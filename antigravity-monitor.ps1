# Antigravity Account Daemon & Docked Widget Controller
[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "status", "restart", "widget", "hud", "analytics", "health", "notify-test", "add", "list", "remove")]
    [string]$Action = "status"
)

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = "$env:USERPROFILE\.openclaw\workspace\state\antigravity_controller"
$PidFile = "$StateDir\daemon.pid"
$WidgetPidFile = "$StateDir\widget.pid"
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

switch ($Action.ToLower()) {
    "start" {
        $existing = Get-DaemonProcess
        if ($existing) {
            Write-Host "[!] El daemon ya esta activo (PID: $($existing.Id))." -ForegroundColor Yellow
        } else {
            Write-Host "[+] Iniciando daemon en segundo plano..." -ForegroundColor Cyan
            $argsList = @("$ScriptDir\daemon_service.py", "--daemon")
            $proc = Start-Process -FilePath "pythonw.exe" `
                -ArgumentList $argsList `
                -WorkingDirectory $ScriptDir `
                -PassThru
            if ($proc) {
                $proc.Id | Out-File -FilePath $PidFile -Force -Encoding ascii
                Start-Sleep -Seconds 1
                Write-Host "[OK] Daemon de Antigravity iniciado (PID: $($proc.Id))." -ForegroundColor Green
            }
        }

        # Also start docked widget
        $wProc = Get-WidgetProcess
        if ($wProc) {
            Write-Host "[!] El widget acoplado ya esta activo (PID: $($wProc.Id))." -ForegroundColor Yellow
        } else {
            Write-Host "[+] Iniciando widget acoplado nativo a Antigravity..." -ForegroundColor Cyan
            $newW = Start-Process -FilePath "pythonw.exe" `
                -ArgumentList @("$ScriptDir\antigravity_docked_overlay.py") `
                -WorkingDirectory $ScriptDir `
                -PassThru
            if ($newW) {
                $newW.Id | Out-File -FilePath $WidgetPidFile -Force -Encoding ascii
                Write-Host "[OK] Widget acoplado iniciado exitosamente (PID: $($newW.Id))." -ForegroundColor Green
            }
        }
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
            -PassThru
        if ($newW) {
            $newW.Id | Out-File -FilePath $WidgetPidFile -Force -Encoding ascii
            Write-Host "[OK] Widget acoplado iniciado exitosamente (PID: $($newW.Id))." -ForegroundColor Green
        }
    }

    "stop" {
        $allProcs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { 
            $_.CommandLine -like "*daemon_service.py*" -or $_.CommandLine -like "*antigravity_docked_overlay.py*" 
        }
        if ($allProcs) {
            foreach ($dp in $allProcs) {
                Write-Host "[*] Deteniendo proceso (PID: $($dp.ProcessId))..." -ForegroundColor Yellow
                Stop-Process -Id $dp.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $WidgetPidFile) { Remove-Item $WidgetPidFile -Force -ErrorAction SilentlyContinue }
        Write-Host "[OK] Todos los servicios y widgets de Antigravity detenidos." -ForegroundColor Green
    }

    "status" {
        $proc = Get-DaemonProcess
        $wProc = Get-WidgetProcess
        Write-Host "=====================================================" -ForegroundColor Cyan
        Write-Host "     ESTADO DEL MONITOR AUTO-SWITCH & WIDGET         " -ForegroundColor Cyan
        Write-Host "=====================================================" -ForegroundColor Cyan
        if ($proc) {
            Write-Host " Daemon: ACTIVO (PID: $($proc.Id))" -ForegroundColor Green
        } else {
            Write-Host " Daemon: INACTIVO (Detenido)" -ForegroundColor Gray
        }
        if ($wProc) {
            Write-Host " Widget: ACTIVO (Acoplado a ventana Antigravity, PID: $($wProc.Id))" -ForegroundColor Green
        } else {
            Write-Host " Widget: INACTIVO (Detenido)" -ForegroundColor Gray
        }
        Write-Host " Log:    $LogFile" -ForegroundColor DarkGray
        Write-Host " HUD:    http://127.0.0.1:59123" -ForegroundColor Cyan
        Write-Host "-----------------------------------------------------"
        & python.exe "$ScriptDir\daemon_service.py" --status
    }

    "restart" {
        # Stop both
        $allProcs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { 
            $_.CommandLine -like "*daemon_service.py*" -or $_.CommandLine -like "*antigravity_docked_overlay.py*" 
        }
        if ($allProcs) {
            foreach ($dp in $allProcs) {
                Stop-Process -Id $dp.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }
        if (Test-Path $PidFile) { Remove-Item $PidFile -Force -ErrorAction SilentlyContinue }
        if (Test-Path $WidgetPidFile) { Remove-Item $WidgetPidFile -Force -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1

        # Start both
        $proc = Start-Process -FilePath "pythonw.exe" `
            -ArgumentList @("$ScriptDir\daemon_service.py", "--daemon") `
            -WorkingDirectory $ScriptDir `
            -PassThru
        if ($proc) { $proc.Id | Out-File -FilePath $PidFile -Force -Encoding ascii }

        $newW = Start-Process -FilePath "pythonw.exe" `
            -ArgumentList @("$ScriptDir\antigravity_docked_overlay.py") `
            -WorkingDirectory $ScriptDir `
            -PassThru
        if ($newW) { $newW.Id | Out-File -FilePath $WidgetPidFile -Force -Encoding ascii }

        Write-Host "[OK] Daemon (PID: $($proc.Id)) y Widget (PID: $($newW.Id)) reiniciados exitosamente." -ForegroundColor Green
    }

    "hud" {
        Write-Host "[*] Abriendo Antigravity Live HUD en navegador..." -ForegroundColor Cyan
        Start-Process "http://127.0.0.1:59123"
        Write-Host "[OK] Panel abierto en http://127.0.0.1:59123" -ForegroundColor Green
    }

    "analytics" {
        & python.exe "$ScriptDir\daemon_service.py" --analytics
    }

    "health" {
        Write-Host "[*] Ejecutando auditoria de salud del Watchdog..." -ForegroundColor Cyan
        & python.exe "$ScriptDir\daemon_service.py" --health
    }

    "notify-test" {
        Write-Host "[*] Enviando notificacion Toast de prueba a Windows..." -ForegroundColor Cyan
        & python.exe "$ScriptDir\daemon_service.py" --notify-test
    }

    "add" {
        $email = $args[0]
        $name = $args[1]
        $tier = $args[2]
        if (-not $email) {
            & python.exe "$ScriptDir\config_manager.py" --interactive
        } else {
            $cmdArgs = @("$ScriptDir\config_manager.py", "--add", $email)
            if ($name) { $cmdArgs += @("--name", $name) }
            if ($tier) { $cmdArgs += @("--tier", $tier) }
            & python.exe @cmdArgs
        }
    }

    "list" {
        & python.exe "$ScriptDir\config_manager.py" --list
    }

    "remove" {
        $email = $args[0]
        if (-not $email) {
            Write-Host "[!] Especifica el correo a eliminar: .\antigravity-monitor.ps1 remove usuario@gmail.com" -ForegroundColor Yellow
        } else {
            & python.exe "$ScriptDir\config_manager.py" --remove $email
        }
    }
}

