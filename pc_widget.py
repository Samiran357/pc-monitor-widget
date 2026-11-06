"""
PC Monitor Widget for Windows 10
Shows CPU, RAM, temperature, disk, network, battery, uptime
and the apps using the most RAM. Draggable, frameless, always on your desktop.

Run:  python pc_widget.py
"""
import json
import os
import sys
import threading
import time
import tkinter as tk
from datetime import datetime

import psutil

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".pc_widget.json")

BG = "#14161c"
CARD = "#1d2029"
FG = "#e6e9f0"
MUTED = "#8b93a7"
GREEN = "#3ddc97"
YELLOW = "#ffc857"
RED = "#ff5c5c"
BLUE = "#5aa9ff"

WIDTH = 290
REFRESH_MS = 1000


# ---------------------------------------------------------------- config
def load_config():
    cfg = {"x": 40, "y": 40, "topmost": False, "alpha": 0.93, "locked": False}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except Exception:
        pass


# ---------------------------------------------------------------- helpers
def fmt_bytes(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def fmt_speed(bps):
    return fmt_bytes(bps) + "/s"


def fmt_uptime(seconds):
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    return (f"{d}d " if d else "") + f"{h}h {m}m"


def temp_color(t):
    if t is None:
        return MUTED
    if t < 60:
        return GREEN
    if t < 80:
        return YELLOW
    return RED


def pct_color(p):
    if p < 60:
        return GREEN
    if p < 85:
        return YELLOW
    return RED


# ---------------------------------------------------------------- start with Windows
APP_NAME = "PCMonitorWidget"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command():
    """Command Windows should run at sign-in (works for both .exe and .py)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def autostart_enabled():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_NAME)
            return True
    except Exception:
        return False


def set_autostart(enable):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError:
                pass


_mutex_handle = None


def already_running():
    """True if another copy of the widget is already open."""
    global _mutex_handle
    try:
        import ctypes
        _mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, "PCMonitorWidgetMutex")
        return ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


# ---------------------------------------------------------------- slow sensors (background thread)
class SlowData:
    """Temperature + top-process scan run in a thread so the UI never freezes."""

    def __init__(self):
        self.cpu_temp = None
        self.gpu_temp = None
        self.temp_source = ""
        self.top_apps = []  # [(name, bytes, count)]
        self._stop = False
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self):
        self._stop = True

    def _loop(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        while not self._stop:
            try:
                self._read_temps()
            except Exception:
                pass
            try:
                self._read_top_apps()
            except Exception:
                pass
            time.sleep(2.5)

    def _read_temps(self):
        try:
            import wmi
        except Exception:
            return

        # 1) LibreHardwareMonitor / OpenHardwareMonitor (accurate, must be running)
        for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
            try:
                w = wmi.WMI(namespace=ns)
                sensors = [s for s in w.Sensor() if s.SensorType == "Temperature"]
                if not sensors:
                    continue
                cpu = [s.Value for s in sensors
                       if any(k in s.Name.lower() for k in ("cpu package", "package", "cpu core", "core (tctl", "tctl"))]
                if not cpu:
                    cpu = [s.Value for s in sensors if "cpu" in s.Name.lower()]
                gpu = [s.Value for s in sensors if "gpu" in s.Name.lower()]
                self.cpu_temp = max(cpu) if cpu else None
                self.gpu_temp = max(gpu) if gpu else None
                self.temp_source = ns.split("\\")[-1]
                return
            except Exception:
                continue

        # 2) ACPI thermal zone (works on some PCs, may need Administrator)
        try:
            w = wmi.WMI(namespace="root\\wmi")
            zones = w.MSAcpi_ThermalZoneTemperature()
            vals = [(z.CurrentTemperature / 10.0) - 273.15 for z in zones]
            vals = [v for v in vals if 0 < v < 130]
            if vals:
                self.cpu_temp = max(vals)
                self.gpu_temp = None
                self.temp_source = "ACPI"
                return
        except Exception:
            pass

        self.cpu_temp = None
        self.gpu_temp = None
        self.temp_source = ""

    def _read_top_apps(self):
        totals = {}
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                name = p.info["name"] or "?"
                mem = p.info["memory_info"].rss
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
            if name in ("System Idle Process", "Memory Compression"):
                continue
            t = totals.setdefault(name, [0, 0])
            t[0] += mem
            t[1] += 1
        ranked = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)[:3]
        self.top_apps = [(n, v[0], v[1]) for n, v in ranked]


# ---------------------------------------------------------------- widget
class Widget:
    def __init__(self):
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.title("PC Monitor")
        self.root.overrideredirect(True)
        self.root.configure(bg=BG)
        self.root.attributes("-alpha", self.cfg["alpha"])
        self.root.attributes("-topmost", self.cfg["topmost"])
        self.root.geometry(f"{WIDTH}x10+{self.cfg['x']}+{self.cfg['y']}")

        self.slow = SlowData()
        self.last_net = psutil.net_io_counters()
        self.last_net_t = time.time()
        psutil.cpu_percent(None)

        self._drag = (0, 0)
        self._build()
        self._bind_all(self.root)
        self._make_menu()
        self.root.update_idletasks()
        self.root.geometry(f"{WIDTH}x{self.root.winfo_reqheight()}+{self.cfg['x']}+{self.cfg['y']}")
        self._tick()

    # ---- UI construction
    def _build(self):
        pad = tk.Frame(self.root, bg=BG)
        pad.pack(fill="both", expand=True, padx=12, pady=10)

        # header: time + date
        head = tk.Frame(pad, bg=BG)
        head.pack(fill="x")
        self.clock = tk.Label(head, text="", bg=BG, fg=FG, font=("Segoe UI Semibold", 22))
        self.clock.pack(side="left")
        self.date = tk.Label(head, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="right")
        self.date.pack(side="right", pady=(8, 0))

        self.cpu_val, self.cpu_bar = self._meter(pad, "CPU")
        self.ram_val, self.ram_bar = self._meter(pad, "RAM")
        self.ram_sub = tk.Label(pad, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self.ram_sub.pack(fill="x")
        self.disk_val, self.disk_bar = self._meter(pad, "DISK C:")

        # temperature card
        tcard = tk.Frame(pad, bg=CARD)
        tcard.pack(fill="x", pady=(8, 0))
        self.temp_cpu = tk.Label(tcard, text="CPU --", bg=CARD, fg=MUTED, font=("Segoe UI Semibold", 11))
        self.temp_cpu.pack(side="left", padx=10, pady=6)
        self.temp_gpu = tk.Label(tcard, text="", bg=CARD, fg=MUTED, font=("Segoe UI Semibold", 11))
        self.temp_gpu.pack(side="left", padx=4)
        self.temp_note = tk.Label(tcard, text="", bg=CARD, fg=MUTED, font=("Segoe UI", 7))
        self.temp_note.pack(side="right", padx=8)

        # top apps
        tk.Label(pad, text="TOP RAM APPS", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 8),
                 anchor="w").pack(fill="x", pady=(10, 2))
        self.app_labels = []
        for _ in range(3):
            row = tk.Frame(pad, bg=BG)
            row.pack(fill="x")
            n = tk.Label(row, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w")
            n.pack(side="left")
            v = tk.Label(row, text="", bg=BG, fg=BLUE, font=("Segoe UI Semibold", 9), anchor="e")
            v.pack(side="right")
            self.app_labels.append((n, v))

        # footer stats
        sep = tk.Frame(pad, bg=CARD, height=1)
        sep.pack(fill="x", pady=8)
        self.net_lbl = tk.Label(pad, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w")
        self.net_lbl.pack(fill="x")
        self.bat_lbl = tk.Label(pad, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w")
        self.bat_lbl.pack(fill="x")
        self.up_lbl = tk.Label(pad, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.up_lbl.pack(fill="x")

    def _meter(self, parent, title):
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x", pady=(8, 0))
        top = tk.Frame(frame, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text=title, bg=BG, fg=MUTED, font=("Segoe UI Semibold", 8)).pack(side="left")
        val = tk.Label(top, text="--", bg=BG, fg=FG, font=("Segoe UI Semibold", 10))
        val.pack(side="right")
        bar = tk.Canvas(frame, height=6, bg=CARD, highlightthickness=0)
        bar.pack(fill="x", pady=(2, 0))
        return val, bar

    def _set_bar(self, canvas, pct):
        canvas.update_idletasks()
        w = canvas.winfo_width()
        canvas.delete("all")
        canvas.create_rectangle(0, 0, w * min(pct, 100) / 100, 6, fill=pct_color(pct), width=0)

    # ---- interactions
    def _bind_all(self, widget):
        widget.bind("<Button-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._do_drag)
        widget.bind("<ButtonRelease-1>", self._end_drag)
        widget.bind("<Button-3>", self._popup)
        for child in widget.winfo_children():
            self._bind_all(child)

    def _start_drag(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _do_drag(self, e):
        if self.cfg["locked"]:
            return
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _end_drag(self, _e):
        self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
        save_config(self.cfg)

    def _make_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.var_top = tk.BooleanVar(value=self.cfg["topmost"])
        self.var_lock = tk.BooleanVar(value=self.cfg["locked"])
        self.menu.add_checkbutton(label="Always on top", variable=self.var_top, command=self._toggle_top)
        self.menu.add_checkbutton(label="Lock position", variable=self.var_lock, command=self._toggle_lock)
        self.var_auto = tk.BooleanVar(value=autostart_enabled())
        self.menu.add_checkbutton(label="Start with Windows", variable=self.var_auto, command=self._toggle_autostart)
        alpha = tk.Menu(self.menu, tearoff=0)
        for pct in (100, 90, 80, 70, 60, 50):
            alpha.add_command(label=f"{pct}%", command=lambda p=pct: self._set_alpha(p / 100))
        self.menu.add_cascade(label="Opacity", menu=alpha)
        self.menu.add_separator()
        self.menu.add_command(label="Open Task Manager", command=lambda: os.startfile("taskmgr"))
        self.menu.add_separator()
        self.menu.add_command(label="Close widget", command=self.quit)

    def _popup(self, e):
        self.menu.tk_popup(e.x_root, e.y_root)

    def _toggle_top(self):
        self.cfg["topmost"] = self.var_top.get()
        self.root.attributes("-topmost", self.cfg["topmost"])
        save_config(self.cfg)

    def _toggle_autostart(self):
        try:
            set_autostart(self.var_auto.get())
        except Exception:
            self.var_auto.set(not self.var_auto.get())

    def _toggle_lock(self):
        self.cfg["locked"] = self.var_lock.get()
        save_config(self.cfg)

    def _set_alpha(self, a):
        self.cfg["alpha"] = a
        self.root.attributes("-alpha", a)
        save_config(self.cfg)

    def quit(self):
        self.slow.stop()
        save_config(self.cfg)
        self.root.destroy()

    # ---- refresh loop
    def _tick(self):
        now = datetime.now()
        self.clock.config(text=now.strftime("%I:%M %p").lstrip("0"))
        self.date.config(text=now.strftime("%A\n%d %b %Y"))

        cpu = psutil.cpu_percent(None)
        self.cpu_val.config(text=f"{cpu:.0f}%  •  {psutil.cpu_count()} threads", fg=pct_color(cpu))
        self._set_bar(self.cpu_bar, cpu)

        vm = psutil.virtual_memory()
        self.ram_val.config(text=f"{vm.percent:.0f}%", fg=pct_color(vm.percent))
        self._set_bar(self.ram_bar, vm.percent)
        self.ram_sub.config(text=f"{fmt_bytes(vm.used)} used of {fmt_bytes(vm.total)}  •  {fmt_bytes(vm.available)} free")

        try:
            du = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
            self.disk_val.config(text=f"{du.percent:.0f}%  •  {fmt_bytes(du.free)} free", fg=pct_color(du.percent))
            self._set_bar(self.disk_bar, du.percent)
        except Exception:
            self.disk_val.config(text="n/a")

        # temperatures
        ct, gt = self.slow.cpu_temp, self.slow.gpu_temp
        if ct is not None:
            self.temp_cpu.config(text=f"CPU {ct:.0f}°C", fg=temp_color(ct))
            self.temp_note.config(text=self.slow.temp_source)
        else:
            self.temp_cpu.config(text="Temp: N/A", fg=MUTED)
            self.temp_note.config(text="start LibreHardwareMonitor")
        if gt is not None:
            self.temp_gpu.config(text=f"GPU {gt:.0f}°C", fg=temp_color(gt))
        else:
            self.temp_gpu.config(text="")

        # top apps
        apps = self.slow.top_apps
        for i, (n, v) in enumerate(self.app_labels):
            if i < len(apps):
                name, mem, count = apps[i]
                label = name.replace(".exe", "")
                if count > 1:
                    label += f" ×{count}"
                n.config(text=f"{i + 1}. {label[:26]}")
                v.config(text=fmt_bytes(mem))
            else:
                n.config(text="")
                v.config(text="")

        # network
        net = psutil.net_io_counters()
        t = time.time()
        dt = max(t - self.last_net_t, 0.001)
        down = (net.bytes_recv - self.last_net.bytes_recv) / dt
        up = (net.bytes_sent - self.last_net.bytes_sent) / dt
        self.last_net, self.last_net_t = net, t
        self.net_lbl.config(text=f"↓ {fmt_speed(down)}    ↑ {fmt_speed(up)}")

        # battery
        try:
            b = psutil.sensors_battery()
        except Exception:
            b = None
        if b is not None:
            state = "charging" if b.power_plugged else "on battery"
            left = ""
            if not b.power_plugged and b.secsleft not in (None, psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
                left = f"  •  {fmt_uptime(b.secsleft)} left"
            self.bat_lbl.config(text=f"Battery {b.percent:.0f}% ({state}){left}")
        else:
            self.bat_lbl.config(text="Power: plugged in (no battery)")

        self.up_lbl.config(text=f"Uptime {fmt_uptime(time.time() - psutil.boot_time())}  •  {len(psutil.pids())} processes")

        self.root.after(REFRESH_MS, self._tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if already_running():
        sys.exit(0)
    Widget().run()
