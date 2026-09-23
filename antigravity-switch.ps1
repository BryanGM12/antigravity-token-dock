# Antigravity Account Switcher - Instant Execution Convenience Shortcut
[CmdletBinding()]
param()

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& "$ScriptDir\antigravity-monitor.ps1" switch
