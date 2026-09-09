CC      = cc
CFLAGS  = -O2 -Wall $(shell pkg-config --cflags wayland-client libpng)
LDFLAGS = $(shell pkg-config --libs wayland-client libpng) \
          -Wl,--unresolved-symbols=ignore-all

hyprshot: hyprshot.c hyprland-toplevel-export-v1.c hyprland-toplevel-export-v1.h
	$(CC) $(CFLAGS) hyprshot.c hyprland-toplevel-export-v1.c $(LDFLAGS) -o hyprshot

clean:
	rm -f hyprshot

.PHONY: clean
