<#
  Phone <-> Laptop Transfer - one-line installer
  Run in PowerShell:
    irm https://raw.githubusercontent.com/merajahmad1150/PhoneLaptopTransfer/main/install.ps1 | iex
#>
$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ================= EDIT THESE =================
$Repo       = "merajahmad1150/PhoneLaptopTransfer"
$Branch     = "main"
$InstallDir = if ($env:PLT_DIR) { $env:PLT_DIR } else { Join-Path $env:USERPROFILE "Tools\PhoneLaptopTransfer" }
# ==============================================

function Has($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path","User")
}
function WingetInstall($id) {
  winget install -e --id $id --silent --accept-package-agreements --accept-source-agreements
}
function Ask($q) { (Read-Host "$q [y/N]") -match '^(y|yes)$' }

Write-Host "`n=== Phone <-> Laptop Transfer Installer ===" -ForegroundColor Cyan
Write-Host "Install folder: $InstallDir`n"

if (-not (Has winget)) {
  Write-Host "winget not found. Install 'App Installer' from the Microsoft Store, then re-run." -ForegroundColor Red
  exit 1
}

# 1. Python (required)
if (-not (Has py)) {
  Write-Host "Installing Python 3.11..." -ForegroundColor Yellow
  WingetInstall "Python.Python.3.11"
  Refresh-Path
}
if (-not (Has py)) {
  Write-Host "Python installed but not visible yet. Close this window, open a new one, and re-run the command." -ForegroundColor Red
  exit 1
}

# 2. Optional tools
if (-not (Has scrcpy) -and (Ask "Install scrcpy (phone screen mirroring)?")) { WingetInstall "Genymobile.scrcpy" }
if (-not (Has adb)    -and (Ask "Install ADB platform-tools (USB file push/pull)?")) { WingetInstall "Google.PlatformTools" }
if (-not (Has syncthing) -and (Ask "Install Syncthing (auto folder sync)?")) { WingetInstall "Syncthing.Syncthing" }
if (-not (Has tailscale) -and (Ask "Install Tailscale (for public access via Funnel)?")) { WingetInstall "Tailscale.Tailscale" }
Refresh-Path

# 3. Download the project zip from GitHub (no Git needed)
Write-Host "`nDownloading app..." -ForegroundColor Yellow
$zip = Join-Path $env:TEMP "plt.zip"
$tmp = Join-Path $env:TEMP "plt_extract"
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/$Branch.zip" -OutFile $zip -UseBasicParsing
Expand-Archive $zip $tmp -Force
$src = (Get-ChildItem $tmp -Directory | Select-Object -First 1).FullName

# 4. Copy files - keeps your venv, settings, logs and transferred files on updates
New-Item -ItemType Directory -Force $InstallDir | Out-Null
robocopy $src $InstallDir /E /XD .venv logs ReceivedFromPhone ShareToPhone __pycache__ /XF config.json | Out-Null
Remove-Item $zip, $tmp -Recurse -Force -ErrorAction SilentlyContinue

# 5. Virtual environment + packages (.venv, same as Start.bat expects)
$py = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Creating virtual environment..." -ForegroundColor Yellow
  py -3.11 -m venv (Join-Path $InstallDir ".venv")
}
& $py -m pip install --upgrade pip --quiet
& $py -m pip install -r (Join-Path $InstallDir "requirements.txt")

# 6. Shortcuts (Desktop + Start Menu) - launches without a console window
$shell   = New-Object -ComObject WScript.Shell
$targets = @(
  [Environment]::GetFolderPath("Desktop"),
  (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs")
)
foreach ($dir in $targets) {
  $lnk = $shell.CreateShortcut((Join-Path $dir "Phone Laptop Transfer.lnk"))
  $lnk.TargetPath       = Join-Path $InstallDir ".venv\Scripts\pythonw.exe"
  $lnk.Arguments        = "`"$(Join-Path $InstallDir 'core\run.py')`""
  $lnk.WorkingDirectory = $InstallDir
  $lnk.Save()
}

Write-Host "`nDone! Use the 'Phone Laptop Transfer' shortcut on your Desktop." -ForegroundColor Green
Write-Host "Console mode (shows errors): $InstallDir\Start.bat"
Write-Host "On first 'Start Server', click Allow in the Windows Firewall prompt."
