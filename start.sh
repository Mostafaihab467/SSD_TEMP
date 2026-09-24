#!/usr/bin/env bash

# Resolve directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. Check for smartctl
if ! command -v smartctl &> /dev/null; then
    echo "[-] smartctl not found! Please install it with:"
    echo "    Ubuntu/Debian: sudo apt install smartmontools"
    echo "    Arch Linux:    sudo pacman -S smartmontools"
    echo "    Fedora:        sudo dnf install smartmontools"
    echo ""
fi

# 2. Check for python3
if ! command -v python3 &> /dev/null; then
    echo "[-] python3 not found! Please install python3."
    exit 1
fi

# 3. Check for PyQt5
if ! python3 -c "import PyQt5" &> /dev/null; then
    echo "[-] PyQt5 is required. Install it using:"
    echo "    Ubuntu/Debian: sudo apt install python3-pyqt5"
    echo "    Arch Linux:    sudo pacman -S python-pyqt5"
    echo "    Pip:           pip3 install PyQt5"
    echo ""
fi

# 4. Launch with root permissions to query raw SMART disk data
# Note: -E preserves the user's DISPLAY / XAUTHORITY / WAYLAND environment for the GUI
echo "[+] Starting NVMe Temperature Monitor..."
if [ "$EUID" -ne 0 ]; then
    sudo -E python3 "$SCRIPT_DIR/nvme_monitor.py" "$@" &
else
    python3 "$SCRIPT_DIR/nvme_monitor.py" "$@" &
fi

echo "[+] Monitor launched in background."
