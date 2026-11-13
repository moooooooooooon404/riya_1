$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = [System.Drawing.SystemIcons]::Information
$icon.Visible = $true
$icon.BalloonTipTitle = $env:RIYA_TOAST_TITLE
$icon.BalloonTipText = $env:RIYA_TOAST_BODY
$icon.BalloonTipIcon = [System.Windows.Forms.ToolTipIcon]::Info
$icon.ShowBalloonTip(10000)
Start-Sleep -Seconds 10
$icon.Dispose()
