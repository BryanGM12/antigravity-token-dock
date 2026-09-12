# Installer for Antigravity Startup Integration
# Configures Windows Task Scheduler and WMI triggers to ensure the account controller
# launches automatically whenever Antigravity is started.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$DaemonScript = "$ScriptDir\daemon_service.py"
$PythonwExe = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe"
$TaskName = "AntigravityAutoAccountSupervisor"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  CONFIGURANDO AUTO-INICIO DEL CONTROLADOR ANTIGRAVITY " -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Register Scheduled Task in Task Scheduler
Write-Host "1. Creando tarea programada en Windows Task Scheduler..." -ForegroundColor Yellow

$Action = New-ScheduledTaskAction -Execute $PythonwExe -Argument "`"$DaemonScript`" --daemon" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Unregister if previously existed
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings | Out-Null
Write-Host "   ✅ Tarea '$TaskName' registrada exitosamente." -ForegroundColor Green

# 2. Register WMI Event Trigger for immediate process creation wake-up
Write-Host "2. Configurando disparador de WMI para Antigravity.exe..." -ForegroundColor Yellow
try {
    # Remove existing instances if present
    Get-CimInstance -Namespace "root\subscription" -ClassName __FilterToConsumerBinding -ErrorAction SilentlyContinue |
        Where-Object { $_.Filter.Name -eq "AntigravityProcessFilter" } |
        Remove-CimInstance -ErrorAction SilentlyContinue

    Get-CimInstance -Namespace "root\subscription" -ClassName __EventFilter -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "AntigravityProcessFilter" } |
        Remove-CimInstance -ErrorAction SilentlyContinue

    Get-CimInstance -Namespace "root\subscription" -ClassName CommandLineEventConsumer -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "AntigravityProcessConsumer" } |
        Remove-CimInstance -ErrorAction SilentlyContinue

    # Create Filter
    $wql = "SELECT * FROM __InstanceCreationEvent WITHIN 2 WHERE TargetInstance ISA 'Win32_Process' AND TargetInstance.Name = 'Antigravity.exe'"
    $filter = New-CimInstance -Namespace "root\subscription" -ClassName __EventFilter -Property @{
        Name = "AntigravityProcessFilter"
        EventNamespace = "root\cimv2"
        QueryLanguage = "WQL"
        Query = $wql
    }

    # Create Consumer
    $consumer = New-CimInstance -Namespace "root\subscription" -ClassName CommandLineEventConsumer -Property @{
        Name = "AntigravityProcessConsumer"
        CommandLineTemplate = "schtasks.exe /run /tn `"$TaskName`""
    }

    # Bind Filter and Consumer
    New-CimInstance -Namespace "root\subscription" -ClassName __FilterToConsumerBinding -Property @{
        Filter = [ref]$filter
        Consumer = [ref]$consumer
    } | Out-Null

    Write-Host "   ✅ Disparador WMI vinculado: 'Antigravity.exe' activa la tarea instantaneamente." -ForegroundColor Green
} catch {
    Write-Host "   ⚠️ Aviso WMI: $($_.Exception.Message). La tarea programada seguira funcionando en Logon." -ForegroundColor Yellow
}

# 3. Start the task right now for the currently running Antigravity session
Write-Host "3. Iniciando tarea para la sesion actual..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "   Ultimo resultado: $($taskInfo.LastTaskResult)" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "✅ Integracion completada. El controlador se iniciara" -ForegroundColor Green
Write-Host "   automaticamente cada vez que abras Antigravity." -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
