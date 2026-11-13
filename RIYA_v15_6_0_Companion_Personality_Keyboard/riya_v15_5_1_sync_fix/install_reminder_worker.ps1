$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $Python) { $Python = (Get-Command python.exe -ErrorAction Stop).Source }
$TaskName = 'RIYA Background Reminders'
$Worker = Join-Path $Root 'riya_reminder_worker.py'
$Db = Join-Path $Root 'data\riya.db'
$Arguments = '"' + $Worker + '" --db "' + $Db + '" --interval 15'
$Action = New-ScheduledTaskAction -Execute $Python -Argument $Arguments -WorkingDirectory $Root
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Seconds 0) -MultipleInstances IgnoreNew -StartWhenAvailable
$Principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Runs RIYA reminders independently of the browser while this Windows user is signed in.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host 'RIYA background reminders installed and started.' -ForegroundColor Green
Write-Host 'The worker runs while you are signed in, even when Edge is closed.'
