/*
 * hyprshot.c — capture any Hyprland window by address to PNG on stdout
 *
 * Usage: hyprshot <window_address_hex>
 *   e.g. hyprshot 0x560e46cd71b0
 *
 * Uses hyprland-toplevel-export-v1 to capture the window's framebuffer
 * regardless of Z-order or visibility. Writes PNG to stdout.
 * Exit 0 on success, 1 on failure.
 *
 * Build: cc hyprshot.c hyprland-toplevel-export-v1.c \
 *           $(pkg-config --cflags --libs wayland-client libpng) -o hyprshot
 */

#include <errno.h>
#include <fcntl.h>
#include <png.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>
#include <wayland-client.h>
#include "hyprland-toplevel-export-v1.h"

/* ── State ──────────────────────────────────────────────────────────────── */

static struct {
    struct wl_display                          *display;
    struct wl_registry                         *registry;
    struct wl_shm                              *shm;
    struct hyprland_toplevel_export_manager_v1 *export_manager;
    int                                         version;
} g = {0};

static struct {
    uint32_t format, width, height, stride;
    int      y_invert;
    int      done;   /* 1 = ready, -1 = failed */
    void    *data;
    size_t   size;
    int      shm_fd;
} frame = {0};

/* ── wl_shm helpers ─────────────────────────────────────────────────────── */

static int create_shm_file(size_t size) {
    char name[] = "/hyprshot-XXXXXX";
    int fd = shm_open(name, O_RDWR | O_CREAT | O_EXCL, 0600);
    if (fd < 0) return -1;
    shm_unlink(name);
    if (ftruncate(fd, (off_t)size) < 0) { close(fd); return -1; }
    return fd;
}

/* ── Frame callbacks ────────────────────────────────────────────────────── */

static void frame_buffer(void *data,
    struct hyprland_toplevel_export_frame_v1 *f,
    uint32_t format, uint32_t width, uint32_t height, uint32_t stride)
{
    (void)data; (void)f;
    frame.format = format;
    frame.width  = width;
    frame.height = height;
    frame.stride = stride;
}

static void frame_linux_dmabuf(void *data,
    struct hyprland_toplevel_export_frame_v1 *f,
    uint32_t format, uint32_t width, uint32_t height)
{
    (void)data; (void)f; (void)format; (void)width; (void)height;
    /* ignore — we use shm */
}

static void frame_buffer_done(void *data,
    struct hyprland_toplevel_export_frame_v1 *f)
{
    (void)data;
    /* All buffer formats advertised — now allocate shm and copy */
    frame.size   = frame.stride * frame.height;
    frame.shm_fd = create_shm_file(frame.size);
    if (frame.shm_fd < 0) { frame.done = -1; return; }

    frame.data = mmap(NULL, frame.size, PROT_READ | PROT_WRITE,
                      MAP_SHARED, frame.shm_fd, 0);
    if (frame.data == MAP_FAILED) { frame.done = -1; return; }

    struct wl_shm_pool *pool = wl_shm_create_pool(g.shm, frame.shm_fd, (int32_t)frame.size);
    struct wl_buffer   *buf  = wl_shm_pool_create_buffer(pool, 0,
        (int32_t)frame.width, (int32_t)frame.height,
        (int32_t)frame.stride, frame.format);
    wl_shm_pool_destroy(pool);

    hyprland_toplevel_export_frame_v1_copy(f, buf, 0 /* don't ignore damage */);
    wl_buffer_destroy(buf);
}

static void frame_flags(void *data,
    struct hyprland_toplevel_export_frame_v1 *f, uint32_t flags)
{
    (void)data; (void)f;
    frame.y_invert = !!(flags & HYPRLAND_TOPLEVEL_EXPORT_FRAME_V1_FLAGS_Y_INVERT);
}

static void frame_ready(void *data,
    struct hyprland_toplevel_export_frame_v1 *f,
    uint32_t tv_sec_hi, uint32_t tv_sec_lo, uint32_t tv_nsec)
{
    (void)data; (void)f; (void)tv_sec_hi; (void)tv_sec_lo; (void)tv_nsec;
    frame.done = 1;
}

static void frame_failed(void *data,
    struct hyprland_toplevel_export_frame_v1 *f)
{
    (void)data; (void)f;
    frame.done = -1;
}

static void frame_damage(void *data,
    struct hyprland_toplevel_export_frame_v1 *f,
    uint32_t x, uint32_t y, uint32_t width, uint32_t height)
{
    (void)data; (void)f; (void)x; (void)y; (void)width; (void)height;
}

static const struct hyprland_toplevel_export_frame_v1_listener frame_listener = {
    .buffer      = frame_buffer,
    .linux_dmabuf = frame_linux_dmabuf,
    .buffer_done = frame_buffer_done,
    .flags       = frame_flags,
    .ready       = frame_ready,
    .failed      = frame_failed,
    .damage      = frame_damage,
};

/* ── Registry ───────────────────────────────────────────────────────────── */

static void registry_global(void *data, struct wl_registry *reg,
    uint32_t name, const char *iface, uint32_t version)
{
    (void)data;
    if (strcmp(iface, wl_shm_interface.name) == 0) {
        g.shm = wl_registry_bind(reg, name, &wl_shm_interface, 1);
    } else if (strcmp(iface, hyprland_toplevel_export_manager_v1_interface.name) == 0) {
        g.version = (int)version;
        g.export_manager = wl_registry_bind(reg, name,
            &hyprland_toplevel_export_manager_v1_interface,
            version < 2 ? version : 2);
    }
}

static void registry_global_remove(void *data, struct wl_registry *reg, uint32_t name) {
    (void)data; (void)reg; (void)name;
}

static const struct wl_registry_listener registry_listener = {
    .global        = registry_global,
    .global_remove = registry_global_remove,
};

/* ── PNG output ─────────────────────────────────────────────────────────── */

static int write_png_stdout(uint8_t *pixels, uint32_t width, uint32_t height,
                             uint32_t stride, int y_invert)
{
    png_structp png = png_create_write_struct(PNG_LIBPNG_VER_STRING, NULL, NULL, NULL);
    if (!png) return -1;
    png_infop info = png_create_info_struct(png);
    if (!info) { png_destroy_write_struct(&png, NULL); return -1; }
    if (setjmp(png_jmpbuf(png))) {
        png_destroy_write_struct(&png, &info);
        return -1;
    }

    png_init_io(png, stdout);
    png_set_IHDR(png, info, width, height, 8,
                 PNG_COLOR_TYPE_RGBA, PNG_INTERLACE_NONE,
                 PNG_COMPRESSION_TYPE_DEFAULT, PNG_FILTER_TYPE_DEFAULT);
    png_write_info(png, info);

    /* Convert ARGB/XRGB (wl_shm little-endian) to RGBA row by row */
    uint8_t *row = malloc(width * 4);
    if (!row) { png_destroy_write_struct(&png, &info); return -1; }

    for (uint32_t y = 0; y < height; y++) {
        uint32_t src_y = y_invert ? (height - 1 - y) : y;
        uint8_t *src = pixels + src_y * stride;
        for (uint32_t x = 0; x < width; x++) {
            /* wl_shm XRGB8888 is B G R X in memory (little-endian) */
            uint8_t b = src[x*4 + 0];
            uint8_t gr= src[x*4 + 1];
            uint8_t r = src[x*4 + 2];
            /* uint8_t a = src[x*4 + 3]; */
            row[x*4 + 0] = r;
            row[x*4 + 1] = gr;
            row[x*4 + 2] = b;
            row[x*4 + 3] = 255;  /* opaque */
        }
        png_write_row(png, row);
    }
    free(row);
    png_write_end(png, NULL);
    png_destroy_write_struct(&png, &info);
    return 0;
}

/* ── Main ───────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: hyprshot <window_address_hex>\n");
        return 1;
    }

    /* Parse address: accept "0x..." or plain hex */
    const char *addr_str = argv[1];
    if (strncmp(addr_str, "0x", 2) == 0 || strncmp(addr_str, "0X", 2) == 0)
        addr_str += 2;
    uint64_t addr64 = strtoull(addr_str, NULL, 16);
    uint32_t handle = (uint32_t)(addr64 & 0xFFFFFFFF);

    g.display = wl_display_connect(NULL);
    if (!g.display) { fprintf(stderr, "hyprshot: failed to connect to Wayland\n"); return 1; }

    g.registry = wl_display_get_registry(g.display);
    wl_registry_add_listener(g.registry, &registry_listener, NULL);
    wl_display_roundtrip(g.display);

    if (!g.shm) { fprintf(stderr, "hyprshot: no wl_shm\n"); return 1; }
    if (!g.export_manager) { fprintf(stderr, "hyprshot: no hyprland-toplevel-export-v1\n"); return 1; }

    struct hyprland_toplevel_export_frame_v1 *f =
        hyprland_toplevel_export_manager_v1_capture_toplevel(
            g.export_manager, 0 /* no cursor */, handle);

    hyprland_toplevel_export_frame_v1_add_listener(f, &frame_listener, NULL);

    /* Dispatch until done or failed */
    while (frame.done == 0 && wl_display_dispatch(g.display) != -1)
        ;

    int ret = 1;
    if (frame.done == 1 && frame.data) {
        ret = write_png_stdout(frame.data, frame.width, frame.height,
                               frame.stride, frame.y_invert);
        if (ret != 0) fprintf(stderr, "hyprshot: PNG write failed\n");
    } else {
        fprintf(stderr, "hyprshot: capture failed for handle 0x%x\n", handle);
    }

    if (frame.data && frame.data != MAP_FAILED)
        munmap(frame.data, frame.size);
    if (frame.shm_fd >= 0)
        close(frame.shm_fd);

    hyprland_toplevel_export_frame_v1_destroy(f);
    hyprland_toplevel_export_manager_v1_destroy(g.export_manager);
    wl_display_disconnect(g.display);
    return ret;
}
