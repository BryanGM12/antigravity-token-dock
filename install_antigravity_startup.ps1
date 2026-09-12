# Installer for Antigravity Startup Integration
# Configures Windows Task Scheduler and WMI triggers to ensure the auto-activator
# and account controller launch automatically whenever Antigravity is started or user logs in.

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ActivatorScript = "$ScriptDir\antigravity_auto_activator.py"
$PythonwExe = "C:\Users\Administrator\AppData\Local\Programs\Python\Python313\pythonw.exe"
$TaskName = "AntigravityAutoActivator"

Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "  ✦ CONFIGURANDO AUTO-INICIO DEL CONTROLADOR ANTIGRAVITY ✦" -ForegroundColor Cyan
Write-Host "=======================================================" -ForegroundColor Cyan

# 1. Register Scheduled Task in Task Scheduler
Write-Host "1. Creando tarea programada en Windows Task Scheduler..." -ForegroundColor Yellow

$Action = New-ScheduledTaskAction -Execute $PythonwExe -Argument "`"$ActivatorScript`" --daemon" -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 365)

# Unregister legacy task if existed
Unregister-ScheduledTask -TaskName "AntigravityAutoAccountSupervisor" -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings | Out-Null
Write-Host "   [OK] Tarea '$TaskName' registrada exitosamente." -ForegroundColor Green

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

    Write-Host "   [OK] Disparador WMI vinculado: 'Antigravity.exe' activa el sistema instantaneamente." -ForegroundColor Green
} catch {
    Write-Host "   [AVISO WMI] $($_.Exception.Message). La tarea programada seguira funcionando en Logon." -ForegroundColor Yellow
}

# 3. Start the task right now
Write-Host "3. Iniciando tarea de auto-activacion..." -ForegroundColor Yellow
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "   Estado de tarea: $($taskInfo.LastTaskResult)" -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
Write-Host "[OK] Integracion completada. El sistema se activara" -ForegroundColor Green
Write-Host "     automaticamente cada vez que Antigravity este activo." -ForegroundColor Green
Write-Host "=======================================================" -ForegroundColor Cyan
