# Antigravity Account Daemon, Docked Widget & Auto-Activator Controller
[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "status", "restart", "activator", "widget", "hud", "analytics", "health", "notify-test", "add", "list", "remove")]
    [string]$Action = "status"
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = "$env:USERPROFILE\.openclaw\workspace\state\antigravity_controller"
$PidFile = "$StateDir\daemon.pid"
$WidgetPidFile = "$StateDir\widget.pid"
$ActivatorPidFile = "$StateDir\activator.pid"
$LogFile = "$StateDir\controller.log"

if (-not (Test-Path $StateDir)) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
}

function Get-DaemonProcess {
    if (Test-Path $PidFile) {
        $savedPid = Get-Content $PidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -match "python") {
                return $proc
            }
        }
    }
    $procs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like "*daemon_service.py*" -and $_.CommandLine -like "*--daemon*" }
    if ($procs -and $procs.Count -gt 0) {
        return (Get-Process -Id $procs[0].ProcessId -ErrorAction SilentlyContinue)
    }
    if ($procs -and $procs.ProcessId) {
        return (Get-Process -Id $procs.ProcessId -ErrorAction SilentlyContinue)
    }
    return $null
}

function Get-WidgetProcess {
    if (Test-Path $WidgetPidFile) {
        $savedPid = Get-Content $WidgetPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -match "python") {
                return $proc
            }
        }
    }
    $procs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like "*antigravity_docked_overlay.py*" }
    if ($procs -and $procs.Count -gt 0) {
        return (Get-Process -Id $procs[0].ProcessId -ErrorAction SilentlyContinue)
    }
    if ($procs -and $procs.ProcessId) {
        return (Get-Process -Id $procs.ProcessId -ErrorAction SilentlyContinue)
    }
    return $null
}

function Get-ActivatorProcess {
    if (Test-Path $ActivatorPidFile) {
        $savedPid = Get-Content $ActivatorPidFile -ErrorAction SilentlyContinue
        if ($savedPid) {
            $proc = Get-Process -Id ([int]$savedPid) -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -match "python") {
                return $proc
            }
        }
    }
    $procs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like "*antigravity_auto_activator.py*" }
    if ($procs -and $procs.Count -gt 0) {
        return (Get-Process -Id $procs[0].ProcessId -ErrorAction SilentlyContinue)
    }
    if ($procs -and $procs.ProcessId) {
        return (Get-Process -Id $procs.ProcessId -ErrorAction SilentlyContinue)
    }
    return $null
}

function Test-AntigravityRunning {
    $ag = Get-Process -Name "Antigravity" -ErrorAction SilentlyContinue
    return ($ag -ne $null)
}

switch ($Action.ToLower()) {
    "start" {
        Write-Host "=====================================================" -ForegroundColor Cyan
        Write-Host "   ✦ INICIANDO SISTEMA DE CONTROL DE ANTIGRAVITY ✦   " -ForegroundColor Cyan
        Write-Host "=====================================================" -ForegroundColor Cyan

        # 1. Start Auto-Activator
        $actProc = Get-ActivatorProcess
        if ($actProc) {
            Write-Host "[!] Auto-Activador ya activo (PID: $($actProc.Id))." -ForegroundColor Yellow
        } else {
            Write-Host "[+] Iniciando Auto-Activador en segundo plano..." -ForegroundColor Cyan
            $actP = Start-Process -FilePath "pythonw.exe" `
                -ArgumentList @("$ScriptDir\antigravity_auto_activator.py", "--daemon") `
                -WorkingDirectory $ScriptDir `
                -WindowStyle Hidden `
                -PassThru
            if ($actP) {
                $actP.Id | Out-File -FilePath $ActivatorPidFile -Force -Encoding ascii
                Write-Host "[OK] Auto-Activador iniciado (PID: $($actP.Id))." -ForegroundColor Green
            }
        }

        # 2. Start Daemon
        $existing = Get-DaemonProcess
        if ($existing) {
            Write-Host "[!] Daemon ya activo (PID: $($existing.Id))." -ForegroundColor Yellow
        } else {
            Write-Host "[+] Iniciando Daemon en segundo plano..." -ForegroundColor Cyan
            $argsList = @("$ScriptDir\daemon_service.py", "--daemon")
            $proc = Start-Process -FilePath "pythonw.exe" `
                -ArgumentList $argsList `
                -WorkingDirectory $ScriptDir `
                -WindowStyle Hidden `
                -PassThru
            if ($proc) {
                $proc.Id | Out-File -FilePath $PidFile -Force -Encoding ascii
                Start-Sleep -Seconds 1
                Write-Host "[OK] Daemon iniciado exitosamente (PID: $($proc.Id))." -ForegroundColor Green
            }
        }

        # 3. Start Docked Widget
        $wProc = Get-WidgetProcess
        if ($wProc) {
            Write-Host "[!] Widget acoplado ya activo (PID: $($wProc.Id))." -ForegroundColor Yellow
        } else {
            Write-Host "[+] Iniciando Widget acoplado nativo a Antigravity..." -ForegroundColor Cyan
            $newW = Start-Process -FilePath "pythonw.exe" `
                -ArgumentList @("$ScriptDir\antigravity_docked_overlay.py") `
                -WorkingDirectory $ScriptDir `
                -WindowStyle Hidden `
                -PassThru
            if ($newW) {
                $newW.Id | Out-File -FilePath $WidgetPidFile -Force -Encoding ascii
                Write-Host "[OK] Widget acoplado iniciado exitosamente (PID: $($newW.Id))." -ForegroundColor Green
            }
        }
    }

    "activator" {
        & python.exe "$ScriptDir\antigravity_auto_activator.py" --status
    }

    "widget" {
        $wProc = Get-WidgetProcess
        if ($wProc) {
            Write-Host "[!] El widget acoplado ya esta activo (PID: $($wProc.Id))." -ForegroundColor Yellow
            return
        }
        Write-Host "[+] Iniciando widget acoplado nativo a Antigravity..." -ForegroundColor Cyan
        $newW = Start-Process -FilePath "pythonw.exe" `
            -ArgumentList @("$ScriptDir\antigravity_docked_overlay.py") `
            -WorkingDirectory $ScriptDir `
            -WindowStyle Hidden `
            -PassThru
        if ($newW) {
            $newW.Id | Out-File -FilePath $WidgetPidFile -Force -Encoding ascii
            Write-Host "[OK] Widget acoplado iniciado exitosamente (PID: $($newW.Id))." -ForegroundColor Green
        }
    }

    "stop" {
        $allProcs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { 
            $_.CommandLine -like "*daemon_service.py*" -or $_.CommandLine -like "*antigravity_docked_overlay.py*" -or $_.CommandLine -like "*antigravity_auto_activator.py*"
        }
        if ($allProcs) {
            foreach ($dp in $allProcs) {
                Write-Host "[-] Deteniendo proceso (PID: $($dp.ProcessId))..." -ForegroundColor Yellow
                Stop-Process -Id $dp.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $WidgetPidFile) { Remove-Item $WidgetPidFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $ActivatorPidFile) { Remove-Item $ActivatorPidFile -Force -ErrorAction SilentlyContinue }
        Write-Host "[OK] Todos los servicios, activador y widget han sido detenidos." -ForegroundColor Green
    }

    "status" {
        $proc = Get-DaemonProcess
        $wProc = Get-WidgetProcess
        $actProc = Get-ActivatorProcess
        $agRunning = Test-AntigravityRunning

        Write-Host "=====================================================" -ForegroundColor Cyan
        Write-Host "   ✦ ESTADO DEL MONITOR AUTO-SWITCH & ACTIVADOR ✦    " -ForegroundColor Cyan
        Write-Host "=====================================================" -ForegroundColor Cyan
        if ($agRunning) {
            Write-Host " Antigravity IDE: [● ACTIVO] (Ventana en ejecucion)" -ForegroundColor Green
        } else {
            Write-Host " Antigravity IDE: [✕ INACTIVO] (Cerrado)" -ForegroundColor Gray
        }

        if ($actProc) {
            Write-Host " Auto-Activador:  [● ACTIVO] (Supervisando ciclo de vida, PID: $($actProc.Id))" -ForegroundColor Green
        } else {
            Write-Host " Auto-Activador:  [✕ INACTIVO]" -ForegroundColor Gray
        }

        if ($proc) {
            Write-Host " Daemon Rotador:  [● ACTIVO] (PID: $($proc.Id))" -ForegroundColor Green
        } else {
            Write-Host " Daemon Rotador:  [✕ INACTIVO]" -ForegroundColor Gray
        }

        if ($wProc) {
            Write-Host " Widget Acoplado: [● ACTIVO] (Acoplado a ventana, PID: $($wProc.Id))" -ForegroundColor Green
        } else {
            Write-Host " Widget Acoplado: [✕ INACTIVO]" -ForegroundColor Gray
        }

        Write-Host " Log Principal:   $LogFile" -ForegroundColor DarkGray
        Write-Host " HUD Web:         http://127.0.0.1:59123" -ForegroundColor Cyan
        Write-Host "-----------------------------------------------------"
        & python.exe "$ScriptDir\daemon_service.py" --status
    }

    "restart" {
        # Stop all
        $allProcs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { 
            $_.CommandLine -like "*daemon_service.py*" -or $_.CommandLine -like "*antigravity_docked_overlay.py*" -or $_.CommandLine -like "*antigravity_auto_activator.py*"
        }
        if ($allProcs) {
            foreach ($dp in $allProcs) {
                Stop-Process -Id $dp.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $WidgetPidFile) { Remove-Item $WidgetPidFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $ActivatorPidFile) { Remove-Item $ActivatorPidFile -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1

        # Start activator
        $actP = Start-Process -FilePath "pythonw.exe" `
            -ArgumentList @("$ScriptDir\antigravity_auto_activator.py", "--daemon") `
            -WorkingDirectory $ScriptDir `
            -WindowStyle Hidden `
            -PassThru
        if ($actP) { $actP.Id | Out-File -FilePath $ActivatorPidFile -Force -Encoding ascii }

        # Start daemon
        $proc = Start-Process -FilePath "pythonw.exe" `
            -ArgumentList @("$ScriptDir\daemon_service.py", "--daemon") `
            -WorkingDirectory $ScriptDir `
            -WindowStyle Hidden `
            -PassThru
        if ($proc) { $proc.Id | Out-File -FilePath $PidFile -Force -Encoding ascii }

        # Start widget
        $newW = Start-Process -FilePath "pythonw.exe" `
            -ArgumentList @("$ScriptDir\antigravity_docked_overlay.py") `
            -WorkingDirectory $ScriptDir `
            -WindowStyle Hidden `
            -PassThru
        if ($newW) { $newW.Id | Out-File -FilePath $WidgetPidFile -Force -Encoding ascii }

        Write-Host "[OK] Auto-Activador, Daemon y Widget reiniciados exitosamente." -ForegroundColor Green
    }

    "hud" {
        Start-Process "http://127.0.0.1:59123"
    }

    "analytics" {
        & python.exe "$ScriptDir\analytics_engine.py"
    }

    "health" {
        & python.exe "$ScriptDir\watchdog_service.py"
    }

    "notify-test" {
        & python.exe "$ScriptDir\notification_service.py"
    }

    "add" {
        $extraArgs = $args
        if ($extraArgs.Count -ge 1) {
            $email = $extraArgs[0]
            $name = if ($extraArgs.Count -ge 2) { $extraArgs[1] } else { $email.Split('@')[0] }
            $tier = if ($extraArgs.Count -ge 3) { $extraArgs[2] } else { "✦ Pro" }
            & python.exe "$ScriptDir\config_manager.py" --add $email --name $name --tier $tier
        } else {
            & python.exe "$ScriptDir\config_manager.py" --interactive
        }
    }

    "list" {
        & python.exe "$ScriptDir\config_manager.py" --list
    }

    "remove" {
        if ($args.Count -ge 1) {
            $email = $args[0]
            & python.exe "$ScriptDir\config_manager.py" --remove $email
        } else {
            Write-Host "Uso: .\antigravity-monitor.ps1 remove <email>" -ForegroundColor Yellow
        }
    }
}
