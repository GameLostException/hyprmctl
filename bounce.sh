#!/bin/bash
# bounce-hyprmctl.sh — kill any running instance and start fresh
pkill -f "python3.*hyprmctl.py" 2>/dev/null
rm -f /tmp/hyprmctl-1000.sock
sleep 0.3
exec python3 /home/boris/Lab/hyprmctl/hyprmctl.py
