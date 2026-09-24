# NVMe Temperature HUD Monitor

A lightweight, translucent HUD overlay widget in Python (PyQt5) to monitor your NVMe temperature in real time, featuring dedicated monitoring for **Sensor 1 (NAND Flash)** and **Sensor 2 (Controller ASIC)**.

## Why Sensor 2 is Critical
- **Sensor 1 (Flash)**: Measures the NAND memory cells. NAND flash operates comfortably between 30°C and 60°C.
- **Sensor 2 (Controller)**: Measures the central NVMe processor/ASIC. Under heavy read/write loads (especially in a sealed USB enclosure), this is the sensor that skyrockets to 80°C–105°C and triggers emergency thermal shutdown.

## Features
- **Prominent Sensor 2 (Hero Metric)**: Displayed in large, bold numbers with real-time status color coding and peak tracking.
- **Sensor 1 Row**: Displays NAND flash temperature alongside.
- **Always-on-top HUD**: Stays visible above full-screen and windowed apps.
- **Top-Right Placement**: Anchored to the top right of your screen (offset configurable).
- **Translucent Glassmorphism**: Configurable 50% - 60% opacity (default: 55%).
- **Color-Coded Status Alerts** (based on Sensor 2):
  - 🟢 **GOOD** (`< 60°C`)
  - 🟡 **WARM** (`60°C - 75°C`)
  - 🟠 **HIGH** (`75°C - 85°C`) + Warning Notification
  - 🔴 **CRITICAL!** (`≥ 85°C`) + Windows Critical Toast Alert
- **Draggable**: Click and drag anywhere on the widget to reposition.
- **Right-Click Context Menu**:
  - Change opacity on the fly (40%, 50%, 60%, 70%, 100%).
  - Change refresh interval (1s, 2s, 3s, 5s).
  - Switch between external USB Realtek NVMe and internal Kingston M.2 NVMe.
  - Reset position to top-right.
  - Toggle Auto-Start with Windows.
- **Auto-Start on Boot**: Runs automatically via Windows Startup folder and Task Scheduler.
