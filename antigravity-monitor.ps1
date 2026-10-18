# Antigravity Native Titlebar Menu & Token Quota Supervisor
[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [ValidateSet("status", "start", "stop", "restart", "switch", "inject")]
    [string]$Action = "status",
    [Parameter(Position=1)]
    [string]$Target = "",
    [switch]$Force
)

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServerScript = Join-Path $ScriptDir "menu_cuentas.py"
$InjectorScript = Join-Path $ScriptDir "antigravity_auto_injector.py"

function Get-ServerProcess {
    $procs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like "*menu_cuentas.py*" -and $_.CommandLine -like "*59123*" }
    if ($procs -and $procs.Count -gt 0) {
        return (Get-Process -Id $procs[0].ProcessId -ErrorAction SilentlyContinue)
    }
    if ($procs -and $procs.ProcessId) {
        return (Get-Process -Id $procs.ProcessId -ErrorAction SilentlyContinue)
    }
    return $null
}

function Get-InjectorProcess {
    $procs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Where-Object { $_.CommandLine -like "*antigravity_auto_injector.py*" }
    if ($procs -and $procs.Count -gt 0) {
        return (Get-Process -Id $procs[0].ProcessId -ErrorAction SilentlyContinue)
    }
    if ($procs -and $procs.ProcessId) {
        return (Get-Process -Id $procs.ProcessId -ErrorAction SilentlyContinue)
    }
    return $null
}

switch ($Action.ToLower()) {
    "status" {
        Write-Host "==========================================================================" -ForegroundColor Cyan
        Write-Host "       ANTIGRAVITY NATIVE TITLEBAR MENU & TOKEN QUOTA SYSTEM              " -ForegroundColor Cyan
        Write-Host "==========================================================================" -ForegroundColor Cyan

        $srv = Get-ServerProcess
        if ($srv) {
            Write-Host "[ACTIVO]  Servidor Local API / HUD en puerto 59123 (PID: $($srv.Id))" -ForegroundColor Green
        } else {
            Write-Host "[INACTIVO] Servidor Local API en puerto 59123" -ForegroundColor Red
        }

        $inj = Get-InjectorProcess
        if ($inj) {
            Write-Host "[ACTIVO]  Auto-Inyector continuo CDP en puerto 59124 (PID: $($inj.Id))" -ForegroundColor Green
        } else {
            Write-Host "[INACTIVO] Auto-Inyector continuo CDP" -ForegroundColor Red
        }

        Write-Host "`nConsultando estado y cuotas de las 7 cuentas Google AI Pro:`n" -ForegroundColor DarkGray
        python $ServerScript
    }

    "start" {
        Write-Host "Iniciando servicios del nuevo sistema nativo Antigravity..." -ForegroundColor Cyan

        $srv = Get-ServerProcess
        if (-not $srv) {
            Start-Process -FilePath "pythonw.exe" -ArgumentList "`"$ServerScript`" --serve 59123"
            Start-Sleep -Milliseconds 600
            $srv = Get-ServerProcess
            if ($srv) {
                Write-Host "[OK] Servidor API iniciado en puerto 59123 (PID: $($srv.Id))." -ForegroundColor Green
            } else {
                Write-Host "[AVISO] Iniciando servidor en segundo plano..." -ForegroundColor Yellow
            }
        } else {
            Write-Host "[INFO] Servidor API ya esta corriendo (PID: $($srv.Id))." -ForegroundColor Gray
        }

        $inj = Get-InjectorProcess
        if (-not $inj) {
            Start-Process -FilePath "pythonw.exe" -ArgumentList "`"$InjectorScript`""
            Start-Sleep -Milliseconds 600
            $inj = Get-InjectorProcess
            if ($inj) {
                Write-Host "[OK] Auto-inyector iniciado en segundo plano (PID: $($inj.Id))." -ForegroundColor Green
            } else {
                Write-Host "[AVISO] Iniciando auto-inyector en segundo plano..." -ForegroundColor Yellow
            }
        } else {
            Write-Host "[INFO] Auto-inyector ya esta corriendo (PID: $($inj.Id))." -ForegroundColor Gray
        }
    }

    "stop" {
        Write-Host "Deteniendo servicios de Antigravity Token Dock..." -ForegroundColor Yellow

        $srv = Get-ServerProcess
        if ($srv) {
            Stop-Process -Id $srv.Id -Force -ErrorAction SilentlyContinue
            Write-Host "[DETENIDO] Servidor API (PID: $($srv.Id)) detenido." -ForegroundColor Green
        } else {
            Write-Host "[INFO] Servidor API no estaba corriendo." -ForegroundColor Gray
        }

        $inj = Get-InjectorProcess
        if ($inj) {
            Stop-Process -Id $inj.Id -Force -ErrorAction SilentlyContinue
            Write-Host "[DETENIDO] Auto-inyector (PID: $($inj.Id)) detenido." -ForegroundColor Green
        } else {
            Write-Host "[INFO] Auto-inyector no estaba corriendo." -ForegroundColor Gray
        }
    }

    "restart" {
        Write-Host "Reiniciando servicios..." -ForegroundColor Cyan
        & $PSCommandPath stop
        Start-Sleep -Seconds 1
        & $PSCommandPath start
    }

    "switch" {
        if (-not $Target) {
            Write-Host "Uso: .\antigravity-monitor.ps1 switch <1-7 | alias | email>" -ForegroundColor Yellow
            exit 1
        }
        Write-Host "Ejecutando cambio de cuenta a: $Target..." -ForegroundColor Cyan
        python $ServerScript $Target
    }

    "inject" {
        Write-Host "Forzando inyeccion inmediata del menu en Antigravity..." -ForegroundColor Cyan
        python $InjectorScript
    }
}
