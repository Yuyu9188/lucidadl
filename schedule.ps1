<#
  Planifie l'exécution "en fond".
  Crée une tâche planifiée Windows qui lance le téléchargement chaque jour.

  IMPORTANT : la tâche est configurée "quand l'utilisateur est connecté"
  (LogonType Interactive) car le navigateur a besoin d'un bureau visible pour
  passer Cloudflare. Reste donc connecté(e) à ta session à l'heure prévue.

  Exemples :
    .\schedule.ps1                         # albums, tous les jours à 09:00
    .\schedule.ps1 -Mode tracks -Time 21:30
    .\schedule.ps1 -Mode albums -Time 08:00 -TaskName LucidaMatin
  Pour supprimer :  Unregister-ScheduledTask -TaskName LucidaDL -Confirm:$false
#>
param(
  [ValidateSet("albums", "tracks")] [string]$Mode = "albums",
  [string]$Time = "09:00",
  [string]$TaskName = "LucidaDL"
)

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$run = Join-Path $root "run.cmd"

$action    = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$run`" $Mode" -WorkingDirectory $root
$trigger   = New-ScheduledTaskTrigger -Daily -At $Time
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings  = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Tache '$TaskName' creee : '$Mode' tous les jours a $Time (quand tu es connecte)." -ForegroundColor Green
Write-Host "Tester maintenant :  Start-ScheduledTask -TaskName $TaskName"
