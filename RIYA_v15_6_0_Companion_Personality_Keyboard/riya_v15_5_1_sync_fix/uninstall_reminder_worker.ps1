$ErrorActionPreference = 'Stop'
$TaskName = 'RIYA Background Reminders'
$Task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Task) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host 'RIYA background reminders removed.' -ForegroundColor Green
} else { Write-Host 'RIYA background reminder task was not installed.' }
