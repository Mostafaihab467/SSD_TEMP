import sys
import os
import json
import subprocess
import shutil
import ctypes
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtWidgets import QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QMenu, QAction, QSystemTrayIcon

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
IS_WINDOWS = sys.platform == "win32"

DEFAULT_CONFIG = {
    "target_device": "/dev/sdc",
    "device_type": "sntrealtek",
    "device_label": "USB-C NVMe (Realtek)",
    "refresh_rate_sec": 2,
    "opacity": 0.55,
    "position": "top-right",
    "offset_x": 25,
    "offset_y": 25,
    "sensor2_good_threshold_c": 60,
    "sensor2_high_threshold_c": 75,
    "sensor2_critical_threshold_c": 85,
    "enable_notifications": True,
    "run_at_startup": True,
    "smartctl_path": r"C:\Program Files\smartmontools\bin\smartctl.exe" if IS_WINDOWS else "/usr/sbin/smartctl"
}

def is_admin():
    if IS_WINDOWS:
        try:
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            return False
    else:
        return os.geteuid() == 0

def elevate_if_needed():
    if not is_admin():
        if IS_WINDOWS:
            params = f'"{os.path.abspath(__file__)}"'
            result = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable, params, None, 1
            )
            if result > 32:
                sys.exit(0)
        else:
            # On Linux, try re-executing with sudo -E to preserve X11/Wayland DISPLAY
            script = os.path.abspath(__file__)
            try:
                os.execvp("sudo", ["sudo", "-E", sys.executable, script] + sys.argv[1:])
            except Exception as e:
                print("Failed to elevate with sudo:", e)

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                cfg.update(user_cfg)
        except Exception as e:
            print("Error loading config:", e)
            
    # Auto-detect smartctl on Linux if Windows path was left in config
    if not IS_WINDOWS:
        current_smartctl = cfg.get("smartctl_path", "")
        if not os.path.exists(current_smartctl):
            detected = shutil.which("smartctl") or "/usr/sbin/smartctl" or "/usr/bin/smartctl"
            if os.path.exists(detected):
                cfg["smartctl_path"] = detected

    return cfg

def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except Exception as e:
        print("Error saving config:", e)

def manage_startup_task(enable=True):
    if IS_WINDOWS:
        task_name = "NVMeTempMonitor"
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        if not os.path.exists(pythonw):
            pythonw = sys.executable
        script_path = os.path.abspath(__file__)
        
        if enable:
            cmd = f'schtasks /create /tn "{task_name}" /tr "\\"{pythonw}\\" \\"{script_path}\\"" /sc onlogon /rl highest /f'
        else:
            cmd = f'schtasks /delete /tn "{task_name}" /f'
            
        subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        # Linux Autostart via ~/.config/autostart
        autostart_dir = os.path.expanduser("~/.config/autostart")
        desktop_file = os.path.join(autostart_dir, "nvme_monitor.desktop")
        if enable:
            os.makedirs(autostart_dir, exist_ok=True)
            start_sh = os.path.join(os.path.dirname(os.path.abspath(__file__)), "start.sh")
            content = f"""[Desktop Entry]
Type=Application
Name=NVMe Temperature Monitor
Exec={start_sh}
Terminal=false
Categories=System;Monitor;
"""
            try:
                with open(desktop_file, "w") as f:
                    f.write(content)
            except Exception as e:
                print("Failed to write autostart desktop file:", e)
        else:
            if os.path.exists(desktop_file):
                os.remove(desktop_file)

class TempMonitorWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.old_pos = None
        self.max_s2 = None
        self.last_status = None
        
        self.init_ui()
        self.setup_tray()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_temperature)
        interval_ms = int(self.config.get("refresh_rate_sec", 2) * 1000)
        self.timer.start(interval_ms)
        
        self.update_temperature()

    def init_ui(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(float(self.config.get("opacity", 0.55)))

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        
        self.container = QWidget(self)
        self.container.setObjectName("container")
        self.update_container_style("#22c55e")
        
        cont_layout = QVBoxLayout(self.container)
        cont_layout.setContentsMargins(14, 10, 14, 10)
        cont_layout.setSpacing(6)
        
        # Header Row: Drive Name + Status Badge
        header_layout = QHBoxLayout()
        header_layout.setSpacing(6)
        
        self.label_drive = QLabel(self.config.get("device_label", "USB-C NVMe"))
        self.label_drive.setStyleSheet("color: #94a3b8; font-size: 11px; font-weight: 600; font-family: 'Segoe UI', sans-serif;")
        
        self.badge_status = QLabel("GOOD")
        self.badge_status.setStyleSheet(
            "background-color: #15803d; color: #ffffff; border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 700; font-family: 'Segoe UI';"
        )
        
        header_layout.addWidget(self.label_drive)
        header_layout.addStretch()
        header_layout.addWidget(self.badge_status)
        cont_layout.addLayout(header_layout)
        
        # Hero Metric: Sensor 2 (Controller - Most Important)
        s2_box = QVBoxLayout()
        s2_box.setSpacing(1)
        
        s2_header = QHBoxLayout()
        label_s2_title = QLabel("★ SENSOR 2 (CONTROLLER)")
        label_s2_title.setStyleSheet("color: #f87171; font-size: 10px; font-weight: 700; font-family: 'Segoe UI'; letter-spacing: 0.5px;")
        
        self.label_max_s2 = QLabel("Peak: --°C")
        self.label_max_s2.setStyleSheet("color: #64748b; font-size: 10px; font-family: 'Segoe UI';")
        self.label_max_s2.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        s2_header.addWidget(label_s2_title)
        s2_header.addStretch()
        s2_header.addWidget(self.label_max_s2)
        s2_box.addLayout(s2_header)
        
        self.label_s2_temp = QLabel("-- °C")
        self.label_s2_temp.setStyleSheet("color: #22c55e; font-size: 28px; font-weight: 800; font-family: 'Consolas', 'Segoe UI', monospace;")
        s2_box.addWidget(self.label_s2_temp)
        
        cont_layout.addLayout(s2_box)
        
        # Secondary Metric: Sensor 1 (NAND Flash)
        s1_layout = QHBoxLayout()
        s1_layout.setContentsMargins(0, 2, 0, 0)
        
        label_s1_title = QLabel("Sensor 1 (Flash):")
        label_s1_title.setStyleSheet("color: #94a3b8; font-size: 11px; font-family: 'Segoe UI';")
        
        self.label_s1_temp = QLabel("-- °C")
        self.label_s1_temp.setStyleSheet("color: #38bdf8; font-size: 12px; font-weight: 700; font-family: 'Consolas', monospace;")
        
        s1_layout.addWidget(label_s1_title)
        s1_layout.addWidget(self.label_s1_temp)
        s1_layout.addStretch()
        cont_layout.addLayout(s1_layout)
        
        self.main_layout.addWidget(self.container)
        self.setFixedWidth(225)
        self.reposition_window()

    def update_container_style(self, border_color):
        self.container.setStyleSheet(f"""
            QWidget#container {{
                background-color: rgba(15, 23, 42, 220);
                border: 1.5px solid {border_color};
                border-radius: 10px;
            }}
        """)

    def reposition_window(self):
        screen = QApplication.primaryScreen().availableGeometry()
        offset_x = self.config.get("offset_x", 25)
        offset_y = self.config.get("offset_y", 25)
        
        x = screen.width() - self.width() - offset_x
        y = offset_y
        self.move(x, y)

    def setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        pixmap = QtGui.QPixmap(16, 16)
        pixmap.fill(QtGui.QColor(34, 197, 94))
        self.tray.setIcon(QtGui.QIcon(pixmap))
        self.tray.setVisible(True)

    def read_smart_data(self):
        smartctl = self.config.get("smartctl_path", "")
        if not smartctl or not os.path.exists(smartctl):
            smartctl = shutil.which("smartctl") or ("/usr/sbin/smartctl" if not IS_WINDOWS else DEFAULT_CONFIG["smartctl_path"])
            
        if not os.path.exists(smartctl) and not shutil.which(smartctl):
            return None, None, None, f"smartctl not found at {smartctl}"
            
        target = self.config.get("target_device", "/dev/sdc")
        dev_type = self.config.get("device_type", "sntrealtek")
        
        cmd = [smartctl, "-j", "-A"]
        if dev_type:
            cmd.extend(["-d", dev_type])
        cmd.append(target)
        
        try:
            startupinfo = None
            creationflags = 0
            if IS_WINDOWS:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = 0x08000000  # CREATE_NO_WINDOW
            
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            out, err = p.communicate(timeout=3)
            data = json.loads(out.decode("utf-8", errors="ignore"))
            
            composite_temp = None
            s1 = None
            s2 = None
            
            if "temperature" in data and "current" in data["temperature"]:
                composite_temp = data["temperature"]["current"]
            elif "nvme_smart_health_information_log" in data:
                composite_temp = data["nvme_smart_health_information_log"].get("temperature")
            
            if "nvme_smart_health_information_log" in data:
                sensors = data["nvme_smart_health_information_log"].get("temperature_sensors", [])
                if len(sensors) >= 1:
                    s1 = sensors[0]
                if len(sensors) >= 2:
                    s2 = sensors[1]
                    
            if s1 is None:
                s1 = composite_temp
            if s2 is None:
                s2 = composite_temp
            
            return s1, s2, composite_temp, None
        except Exception as e:
            return None, None, None, str(e)

    def update_temperature(self):
        s1, s2, composite, err = self.read_smart_data()
        
        if s2 is None and s1 is None:
            self.label_s2_temp.setText("N/A")
            self.label_s1_temp.setText("N/A")
            self.badge_status.setText("DISC")
            self.badge_status.setStyleSheet("background-color: #64748b; color: #ffffff; border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 700;")
            self.update_container_style("#64748b")
            return

        target_s2 = s2 if s2 is not None else s1
        if self.max_s2 is None or target_s2 > self.max_s2:
            self.max_s2 = target_s2
            self.label_max_s2.setText(f"Peak: {self.max_s2}°C")

        self.label_s2_temp.setText(f"{target_s2}°C")
        if s1 is not None:
            self.label_s1_temp.setText(f"{s1}°C")
        else:
            self.label_s1_temp.setText("--")
            
        good_th = self.config.get("sensor2_good_threshold_c", 60)
        high_th = self.config.get("sensor2_high_threshold_c", 75)
        crit_th = self.config.get("sensor2_critical_threshold_c", 85)
        
        status = "GOOD"
        color = "#22c55e"
        badge_bg = "#15803d"
        
        if target_s2 >= crit_th:
            status = "CRITICAL!"
            color = "#ef4444"
            badge_bg = "#b91c1c"
        elif target_s2 >= high_th:
            status = "HIGH"
            color = "#f97316"
            badge_bg = "#c2410c"
        elif target_s2 > good_th:
            status = "WARM"
            color = "#eab308"
            badge_bg = "#a16207"

        self.label_s2_temp.setStyleSheet(f"color: {color}; font-size: 28px; font-weight: 800; font-family: 'Consolas', 'Segoe UI', monospace;")
        self.badge_status.setText(status)
        self.badge_status.setStyleSheet(f"background-color: {badge_bg}; color: #ffffff; border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 700;")
        self.update_container_style(color)
        
        if self.config.get("enable_notifications", True) and status != self.last_status:
            if status == "CRITICAL!":
                self.tray.showMessage(
                    "🔥 CRITICAL NVMe Sensor 2 Alert!",
                    f"Sensor 2 (Controller) hit {target_s2}°C! Immediate risk of freeze/shutdown.",
                    QSystemTrayIcon.Critical,
                    5000
                )
            elif status == "HIGH":
                self.tray.showMessage(
                    "⚠️ NVMe Sensor 2 High",
                    f"Sensor 2 reached {target_s2}°C (Above warning threshold).",
                    QSystemTrayIcon.Warning,
                    3000
                )
            self.last_status = status

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.old_pos is not None:
            delta = QPoint(event.globalPos() - self.old_pos)
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.old_pos = None

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu {
                background-color: #1e293b;
                color: #f8fafc;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 4px;
            }
            QMenu::item:selected {
                background-color: #3b82f6;
            }
        """)

        opacity_menu = menu.addMenu("Opacity")
        for val in [0.4, 0.5, 0.6, 0.7, 0.85, 1.0]:
            act = opacity_menu.addAction(f"{int(val*100)}%")
            act.triggered.connect(lambda chk, v=val: self.set_opacity(v))

        refresh_menu = menu.addMenu("Refresh Rate")
        for sec in [1, 2, 3, 5]:
            act = refresh_menu.addAction(f"{sec} sec")
            act.triggered.connect(lambda chk, s=sec: self.set_refresh_rate(s))

        drive_menu = menu.addMenu("Select Drive")
        act_realtek = drive_menu.addAction("USB-C NVMe (Realtek)")
        act_realtek.triggered.connect(lambda: self.switch_drive("/dev/sdc", "sntrealtek", "USB-C NVMe (Realtek)"))
        
        act_kingston = drive_menu.addAction("Internal M.2 NVMe (Kingston)")
        act_kingston.triggered.connect(lambda: self.switch_drive("/dev/sdb", "nvme", "Internal NVMe"))

        menu.addSeparator()

        act_reset = menu.addAction("Reset to Top-Right")
        act_reset.triggered.connect(self.reposition_window)

        act_startup = menu.addAction("Toggle Auto-Start with OS")
        act_startup.triggered.connect(self.toggle_startup)

        menu.addSeparator()

        act_exit = menu.addAction("Exit")
        act_exit.triggered.connect(QApplication.instance().quit)

        menu.exec_(event.globalPos())

    def set_opacity(self, val):
        self.setWindowOpacity(val)
        self.config["opacity"] = val
        save_config(self.config)

    def set_refresh_rate(self, sec):
        self.config["refresh_rate_sec"] = sec
        self.timer.setInterval(sec * 1000)
        save_config(self.config)

    def switch_drive(self, target, dev_type, label):
        self.config["target_device"] = target
        self.config["device_type"] = dev_type
        self.config["device_label"] = label
        self.label_drive.setText(label)
        self.max_s2 = None
        self.label_max_s2.setText("Peak: --°C")
        save_config(self.config)
        self.update_temperature()

    def toggle_startup(self):
        curr = self.config.get("run_at_startup", True)
        new_val = not curr
        self.config["run_at_startup"] = new_val
        manage_startup_task(new_val)
        save_config(self.config)
        state_str = "Enabled" if new_val else "Disabled"
        self.tray.showMessage("Startup Setting Updated", f"Auto-start is now {state_str}.", QSystemTrayIcon.Information, 3000)

if __name__ == "__main__":
    elevate_if_needed()
    
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    
    cfg = load_config()
    if cfg.get("run_at_startup", True):
        manage_startup_task(True)

    widget = TempMonitorWidget()
    widget.show()
    sys.exit(app.exec_())
