# Antigravity Supervisor: Automatic Lifecycle Watcher
# Automatically starts the account rotation daemon when Antigravity starts,
# and stops it when Antigravity closes.

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$StateDir = "$env:USERPROFILE\.openclaw\workspace\state\antigravity_controller"
$LogFile = "$StateDir\supervisor.log"

if (-not (Test-Path $StateDir)) {
    New-Item -ItemType Directory -Path $StateDir -Force | Out-Null
}

function Log-Message([string]$msg) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "[$timestamp] $msg" | Out-File -FilePath $LogFile -Append -Encoding utf8
}

Log-Message "Antigravity Supervisor iniciado."

$daemonScript = "$ScriptDir\daemon_service.py"

while ($true) {
    try {
        $agRunning = (Get-Process -Name "Antigravity" -ErrorAction SilentlyContinue) -ne $null
        $daemonRunning = $false

        $pyProcs = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue
        foreach ($p in $pyProcs) {
            if ($p.CommandLine -like "*daemon_service.py*" -and $p.CommandLine -like "*--daemon*") {
                $daemonRunning = $true
                break
            }
        }

        if ($agRunning -and -not $daemonRunning) {
            # Give Antigravity 3 seconds to initialize DevToolsActivePort if it just booted
            Start-Sleep -Seconds 3
            Log-Message "Antigravity detectado en ejecucion. Iniciando daemon de control de cuentas..."
            
            Start-Process -FilePath "python.exe" `
                -ArgumentList @("$daemonScript", "--daemon") `
                -WorkingDirectory $ScriptDir `
                -WindowStyle Hidden
                
            Log-Message "Daemon de control de cuentas iniciado."
        }
        elseif (-not $agRunning -and $daemonRunning) {
            Log-Message "Antigravity cerrado. Deteniendo daemon de control..."
            foreach ($p in $pyProcs) {
                if ($p.CommandLine -like "*daemon_service.py*--daemon*") {
                    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
                }
            }
            Log-Message "Daemon detenido."
        }
    } catch {
        Log-Message "Error en ciclo de supervisor: $($_.Exception.Message)"
    }

    Start-Sleep -Seconds 3
}
