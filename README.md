# PC Monitor Widget

A small, always-visible desktop widget for Windows 10/11 that shows live system stats: CPU, RAM, temperature, the apps using the most memory, and more. It is draggable, semi-transparent, and uses very little CPU itself.

<!-- Add a screenshot here after you upload it to the repo:
![Screenshot](docs/screenshot.png)
-->

## Features

- Clock and date
- CPU usage and RAM usage, with colour bars (green, yellow, red) and used/free memory
- CPU and GPU temperature
- Top 3 apps by RAM (all processes of one app are added together, e.g. `chrome x24`)
- Disk usage of the system drive
- Live download and upload speed
- Battery level and time left (or "plugged in" on desktops)
- Uptime and process count
- Right-click menu: always on top, lock position, opacity, start with Windows, open Task Manager, close
- Remembers its position and settings
- Only one copy can run at a time

## Quick start (one file, nothing else to install)

1. Go to the **Releases** page of this repository.
2. Download `PCMonitorWidget.exe`.
3. Double-click it and click **Yes** on the Windows permission prompt (see [Why administrator?](#why-administrator)).
4. The widget appears. On first run it sets up the temperature sensors by itself, which takes a few seconds, so "Temp" may say `waiting for sensors...` briefly.
5. Right-click the widget and tick **Start with Windows** if you want it to open automatically at sign-in (no permission prompt after that).

That's it. Python, LibreHardwareMonitor and the sensor driver are all included inside the exe.

### Why administrator?

Windows only lets programs with administrator rights read hardware temperatures. The widget asks once when it opens. If you click **No**, it still works but shows `Temp: N/A`.

> **Windows SmartScreen or antivirus warning?** Programs built with PyInstaller are sometimes flagged because they are new and unsigned. The full source is in this repository, and you can build the exe yourself (see [Build the exe yourself](#build-the-exe-yourself)) if you prefer.

## How temperature works

The exe bundles two free, open-source helpers and manages them for you:

- **LibreHardwareMonitor** reads the sensors. The widget starts it hidden in the tray and closes it when you close the widget.
- **PawnIO** is a small driver that lets it read CPU sensors. It is installed silently the first time you run the widget (it needs the administrator permission you already gave).

Nothing to download or start by hand. If you ever see `Temp: N/A`:

- Check the small note next to it: `waiting for sensors...` just means give it a few seconds; `run as administrator` means the permission prompt was declined (close and reopen the widget, click Yes).
- A few PCs (some laptops, virtual machines) simply don't expose a temperature sensor. Everything else in the widget still works.
- Some antivirus programs dislike hardware-monitoring drivers. If yours blocks it, allow the widget in your antivirus.

## Controls

| Action | How |
| --- | --- |
| Move the widget | Drag with the left mouse button |
| Menu | Right-click anywhere on the widget |
| Always on top | Menu, Always on top |
| Prevent accidental moving | Menu, Lock position |
| Change transparency | Menu, Opacity |
| Start with Windows | Menu, Start with Windows |
| Close | Menu, Close widget |

Settings are saved to `.pc_widget.json` in your user folder (`C:\Users\<you>\`). Delete that file to reset them.

## Run from source

Requires Windows and Python 3.9 or newer. Running from source does not include the sensor helpers: open PowerShell in the project folder and run `./get_vendor.ps1` once (needs the [GitHub CLI](https://cli.github.com), signed in with `gh auth login`). It fills a `vendor` folder that the widget picks up automatically. Skip this step if you only want CPU/RAM/disk/network and don't need temperature.

1. Install Python from python.org. On the first installer screen, tick **Add Python to PATH**.
2. Download or clone this repository.
3. Open **Command Prompt** in the project folder (in File Explorer, click the address bar, type `cmd`, press Enter).
4. Install the packages and run:

   ```
   pip install -r requirements.txt
   python pc_widget.py
   ```

   If `pip` or `python` is not recognized, use `py -m pip install -r requirements.txt` and `py pc_widget.py`.

Do not type these commands inside the Python prompt (the one that shows `>>>`). Type `exit()` first if you are in it.

### Run without a terminal window

- Double-click `start_widget.vbs`. It starts the widget in the background with no console window. Keep it in the same folder as `pc_widget.py`.
- Or run `pythonw pc_widget.py` from Command Prompt.

## Troubleshooting

**Temp: N/A** — See [How temperature works](#how-temperature-works). Most often: click Yes on the permission prompt and wait a few seconds after the first start.

**GitHub build fails at "Download sensor helpers"** — The release file names of LibreHardwareMonitor or PawnIO may have changed. Open the failed step's log: it prints the available file names. Adjust the names in `get_vendor.ps1`.

**Nothing happens when I run it** — Run `python pc_widget.py` from Command Prompt (not `pythonw`) to see any error message.

**`pip` is not recognized** — Use `py -m pip ...`, or add Python to PATH by rerunning the Python installer, choosing Modify, and ticking "Add Python to environment variables".

**Error installing `pywin32` or `wmi`** — These are only needed for temperature. The widget still runs without them, so you can remove them from `requirements.txt` if installation fails. Very new Python versions sometimes lag behind on package support; Python 3.12 is a safe choice.

**The widget is hidden behind other windows** — Right-click it and tick Always on top.

**It did not start with Windows** — Right-click the widget and make sure Start with Windows is ticked. If you moved the exe or script afterwards, untick and tick it again so the new location is saved.

**How do I stop it from starting with Windows?** — Right-click the widget and untick Start with Windows. You can also check Task Manager, Startup tab.

**It shows only one monitor's worth of position after I unplug a screen** — Delete `.pc_widget.json` in your user folder to reset its position.

## Project layout

```
pc-monitor-widget/
├── pc_widget.py              The widget
├── requirements.txt          Python packages
├── start_widget.vbs          Launcher with no console window
├── build.bat                 Builds the exe locally
├── get_vendor.ps1            Downloads LibreHardwareMonitor + PawnIO for bundling
├── THIRD_PARTY.md            Licenses of the bundled helpers
├── .github/workflows/build.yml   Builds and releases the exe on GitHub
├── LICENSE
└── README.md
```

## Contributing

Issues and pull requests are welcome. Ideas: GPU usage, per-core CPU bars, a settings window, a light theme, a tray icon.

## License

MIT. See [LICENSE](LICENSE).
