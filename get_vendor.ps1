# Downloads the two helper programs that get bundled inside PCMonitorWidget.exe:
#   - LibreHardwareMonitor (reads the sensors)
#   - PawnIO driver installer (lets it read CPU sensors)
# Result: ./vendor/LibreHardwareMonitor/*  and  ./vendor/PawnIO_setup.exe
# Needs the GitHub CLI ("gh"), which is preinstalled on GitHub Actions Windows runners.
# On your own PC: install it from https://cli.github.com and run "gh auth login" once.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Remove-Item -Recurse -Force vendor, _dl -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force vendor, _dl | Out-Null

# ---- LibreHardwareMonitor
$repo = "LibreHardwareMonitor/LibreHardwareMonitor"
$names = @(gh release view --repo $repo --json assets --jq ".assets[].name")
Write-Host "LibreHardwareMonitor assets: $($names -join ', ')"
$zips = @($names | Where-Object { $_ -match "\.zip$" })
# Prefer the classic .NET Framework build: it runs on Windows 10 with nothing extra to install.
$pick = $zips | Where-Object { $_ -eq "LibreHardwareMonitor.zip" } | Select-Object -First 1
if (-not $pick) { $pick = $zips | Where-Object { $_ -match "net4" } | Select-Object -First 1 }
if (-not $pick) { $pick = $zips | Select-Object -First 1 }
if (-not $pick) { throw "No zip asset found in the LibreHardwareMonitor release." }
Write-Host "Using: $pick"
gh release download --repo $repo --pattern $pick --dir _dl --clobber
Expand-Archive -Path (Join-Path _dl $pick) -DestinationPath _dl\lhm -Force

# Some zips contain a single top-level folder: find the folder that holds the exe.
$exe = Get-ChildItem -Path _dl\lhm -Recurse -Filter LibreHardwareMonitor.exe | Select-Object -First 1
if (-not $exe) { throw "LibreHardwareMonitor.exe not found inside $pick" }
Copy-Item -Recurse -Force "$($exe.DirectoryName)" vendor\LibreHardwareMonitor

# ---- PawnIO driver installer
gh release download --repo namazso/PawnIO.Setup --pattern "PawnIO_setup.exe" --dir vendor --clobber
if (-not (Test-Path vendor\PawnIO_setup.exe)) { throw "PawnIO_setup.exe was not downloaded." }

Remove-Item -Recurse -Force _dl
Write-Host "Vendor files ready:"
Get-ChildItem vendor -Recurse | Select-Object -First 20 FullName
