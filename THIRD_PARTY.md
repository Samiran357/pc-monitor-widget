# Third-party software

The released `PCMonitorWidget.exe` bundles the following programs. They are downloaded from their official GitHub releases at build time and are not modified.

| Component | Purpose | Source | License |
| --- | --- | --- | --- |
| LibreHardwareMonitor | Reads hardware sensors (temperatures) | https://github.com/LibreHardwareMonitor/LibreHardwareMonitor | Mozilla Public License 2.0 |
| PawnIO driver installer | Kernel driver used by LibreHardwareMonitor for CPU sensors | https://github.com/namazso/PawnIO.Setup | See the PawnIO repository |
| psutil | CPU, RAM, disk, network, process info | https://github.com/giampaolo/psutil | BSD 3-Clause |
| WMI, pywin32 | Reads sensor data from Windows | https://pypi.org/project/WMI/ , https://github.com/mhammond/pywin32 | MIT, PSF |

Please check each project's own license before redistributing the exe.
