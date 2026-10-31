param([int]$PreviousPid = 0)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskSource = Join-Path $taskRoot 'dist/SnowbrickPrinter'
$taskDest = Join-Path $env:LOCALAPPDATA 'Programs/SnowbrickWebAgent'
$taskHome = Join-Path $taskRoot 'data/desktop-panel'
$taskData = Join-Path $taskRoot 'data/printing'
if (-not (Test-Path -LiteralPath (Join-Path $taskSource 'SnowbrickPrinter.exe'))) { throw 'Build the Windows module first.' }
New-Item -ItemType Directory -Path $taskDest -Force | Out-Null
$taskLock = [IO.File]::Open((Join-Path $taskData 'agent.lock'),[IO.FileMode]::OpenOrCreate,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
try {
  if ($taskLock.Length -lt 1) { $taskLock.SetLength(1) }
  $taskLock.Lock(0,1)
  if ($PreviousPid) {
    $taskPrevious = Get-Process -Id $PreviousPid -ErrorAction SilentlyContinue
    if ($taskPrevious) {
      if ($taskPrevious.ProcessName -notin @('python','pythonw','SnowbrickPrinter')) { throw 'Unexpected process; migration stopped.' }
      Stop-Process -Id $PreviousPid -Force
      $taskPrevious.WaitForExit(10000) | Out-Null
    }
  }
  Get-ChildItem -LiteralPath $taskSource | Copy-Item -Destination $taskDest -Recurse -Force
  $taskSecure = Import-Clixml -LiteralPath (Join-Path $taskRoot 'data/print-agent-token.xml')
  $taskPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($taskSecure)
  try {
    $taskPlain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($taskPointer)
    $taskBytes = [Text.Encoding]::UTF8.GetBytes($taskPlain)
    $taskProtected = [Security.Cryptography.ProtectedData]::Protect($taskBytes,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser)
    $taskKeyPath = Join-Path $taskHome 'device-key.bin'
    if ((Test-Path -LiteralPath $taskKeyPath) -and -not (Test-Path -LiteralPath ($taskKeyPath+'.before-web-agent'))) {
      Copy-Item -LiteralPath $taskKeyPath -Destination ($taskKeyPath+'.before-web-agent')
    }
    [IO.File]::WriteAllBytes($taskKeyPath,$taskProtected)
  } finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($taskPointer)
    if ($taskBytes) { [Array]::Clear($taskBytes,0,$taskBytes.Length) }
    $taskPlain=$null
  }
  $taskSettingsPath = Join-Path $taskHome 'settings.json'
  $taskSettings = Get-Content -LiteralPath $taskSettingsPath -Raw | ConvertFrom-Json -AsHashtable
  $taskSettings['startup'] = $true
  [IO.File]::WriteAllText(($taskSettingsPath+'.web-agent.tmp'),($taskSettings | ConvertTo-Json -Depth 30),[Text.UTF8Encoding]::new($false))
  [IO.File]::Move(($taskSettingsPath+'.web-agent.tmp'),$taskSettingsPath,$true)
  $taskExe = Join-Path $taskDest 'SnowbrickPrinter.exe'
  $taskArguments = '--background-agent --profile-home "'+$taskHome+'" --printing-data "'+$taskData+'"'
  $taskStartup = '"'+$taskExe+'" '+$taskArguments
  New-Item -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Force | Out-Null
  New-ItemProperty -Path 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -Name 'SnowbrickPrinter' -Value $taskStartup -PropertyType String -Force | Out-Null
} finally {
  try { $taskLock.Unlock(0,1) } catch {}
  $taskLock.Dispose()
}
Start-Process -FilePath $taskExe -ArgumentList $taskArguments -WindowStyle Hidden
'Standalone Windows module installed and started; existing printing data preserved.'
