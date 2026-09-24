import sys
import os
import glob
import re
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
    "target_device": "/dev/sdc" if IS_WINDOWS else "/dev/sdb",
    "target_device_windows": "/dev/sdc",
    "target_device_linux": "/dev/sdb",
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
            # On Linux: only re-exec with sudo if running in an interactive terminal
            # Avoid breaking headless/autostart launches when no TTY is available
            if sys.stdin and sys.stdin.isatty() and os.environ.get("SUDO_ATTEMPTED") != "1":
                script = os.path.abspath(__file__)
                try:
                    env = os.environ.copy()
                    env["SUDO_ATTEMPTED"] = "1"
                    os.execvpe("sudo", ["sudo", "-E", sys.executable, script] + sys.argv[1:], env)
                except Exception as e:
                    print("Note: Running unprivileged on Linux:", e)

def scan_drives():
    drives = []
    smartctl = shutil.which("smartctl") or ("/usr/sbin/smartctl" if not IS_WINDOWS else DEFAULT_CONFIG["smartctl_path"])
    
    if smartctl and os.path.exists(smartctl):
        try:
            startupinfo = None
            creationflags = 0
            if IS_WINDOWS:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                creationflags = 0x08000000
            p = subprocess.run(
                [smartctl, "--scan"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=2,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            for line in p.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.match(r"^(\S+)\s+-d\s+(\S+)\s*(?:#\s*(.*))?", line)
                if match:
                    dev, dtype, comment = match.groups()
                    comment = comment.strip() if comment else ""
                    label = comment if comment else f"{dev} ({dtype})"
                    if "Realtek" in comment or "sntrealtek" in dtype:
                        label = "USB-C NVMe (Realtek)"
                    elif "Kingston" in comment:
                        label = "Internal M.2 NVMe (Kingston)"
                    elif "NVMe" in comment or dtype == "nvme":
                        label = f"Internal NVMe ({os.path.basename(dev)})"
                    drives.append({
                        "device": dev,
                        "type": dtype,
                        "label": label,
                        "comment": comment
                    })
        except Exception:
            pass

    # On Linux, also scan sysfs hwmon for internal NVMe drives
    if not IS_WINDOWS:
        for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
            try:
                name_p = os.path.join(hwmon, "name")
                if os.path.exists(name_p) and open(name_p).read().strip() == "nvme":
                    dev_p = os.path.realpath(os.path.join(hwmon, "device"))
                    dev_base = os.path.basename(dev_p)
                    dev_node = f"/dev/{dev_base}"
                    if not any(d["device"] == dev_node or (d["device"].startswith("/dev/nvme") and dev_node.startswith("/dev/nvme")) for d in drives):
                        drives.append({
                            "device": dev_node,
                            "type": "nvme",
                            "label": f"Internal NVMe ({dev_base})",
                            "comment": f"hwmon ({os.path.basename(hwmon)})"
                        })
            except Exception:
                pass

    return drives

def read_hwmon_nvme(target=None):
    """
    Directly reads NVMe temperatures from Linux /sys/class/hwmon without requiring root.
    Returns (s1, s2, composite, error_string)
    """
    if IS_WINDOWS:
        return None, None, None, "hwmon only available on Linux"
        
    nvme_name = ""
    if target:
        base = os.path.basename(target)
        match = re.match(r"(nvme\d+)", base)
        if match:
            nvme_name = match.group(1)
            
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            name_p = os.path.join(hwmon, "name")
            if not os.path.exists(name_p):
                continue
            with open(name_p, "r") as f:
                hname = f.read().strip()
                
            if hname != "nvme":
                continue
                
            dev_p = os.path.realpath(os.path.join(hwmon, "device"))
            if nvme_name and nvme_name not in os.path.basename(dev_p):
                continue
                
            composite = None
            s1 = None
            s2 = None
            labels = {}
            for input_file in sorted(glob.glob(os.path.join(hwmon, "temp*_input"))):
                prefix = input_file[:-6]
                lbl_file = prefix + "_label"
                lbl_text = ""
                if os.path.exists(lbl_file):
                    try:
                        with open(lbl_file, "r") as f:
                            lbl_text = f.read().strip().lower()
                    except:
                        pass
                if not lbl_text:
                    lbl_text = os.path.basename(prefix).lower()
                    
                try:
                    with open(input_file, "r") as f:
                        val = round(int(f.read().strip()) / 1000.0)
                        labels[lbl_text] = val
                except:
                    pass
                    
            for lbl, val in labels.items():
                if "composite" in lbl:
                    composite = val
                elif "sensor 1" in lbl or "nand" in lbl or "flash" in lbl:
                    s1 = val
                elif "sensor 2" in lbl or "controller" in lbl or "asic" in lbl:
                    s2 = val
                    
            if composite is None and "temp1" in labels:
                composite = labels["temp1"]
            if s1 is None:
                s1 = composite
            if s2 is None:
                for lbl, val in labels.items():
                    if val != composite:
                        s2 = val
                        break
                if s2 is None:
                    s2 = composite
                    
            if s1 is not None or s2 is not None:
                return s1, s2, composite, None
        except Exception:
            continue
            
    return None, None, None, "No matching NVMe hwmon sensor found"

def resolve_target_device(config):
    target = config.get("target_device", "")
    dev_type = config.get("device_type", "")
    label = config.get("device_label", "")

    if IS_WINDOWS:
        target = config.get("target_device_windows") or target or "/dev/sdc"
        return target, dev_type, label

    # On Linux:
    # If current target exists on Linux, use it
    if target and (os.path.exists(target) or target.startswith("/dev/nvme")):
        return target, dev_type, label

    # Check target_device_linux
    target_linux = config.get("target_device_linux")
    if target_linux and (os.path.exists(target_linux) or target_linux.startswith("/dev/nvme")):
        config["target_device"] = target_linux
        return target_linux, dev_type, label

    # Auto-resolve using scanned drives on Linux
    drives = scan_drives()
    matched = None

    if dev_type:
        for d in drives:
            if d.get("type") == dev_type:
                matched = d
                break

    if not matched and label:
        lbl_lower = label.lower()
        for d in drives:
            d_lbl = d.get("label", "").lower()
            d_cmt = d.get("comment", "").lower()
            if ("realtek" in lbl_lower and ("realtek" in d_lbl or "realtek" in d_cmt)) or \
               ("kingston" in lbl_lower and ("kingston" in d_lbl or "kingston" in d_cmt or d.get("type") == "nvme")) or \
               ("nvme" in lbl_lower and d.get("type") == "nvme"):
                matched = d
                break

    if not matched and drives:
        for d in drives:
            if d.get("type") in ("sntrealtek", "nvme"):
                matched = d
                break
        if not matched:
            matched = drives[0]

    if matched:
        target = matched["device"]
        dev_type = matched["type"]
        label = matched["label"]
        config["target_device"] = target
        config["target_device_linux"] = target
        config["device_type"] = dev_type
        config["device_label"] = label
        save_config(config)

    return target, dev_type, label

def load_config():
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
                cfg.update(user_cfg)
        except Exception as e:
            print("Error loading config:", e)

    if IS_WINDOWS:
        if not cfg.get("smartctl_path") or not os.path.exists(cfg.get("smartctl_path", "")):
            cfg["smartctl_path"] = shutil.which("smartctl") or DEFAULT_CONFIG["smartctl_path"]
        if cfg.get("target_device_windows"):
            cfg["target_device"] = cfg["target_device_windows"]
    else:
        current_smartctl = cfg.get("smartctl_path", "")
        if not current_smartctl or not os.path.exists(current_smartctl):
            detected = shutil.which("smartctl") or "/usr/sbin/smartctl" or "/usr/bin/smartctl"
            if os.path.exists(detected):
                cfg["smartctl_path"] = detected
        resolve_target_device(cfg)

    return cfg

def save_config(cfg):
    try:
        if IS_WINDOWS:
            cfg["target_device_windows"] = cfg.get("target_device")
        else:
            cfg["target_device_linux"] = cfg.get("target_device")

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
        # Use actual user's home directory even if running under sudo
        user_home = os.path.expanduser(f"~{os.environ['SUDO_USER']}") if "SUDO_USER" in os.environ else os.path.expanduser("~")
        autostart_dir = os.path.join(user_home, ".config", "autostart")
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
                try:
                    os.remove(desktop_file)
                except Exception:
                    pass

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
        target, dev_type, label = resolve_target_device(self.config)
        
        # 1. On Linux, if target is an internal NVMe, read directly via /sys/class/hwmon (no root needed)
        if not IS_WINDOWS and (dev_type == "nvme" or (target and "nvme" in target)):
            s1, s2, comp, err = read_hwmon_nvme(target)
            if s1 is not None or s2 is not None:
                return s1, s2, comp, None

        # 2. Try smartctl
        smartctl = self.config.get("smartctl_path", "")
        if not smartctl or not os.path.exists(smartctl):
            smartctl = shutil.which("smartctl") or ("/usr/sbin/smartctl" if not IS_WINDOWS else DEFAULT_CONFIG["smartctl_path"])
            
        if not os.path.exists(smartctl) and not shutil.which(smartctl):
            if not IS_WINDOWS:
                s1, s2, comp, err = read_hwmon_nvme(target)
                if s1 is not None or s2 is not None:
                    return s1, s2, comp, None
            return None, None, None, f"smartctl not found at {smartctl}"
            
        cmd = [smartctl, "-j", "-A"]
        if dev_type:
            cmd.extend(["-d", dev_type])
        cmd.append(target)
        
        startupinfo = None
        creationflags = 0
        if IS_WINDOWS:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0
            creationflags = 0x08000000  # CREATE_NO_WINDOW

        data = None
        err_msg = None
        try:
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            out, err = p.communicate(timeout=3)
            raw = out.decode("utf-8", errors="ignore")
            if raw.strip():
                data = json.loads(raw)
        except Exception as e:
            err_msg = str(e)

        # On Linux: check if permission denied, attempt sudo -n
        is_permission_error = False
        if data and "smartctl" in data and "messages" in data["smartctl"]:
            for m in data["smartctl"]["messages"]:
                if "permission denied" in m.get("string", "").lower():
                    is_permission_error = True
                    err_msg = m.get("string")
                    break

        if not IS_WINDOWS and not is_admin() and (is_permission_error or (not data and err_msg)):
            try:
                p = subprocess.Popen(
                    ["sudo", "-n"] + cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                out, err = p.communicate(timeout=3)
                raw = out.decode("utf-8", errors="ignore")
                if raw.strip():
                    sudo_data = json.loads(raw)
                    if "nvme_smart_health_information_log" in sudo_data or "temperature" in sudo_data:
                        data = sudo_data
                        err_msg = None
            except:
                pass

        composite_temp = None
        s1 = None
        s2 = None

        if data:
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

        # Fallback to hwmon on Linux if smartctl returned no sensor data
        if not IS_WINDOWS and s1 is None and s2 is None:
            hs1, hs2, hcomp, herr = read_hwmon_nvme(target)
            if hs1 is not None or hs2 is not None:
                return hs1, hs2, hcomp, None

        if s1 is None and s2 is None:
            if not err_msg and data and "smartctl" in data and "messages" in data["smartctl"]:
                err_msg = "; ".join(m.get("string", "") for m in data["smartctl"]["messages"])
            return None, None, None, err_msg or "No temperature data available"

        return s1, s2, composite_temp, None

    def update_temperature(self):
        s1, s2, composite, err = self.read_smart_data()
        
        if s2 is None and s1 is None:
            self.label_s2_temp.setText("N/A")
            self.label_s1_temp.setText("N/A")
            self.badge_status.setText("DISC")
            self.badge_status.setStyleSheet("background-color: #64748b; color: #ffffff; border-radius: 4px; padding: 1px 6px; font-size: 9px; font-weight: 700;")
            self.update_container_style("#64748b")
            tip = f"Device: {self.config.get('target_device')}\nStatus: Disconnected / No Data"
            if err:
                tip += f"\nError: {err}"
            self.setToolTip(tip)
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
        
        tip = f"Device: {self.label_drive.text()} ({self.config.get('target_device')})\nSensor 2 (Controller): {target_s2}°C\nSensor 1 (Flash): {s1}°C"
        if composite is not None:
            tip += f"\nComposite: {composite}°C"
        self.setToolTip(tip)

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
        drives = scan_drives()
        active_target = self.config.get("target_device")
        
        if drives:
            for d in drives:
                dev = d["device"]
                dtype = d["type"]
                lbl = d["label"]
                is_active = (dev == active_target)
                prefix = "● " if is_active else "   "
                act = drive_menu.addAction(f"{prefix}{lbl} [{dev}]")
                act.triggered.connect(lambda chk, t=dev, dt=dtype, l=lbl: self.switch_drive(t, dt, l))
            drive_menu.addSeparator()
            act_rescan = drive_menu.addAction("🔄 Rescan Drives")
            act_rescan.triggered.connect(self.rescan_drives)
        else:
            if IS_WINDOWS:
                act_realtek = drive_menu.addAction("USB-C NVMe (Realtek) [/dev/sdc]")
                act_realtek.triggered.connect(lambda: self.switch_drive("/dev/sdc", "sntrealtek", "USB-C NVMe (Realtek)"))
                act_kingston = drive_menu.addAction("Internal M.2 NVMe (Kingston) [/dev/sdb]")
                act_kingston.triggered.connect(lambda: self.switch_drive("/dev/sdb", "nvme", "Internal NVMe"))
            else:
                act_realtek = drive_menu.addAction("USB-C NVMe (Realtek) [/dev/sdb]")
                act_realtek.triggered.connect(lambda: self.switch_drive("/dev/sdb", "sntrealtek", "USB-C NVMe (Realtek)"))
                act_kingston = drive_menu.addAction("Internal M.2 NVMe (Kingston) [/dev/nvme0]")
                act_kingston.triggered.connect(lambda: self.switch_drive("/dev/nvme0", "nvme", "Internal NVMe"))

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

    def rescan_drives(self):
        resolve_target_device(self.config)
        self.label_drive.setText(self.config.get("device_label", "NVMe Drive"))
        self.update_temperature()

    def switch_drive(self, target, dev_type, label):
        self.config["target_device"] = target
        self.config["device_type"] = dev_type
        self.config["device_label"] = label
        if IS_WINDOWS:
            self.config["target_device_windows"] = target
        else:
            self.config["target_device_linux"] = target
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
