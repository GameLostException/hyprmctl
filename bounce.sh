#!/usr/bin/env bash
# bounce.sh — kill any running hyprmctl instance and start a fresh daemon.
# Useful during development after code changes.

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"

pkill -f "python3.*hyprmctl.py" 2>/dev/null || true
rm -f "/tmp/hyprmctl-${UID}.sock"
sleep 0.3
exec python3 "$SCRIPT_DIR/hyprmctl.py"
