"""
PC Monitor Widget for Windows 10
Shows CPU, RAM, temperature, disk, network, battery, uptime
and the apps using the most RAM. Draggable, frameless, always on your desktop.

Run:  python pc_widget.py
"""
import ctypes
import json
import os
import sys
import threading
import time
import tkinter as tk
import traceback
from ctypes import wintypes
from datetime import datetime

import psutil

__version__ = "1.1.0"

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
            saved = json.load(f)
        for key, default in list(cfg.items()):
            try:
                cfg[key] = type(default)(saved[key])
            except Exception:
                pass  # missing or damaged value: keep the default
        cfg["alpha"] = min(1.0, max(0.2, cfg["alpha"]))  # 0 would make the widget invisible
    except Exception:
        pass  # no file yet, or not valid JSON: start with defaults
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
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        _mutex_handle = kernel32.CreateMutexW(None, False, "PCMonitorWidgetMutex")
        return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    except Exception:
        return False


# ---------------------------------------------------------------- display
def enable_dpi_awareness():
    """Stop Windows from stretching the window on scaled displays (125%, 150%...), which blurs the text."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass  # already set, or not available: the widget still works, just less sharp


def on_screen(x, y):
    """False if the point is on no monitor, e.g. a position saved on a screen that is now unplugged."""
    try:
        user32 = ctypes.WinDLL("user32")
        user32.MonitorFromPoint.restype = wintypes.HMONITOR
        user32.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
        return bool(user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 0))
    except Exception:
        return True


# ---------------------------------------------------------------- process memory
# psutil asks Windows about one process at a time, and for the many system processes a normal
# user may not open it falls back to a full system scan *per process*. That cost about 0.8 s of
# CPU every time the "top apps" list was refreshed. One NtQuerySystemInformation call returns
# every process at once, and its "private working set" is the figure Task Manager shows.
class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                ("Buffer", ctypes.c_void_p)]


class _SYSTEM_PROCESS_INFORMATION(ctypes.Structure):
    # Start of each record; the fields after ImageName are not needed here.
    _fields_ = [("NextEntryOffset", wintypes.ULONG),
                ("NumberOfThreads", wintypes.ULONG),
                ("WorkingSetPrivateSize", ctypes.c_longlong),
                ("HardFaultCount", wintypes.ULONG),
                ("NumberOfThreadsHighWatermark", wintypes.ULONG),
                ("CycleTime", ctypes.c_ulonglong),
                ("CreateTime", ctypes.c_longlong),
                ("UserTime", ctypes.c_longlong),
                ("KernelTime", ctypes.c_longlong),
                ("ImageName", _UNICODE_STRING)]


def process_memory():
    """[(name, private working set in bytes)] for every running process, from one system call."""
    query = ctypes.WinDLL("ntdll").NtQuerySystemInformation
    query.restype = ctypes.c_ulong
    query.argtypes = (ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong))
    size = 0x80000
    while True:
        buf = ctypes.create_string_buffer(size)
        needed = ctypes.c_ulong(0)
        status = query(5, buf, size, ctypes.byref(needed))  # 5 = SystemProcessInformation
        if status == 0:
            break
        if status != 0xC0000004:  # anything but STATUS_INFO_LENGTH_MISMATCH (buffer too small)
            raise OSError(f"NtQuerySystemInformation failed: 0x{status:08X}")
        size = max(size, needed.value) + 0x10000
    result, offset = [], 0
    while True:
        p = _SYSTEM_PROCESS_INFORMATION.from_buffer(buf, offset)
        if p.ImageName.Buffer:
            name = ctypes.wstring_at(p.ImageName.Buffer, p.ImageName.Length // 2)
        else:
            name = "System Idle Process"
        result.append((name, p.WorkingSetPrivateSize))
        if not p.NextEntryOffset:
            return result
        offset += p.NextEntryOffset


# ---------------------------------------------------------------- slow sensors (background thread)
class SlowData:
    """Temperature + top-process scan run in a thread so the UI never freezes."""

    def __init__(self):
        self.cpu_temp = None
        self.gpu_temp = None
        self.temp_source = ""
        self.top_apps = []  # [(name, bytes, count)]
        self._cimv2 = None  # WMI connection for the thermal zone, opened on first use
        self._nvml = None  # (library, device handle) once opened; False if there is no NVIDIA driver
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
        next_temps = 0
        while not self._stop:
            if time.time() >= next_temps:
                try:
                    self._read_temps()
                except Exception:
                    pass
                # Temperatures move slowly: every 5 s is plenty. With no source at all, asking
                # WMI every round is wasted work, so look again in 30 s.
                next_temps = time.time() + (5 if self.temp_source else 30)
            try:
                self._read_top_apps()
            except Exception:
                pass
            time.sleep(2.5)

    def _read_temps(self):
        cpu = gpu = None
        source = ""
        try:
            import wmi
        except Exception:
            wmi = None

        # 1) LibreHardwareMonitor / OpenHardwareMonitor (most accurate, must be running)
        if wmi:
            for ns in ("root\\LibreHardwareMonitor", "root\\OpenHardwareMonitor"):
                try:
                    w = wmi.WMI(namespace=ns)
                    # "Distance to TjMax" sensors are headroom, not a temperature: on a cool CPU
                    # they are the largest value and would be shown as the CPU temperature.
                    sensors = [s for s in w.Sensor() if s.SensorType == "Temperature"
                               and "tjmax" not in s.Name.lower()]
                    if not sensors:
                        continue
                    cpus = [s.Value for s in sensors
                            if any(k in s.Name.lower() for k in ("cpu package", "package", "cpu core", "core (tctl", "tctl"))]
                    if not cpus:
                        cpus = [s.Value for s in sensors if "cpu" in s.Name.lower()]
                    gpus = [s.Value for s in sensors if "gpu" in s.Name.lower()]
                    # "GPU Core" is the figure other tools show; "GPU Hot Spot" runs 10-15 degrees hotter
                    gpu_core = [s.Value for s in sensors if "gpu core" in s.Name.lower()]
                    cpu = max(cpus) if cpus else None
                    gpu = max(gpu_core or gpus) if gpus else None
                    source = ns.split("\\")[-1]
                    break
                except Exception:
                    continue

        # 2) ACPI thermal zone through its performance counter: works for normal users on many
        #    laptops (the root\wmi class needs Administrator). Some desktops have no zone.
        if cpu is None and wmi:
            cpu = self._thermal_zone_temp(wmi)
            if cpu is not None:
                source = "ACPI"

        # 3) GPU temperature straight from the NVIDIA driver (no NVIDIA GPU: stays empty)
        if gpu is None:
            gpu = self._nvidia_temp()
            if gpu is not None:
                source = "ACPI · NVIDIA" if source == "ACPI" else (source or "NVIDIA")

        self.cpu_temp, self.gpu_temp, self.temp_source = cpu, gpu, source

    def _thermal_zone_temp(self, wmi_module):
        """Hottest ACPI thermal zone in °C, or None if Windows reports none."""
        try:
            if self._cimv2 is None:
                self._cimv2 = wmi_module.WMI()  # kept open: connecting costs more than the query
            vals = []
            for z in self._cimv2.Win32_PerfRawData_Counters_ThermalZoneInformation():
                kelvin = z.HighPrecisionTemperature / 10.0 if z.HighPrecisionTemperature else float(z.Temperature)
                vals.append(kelvin - 273.15)
            vals = [v for v in vals if 0 < v < 130]
            return max(vals) if vals else None
        except Exception:
            self._cimv2 = None  # connect again next time
            return None

    def _nvidia_temp(self):
        """GPU temperature from the NVIDIA driver's own library (nvml.dll), or None."""
        if self._nvml is False:
            return None  # already found there is no NVIDIA driver here
        try:
            if self._nvml is None:
                lib = ctypes.WinDLL("nvml")
                lib.nvmlDeviceGetHandleByIndex_v2.argtypes = (ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))
                lib.nvmlDeviceGetTemperature.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint))
                handle = ctypes.c_void_p()
                if lib.nvmlInit_v2() != 0 or lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                    raise OSError("NVML not usable")
                self._nvml = (lib, handle)
            lib, handle = self._nvml
            temp = ctypes.c_uint()
            if lib.nvmlDeviceGetTemperature(handle, 0, ctypes.byref(temp)) != 0:  # 0 = the GPU sensor
                return None
            return float(temp.value)
        except Exception:
            self._nvml = False
            return None

    def _read_top_apps(self):
        try:
            procs = process_memory()
        except Exception:
            procs = self._process_memory_psutil()
        totals = {}
        for name, mem in procs:
            # psutil calls the memory compression process "MemCompression"
            if name in ("System Idle Process", "Memory Compression", "MemCompression"):
                continue
            t = totals.setdefault(name, [0, 0])
            t[0] += mem
            t[1] += 1
        ranked = sorted(totals.items(), key=lambda kv: kv[1][0], reverse=True)[:3]
        self.top_apps = [(n, v[0], v[1]) for n, v in ranked]

    @staticmethod
    def _process_memory_psutil():
        """Fallback if the fast path fails: slower, and counts shared memory once per process."""
        result = []
        for p in psutil.process_iter(["name", "memory_info"]):
            try:
                result.append((p.info["name"] or "?", p.info["memory_info"].rss))
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                continue
        return result


# ---------------------------------------------------------------- widget
class Widget:
    def __init__(self):
        enable_dpi_awareness()
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.title("PC Monitor")
        self.root.overrideredirect(True)
        self.root.configure(bg=BG)
        self.root.attributes("-alpha", self.cfg["alpha"])
        self.root.attributes("-topmost", self.cfg["topmost"])
        # 1.0 at 100% display scaling, 1.25 at 125%... Fonts scale by themselves, pixel sizes do not.
        self.scale = self.root.winfo_fpixels("1i") / 96
        self.width = self._px(WIDTH)
        self.root.geometry(f"{self.width}x10+{self.cfg['x']}+{self.cfg['y']}")

        self.drive = os.environ.get("SystemDrive", "C:")
        self.slow = SlowData()
        self.last_net = psutil.net_io_counters()
        self.last_net_t = time.time()
        psutil.cpu_percent(None)

        self._drag = (0, 0)
        self._build()
        self._bind_events()
        self._make_menu()
        self.root.update_idletasks()
        height = self.root.winfo_reqheight()
        if not on_screen(self.cfg["x"] + self.width // 2, self.cfg["y"] + height // 2):
            self.cfg["x"], self.cfg["y"] = 40, 40  # saved on a screen that is gone: come back into view
        self.root.geometry(f"{self.width}x{height}+{self.cfg['x']}+{self.cfg['y']}")
        self._tick()

    def _px(self, n):
        """Scale a pixel size to the display's scaling factor."""
        return round(n * self.scale)

    # ---- UI construction
    def _build(self):
        px = self._px
        pad = tk.Frame(self.root, bg=BG)
        pad.pack(fill="both", expand=True, padx=px(12), pady=px(10))

        # header: time + date
        head = tk.Frame(pad, bg=BG)
        head.pack(fill="x")
        self.clock = tk.Label(head, text="", bg=BG, fg=FG, font=("Segoe UI Semibold", 22))
        self.clock.pack(side="left")
        self.date = tk.Label(head, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), justify="right")
        self.date.pack(side="right", pady=(px(8), 0))

        self.cpu_val, self.cpu_bar = self._meter(pad, "CPU")
        self.ram_val, self.ram_bar = self._meter(pad, "RAM")
        self.ram_sub = tk.Label(pad, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self.ram_sub.pack(fill="x")
        self.disk_val, self.disk_bar = self._meter(pad, f"DISK {self.drive}")

        # temperature card
        tcard = tk.Frame(pad, bg=CARD)
        tcard.pack(fill="x", pady=(px(8), 0))
        self.temp_cpu = tk.Label(tcard, text="CPU --", bg=CARD, fg=MUTED, font=("Segoe UI Semibold", 11))
        self.temp_cpu.pack(side="left", padx=px(10), pady=px(6))
        self.temp_gpu = tk.Label(tcard, text="", bg=CARD, fg=MUTED, font=("Segoe UI Semibold", 11))
        self.temp_gpu.pack(side="left", padx=px(4))
        self.temp_note = tk.Label(tcard, text="", bg=CARD, fg=MUTED, font=("Segoe UI", 7))
        self.temp_note.pack(side="right", padx=px(8))

        # top apps
        tk.Label(pad, text="TOP RAM APPS", bg=BG, fg=MUTED, font=("Segoe UI Semibold", 8),
                 anchor="w").pack(fill="x", pady=(px(10), px(2)))
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
        sep = tk.Frame(pad, bg=CARD, height=max(1, px(1)))
        sep.pack(fill="x", pady=px(8))
        self.net_lbl = tk.Label(pad, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w")
        self.net_lbl.pack(fill="x")
        self.bat_lbl = tk.Label(pad, text="", bg=BG, fg=FG, font=("Segoe UI", 9), anchor="w")
        self.bat_lbl.pack(fill="x")
        self.up_lbl = tk.Label(pad, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w")
        self.up_lbl.pack(fill="x")

    def _meter(self, parent, title):
        frame = tk.Frame(parent, bg=BG)
        frame.pack(fill="x", pady=(self._px(8), 0))
        top = tk.Frame(frame, bg=BG)
        top.pack(fill="x")
        tk.Label(top, text=title, bg=BG, fg=MUTED, font=("Segoe UI Semibold", 8)).pack(side="left")
        val = tk.Label(top, text="--", bg=BG, fg=FG, font=("Segoe UI Semibold", 10))
        val.pack(side="right")
        bar = tk.Canvas(frame, height=self._px(6), bg=CARD, highlightthickness=0)
        bar.pack(fill="x", pady=(self._px(2), 0))
        return val, bar

    def _set_bar(self, canvas, pct):
        canvas.update_idletasks()
        w = canvas.winfo_width()
        canvas.delete("all")
        canvas.create_rectangle(0, 0, w * min(pct, 100) / 100, canvas.winfo_height(),
                                fill=pct_color(pct), width=0)

    # ---- interactions
    def _bind_events(self):
        # Bind on the window only. Tk also runs a window's bindings for every widget inside it,
        # so binding each child as well ran every handler twice per click (the menu opened twice).
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)
        self.root.bind("<Button-3>", self._popup)

    def _start_drag(self, e):
        self._drag = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _do_drag(self, e):
        if self.cfg["locked"]:
            return
        self.root.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _end_drag(self, _e):
        pos = (self.root.winfo_x(), self.root.winfo_y())
        if pos != (self.cfg["x"], self.cfg["y"]):  # a plain click does not need a file write
            self.cfg["x"], self.cfg["y"] = pos
            save_config(self.cfg)

    def _make_menu(self):
        self.menu = tk.Menu(self.root, tearoff=0)
        self.menu.add_command(label=f"PC Monitor Widget v{__version__}", state="disabled")
        self.menu.add_separator()
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
        try:
            self._refresh()
        except Exception:
            traceback.print_exc()  # one bad reading must not stop the widget updating for good
        self.root.after(REFRESH_MS, self._tick)

    def _refresh(self):
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
            du = psutil.disk_usage(self.drive + "\\")
            self.disk_val.config(text=f"{du.percent:.0f}%  •  {fmt_bytes(du.free)} free", fg=pct_color(du.percent))
            self._set_bar(self.disk_bar, du.percent)
        except Exception:
            self.disk_val.config(text="n/a")

        # temperatures
        ct, gt = self.slow.cpu_temp, self.slow.gpu_temp
        if ct is not None:
            self.temp_cpu.config(text=f"CPU {ct:.0f}°C", fg=temp_color(ct))
        elif gt is not None:
            self.temp_cpu.config(text="CPU n/a", fg=MUTED)
        else:
            self.temp_cpu.config(text="Temp: N/A", fg=MUTED)
        self.temp_gpu.config(text=f"GPU {gt:.0f}°C" if gt is not None else "", fg=temp_color(gt))
        self.temp_note.config(text=self.slow.temp_source or "start LibreHardwareMonitor")

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
            if not b.power_plugged:
                state = "on battery"
            elif b.percent >= 100:
                state = "plugged in"
            else:
                state = "charging"
            left = ""
            if not b.power_plugged and b.secsleft not in (None, psutil.POWER_TIME_UNLIMITED, psutil.POWER_TIME_UNKNOWN):
                left = f"  •  {fmt_uptime(b.secsleft)} left"
            self.bat_lbl.config(text=f"Battery {b.percent:.0f}% ({state}){left}")
        else:
            self.bat_lbl.config(text="Power: plugged in (no battery)")

        self.up_lbl.config(text=f"Uptime {fmt_uptime(time.time() - psutil.boot_time())}  •  {len(psutil.pids())} processes")

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    if already_running():
        sys.exit(0)
    Widget().run()
