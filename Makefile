# Makefile — hyprmctl
#
# Targets:
#   make build     → build the hyprshot capture helper (required once)
#   make run       → start the daemon (foreground, for testing)
#   make test      → run the test suite (headless, no Wayland needed)
#   make lint      → run ruff linter
#   make bounce    → kill running daemon and restart fresh
#   make clean     → remove hyprshot binary

PYTHON    := python3
HYPRSHOT  := hyprshot/hyprshot

.PHONY: build run test lint bounce clean help

## Build hyprshot (required before first run)
build:
	$(MAKE) -C hyprshot

## Start the daemon in the foreground
run: build
	$(PYTHON) hyprmctl.py

## Run tests (no Wayland required)
test:
	GDK_BACKEND=offscreen $(PYTHON) -m pytest tests/ -v

## Run tests with coverage
coverage:
	GDK_BACKEND=offscreen $(PYTHON) -m pytest tests/ --cov=src --cov-report=term-missing

## Lint with ruff
lint:
	ruff check src/ tests/

## Kill running daemon and restart
bounce:
	@bash bounce.sh

## Remove build artefacts
clean:
	$(MAKE) -C hyprshot clean

## Show available targets
help:
	@echo "Targets: build  run  test  coverage  lint  bounce  clean"
