# Installer checks use a synthetic key only; no credentials or network requests.
$ErrorActionPreference='Stop'
$taskRoot=Split-Path -Parent $PSScriptRoot
$taskArea=Join-Path $taskRoot ('data/installer-unit-'+[guid]::NewGuid().ToString('N'))
$taskPayloadDir=Join-Path $taskArea 'payload'
New-Item -ItemType Directory -Path $taskPayloadDir -Force|Out-Null
Set-Content -LiteralPath (Join-Path $taskPayloadDir 'SnowbrickPrinter.exe') -Value 'synthetic payload; never executed' -Encoding ascii
Add-Type -AssemblyName System.IO.Compression.FileSystem
$taskPayload=Join-Path $taskArea 'payload.zip'
[IO.Compression.ZipFile]::CreateFromDirectory($taskPayloadDir,$taskPayload)
$taskDummy='TEST_ONLY_'+('a'*33)
$taskKeyFile=Join-Path $taskArea 'synthetic-access.txt'
[IO.File]::WriteAllText($taskKeyFile,$taskDummy,[Text.UTF8Encoding]::new($false))
$taskCompiler=Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
$taskExe=Join-Path $taskArea 'SyntheticSetup.exe'
& $taskCompiler /nologo /target:winexe /platform:x64 /reference:System.Windows.Forms.dll /reference:System.Security.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:Microsoft.CSharp.dll "/resource:$taskPayload,payload.zip" "/resource:$taskKeyFile,preconnected.token" "/out:$taskExe" (Join-Path $taskRoot 'desktop/Setup.cs')
if ($LASTEXITCODE -ne 0) { throw 'Synthetic installer compilation failed' }
$taskDest=Join-Path $taskArea 'installed'
$taskProfile=Join-Path $taskDest 'test-profile'
$taskPrinting=Join-Path $taskProfile 'printing'
New-Item -ItemType Directory -Path $taskPrinting -Force|Out-Null
Set-Content -LiteralPath (Join-Path $taskProfile 'settings.json') -Value '{"printer":"Saved test printer","startup":true,"paired":false}' -Encoding utf8
Set-Content -LiteralPath (Join-Path $taskPrinting 'state.json') -Value '{"activatedAt":100,"printed":{"123":{}},"uncertain":{"456":{}}}' -Encoding utf8
Set-Content -LiteralPath (Join-Path $taskPrinting 'auto-print.json') -Value '{"enabled":false}' -Encoding utf8
$taskBefore=(Get-FileHash -LiteralPath (Join-Path $taskPrinting 'state.json')).Hash
$taskAutoBefore=(Get-FileHash -LiteralPath (Join-Path $taskPrinting 'auto-print.json')).Hash
$taskProcess=Start-Process -FilePath $taskExe -ArgumentList @('--test-install',$taskDest) -WindowStyle Hidden -Wait -PassThru
if ($taskProcess.ExitCode -ne 0) { throw 'Synthetic installer failed' }
$taskConfig=Get-Content -LiteralPath (Join-Path $taskProfile 'settings.json') -Raw|ConvertFrom-Json
if ($taskConfig.paired -ne $true -or $taskConfig.printer -ne 'Saved test printer' -or $taskConfig.startup -ne $true) { throw 'Settings preservation failed' }
if ((Get-FileHash -LiteralPath (Join-Path $taskPrinting 'state.json')).Hash -ne $taskBefore -or (Get-FileHash -LiteralPath (Join-Path $taskPrinting 'auto-print.json')).Hash -ne $taskAutoBefore) { throw 'Printing history or switch changed' }
Add-Type -AssemblyName System.Security
$taskStored=[IO.File]::ReadAllBytes((Join-Path $taskProfile 'device-key.bin'))
$taskDecoded=[Text.Encoding]::UTF8.GetString([Security.Cryptography.ProtectedData]::Unprotect($taskStored,$null,[Security.Cryptography.DataProtectionScope]::CurrentUser))
if ($taskDecoded -cne $taskDummy) { throw 'Synthetic DPAPI round trip failed' }
$taskShell=New-Object -ComObject WScript.Shell
foreach ($taskLink in @('Desktop/Снегострой — печать этикеток.lnk','StartMenu/Печать СДЭК.lnk')) {
  $taskShortcut=$taskShell.CreateShortcut((Join-Path $taskDest ('test-shortcuts/'+$taskLink)))
  if ($taskShortcut.TargetPath -ne (Join-Path $taskDest 'SnowbrickPrinter.exe')) { throw 'Shortcut failed' }
}
'Synthetic installer OK: preconnected DPAPI key, existing settings/history preserved, autoprint unchanged, both shortcuts valid.'
