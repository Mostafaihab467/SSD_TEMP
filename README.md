# NVMe Temperature HUD Monitor

A lightweight, translucent HUD overlay widget in Python (PyQt5) to monitor your NVMe temperature in real time, featuring dedicated monitoring for **Sensor 1 (NAND Flash)** and **Sensor 2 (Controller ASIC)** on both **Linux** and **Windows**.

## Why Sensor 2 is Critical
- **Sensor 1 (Flash)**: Measures the NAND memory cells. NAND flash operates comfortably between 30°C and 60°C.
- **Sensor 2 (Controller)**: Measures the central NVMe processor/ASIC. Under heavy read/write loads (especially in a sealed USB enclosure), this is the sensor that skyrockets to 80°C–105°C and triggers emergency thermal shutdown.

## Features
- **Prominent Sensor 2 (Hero Metric)**: Displayed in large, bold numbers with real-time status color coding and peak tracking.
- **Sensor 1 Row**: Displays NAND flash temperature alongside.
- **Cross-Platform Compatibility**: Full seamless support for both Windows and Linux without path conflicts or config corruption.
- **Direct Linux Sysfs / Hwmon Support**: Directly reads internal NVMe temperature sensors from `/sys/class/hwmon` on Linux with zero root / sudo required!
- **Dynamic Drive Scanner**: Right-click context menu scans and lists all available drives on your system (internal M.2 NVMe drives, USB NVMe bridges like Realtek RTL9210, etc.).
- **Always-on-top HUD**: Stays visible above full-screen and windowed apps.
- **Top-Right Placement**: Anchored to the top right of your screen (offset configurable).
- **Translucent Glassmorphism**: Configurable 50% - 60% opacity (default: 55%).
- **Color-Coded Status Alerts** (based on Sensor 2):
  - 🟢 **GOOD** (`< 60°C`)
  - 🟡 **WARM** (`60°C - 75°C`)
  - 🟠 **HIGH** (`75°C - 85°C`) + Warning Notification
  - 🔴 **CRITICAL!** (`≥ 85°C`) + Critical Toast Alert
- **Draggable**: Click and drag anywhere on the widget to reposition.
- **Right-Click Context Menu**:
  - Change opacity on the fly (40%, 50%, 60%, 70%, 85%, 100%).
  - Change refresh interval (1s, 2s, 3s, 5s).
  - Select detected drives and rescan on the fly.
  - Reset position to top-right.
  - Toggle Auto-Start with OS (Windows Task Scheduler or Linux `.config/autostart`).

## Quick Start

### On Linux:
```bash
./start.sh
```
Or directly:
```bash
python3 nvme_monitor.py
```
> **Tip for USB NVMe enclosures on Linux without sudo:**  
> Add your user to the `disk` group so `smartctl` can access USB disk nodes directly:  
> `sudo usermod -aG disk $USER` (then log out and log back in).

### On Windows:
Double-click `start.bat` or run:
```bat
start_monitor.bat
```
