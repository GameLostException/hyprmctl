# hyprshot

Small C helper that captures any Hyprland window's framebuffer by address,
using the `hyprland-toplevel-export-v1` Wayland protocol.

Works for any window regardless of Z-order, visibility, or monocle stacking.
Writes PNG to stdout. Used by `src/thumbnails.py` in hyprmctl.

## Build

```bash
cd hyprshot
make
```

Requires: `wayland-client`, `libpng`, `pkg-config`, `cc`

On Arch: `pacman -S wayland libpng pkg-config gcc`

## Usage

```bash
./hyprshot 0x560e46cd71b0   # window address from hyprctl clients -j
# → writes PNG to stdout
```

## Protocol

Uses `hyprland_toplevel_export_manager_v1_capture_toplevel(handle)` where
`handle` is the lower 32 bits of the window address as reported by
`hyprctl clients -j`.

The `hyprland-toplevel-export-v1.{h,c}` glue was generated with:
```bash
wayland-scanner client-header hyprland-toplevel-export-v1.xml hyprland-toplevel-export-v1.h
wayland-scanner private-code  hyprland-toplevel-export-v1.xml hyprland-toplevel-export-v1.c
```

XML source: https://github.com/hyprwm/hyprland-protocols
