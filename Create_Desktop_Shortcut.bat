@echo off
REM Creates a Desktop shortcut (with the tool logo) that runs Start.bat
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath(Desktop)+\Phone-Laptop Transfer.lnk); $s.TargetPath=%~dp0Start.bat; $s.WorkingDirectory=%~dp0; $s.IconLocation=%~dp0assets\logo.ico; $s.Description=Phone-Laptop Transfer; $s.Save()"
if errorlevel 1 ( echo Could not create the shortcut. ) else ( echo Shortcut "Phone-Laptop Transfer" created on your Desktop. )
pause
