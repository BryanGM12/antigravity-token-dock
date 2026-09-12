# Antigravity Account Switcher - Instant Execution
[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = "python.exe"

Write-Host "=====================================================" -ForegroundColor Cyan
Write-Host "     ROTADOR DE CUENTAS DE ANTIGRAVITY (INSTANT)     " -ForegroundColor Cyan
Write-Host "=====================================================" -ForegroundColor Cyan

& $PythonExe "$ScriptDir\daemon_service.py" --switch-now

Write-Host "`nOperacion finalizada." -ForegroundColor Green
