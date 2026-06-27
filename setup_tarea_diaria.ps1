# setup_tarea_diaria.ps1
#
# Registra (o actualiza) la tarea de scraping diario en Windows Task Scheduler.
# Ejecutar UNA SOLA VEZ con PowerShell como Administrador:
#
#   Set-ExecutionPolicy RemoteSigned -Scope CurrentUser   # (si es la primera vez)
#   .\setup_tarea_diaria.ps1

$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe  = (Get-Command python -ErrorAction Stop).Source
$RunScript  = Join-Path $ScriptDir "run_daily.py"
$LogDir     = Join-Path $ScriptDir "logs"
$TaskName   = "ScrapeAEV_Diario"
$RunAt      = "02:00AM"   # <-- cambiar aquí si se desea otro horario

# Crear carpeta de logs si no existe
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "Carpeta de logs creada: $LogDir"
}

# Eliminar tarea previa del mismo nombre si existe
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

# Acción: python run_daily.py
$Action = New-ScheduledTaskAction `
    -Execute   $PythonExe `
    -Argument  "`"$RunScript`"" `
    -WorkingDirectory $ScriptDir

# Trigger: diario a la hora configurada
$Trigger = New-ScheduledTaskTrigger -Daily -At $RunAt

# Configuración de la tarea
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 4) `
    -RestartCount        2 `
    -RestartInterval     (New-TimeSpan -Minutes 30) `
    -StartWhenAvailable                           # corre aunque el horario se haya perdido

# Registrar con privilegios elevados (necesario para correr sin sesión abierta)
Register-ScheduledTask `
    -TaskName   $TaskName `
    -Action     $Action `
    -Trigger    $Trigger `
    -Settings   $Settings `
    -Description "Scraping diario personas desaparecidas Venezuela + envío a API" `
    -RunLevel   Highest `
    -Force

Write-Host ""
Write-Host "Tarea '$TaskName' registrada exitosamente."
Write-Host "Hora de ejecucion: $RunAt (diario)"
Write-Host "Script: $RunScript"
Write-Host "Logs:   $LogDir\YYYY-MM-DD.log"
Write-Host ""
Write-Host "Comandos utiles:"
Write-Host "  Ejecutar ahora:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Ver estado:      Get-ScheduledTask  -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  Eliminar tarea:  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
