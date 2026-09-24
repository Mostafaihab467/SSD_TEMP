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

# 4. Allow X11 root display access for GUI if needed
if command -v xhost &> /dev/null; then
    xhost +si:localuser:root 2>/dev/null || true
fi

# 5. Launch NVMe Temperature Monitor
echo "[+] Starting NVMe Temperature Monitor..."
if [ "$EUID" -ne 0 ]; then
    # Authenticate sudo interactively in foreground so password prompt works properly
    if [ -t 0 ] && sudo -v 2>/dev/null; then
        sudo modprobe drivetemp 2>/dev/null || true
        sudo -E python3 "$SCRIPT_DIR/nvme_monitor.py" "$@" &
    else
        # Launch unprivileged (works with sysfs hwmon and user in disk group)
        python3 "$SCRIPT_DIR/nvme_monitor.py" "$@" &
    fi
else
    modprobe drivetemp 2>/dev/null || true
    python3 "$SCRIPT_DIR/nvme_monitor.py" "$@" &
fi

echo "[+] Monitor launched in background."
