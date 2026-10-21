# Private build requested by the owner. Never publish the resulting installer.
param([string]$OutputPath)
$ErrorActionPreference = 'Stop'
$taskProject = Split-Path -Parent $PSScriptRoot
if (-not $OutputPath) { $OutputPath = Join-Path $taskProject 'dist/SnowbrickPersonalSetup.exe' }
$taskPayload = Join-Path $taskProject 'build/payload.zip'
if (-not (Test-Path -LiteralPath $taskPayload)) { throw 'Build the standard application payload first.' }
$taskPrivateDirectory = Join-Path $taskProject ('data/private-build/' + [guid]::NewGuid().ToString('N'))
$taskKeyFile = Join-Path $taskPrivateDirectory 'access.txt'
New-Item -ItemType Directory -Path $taskPrivateDirectory -Force | Out-Null
try {
  $taskSecure = Import-Clixml -LiteralPath (Join-Path $taskProject 'data/print-agent-token.xml')
  $taskToken = ConvertFrom-SecureString -SecureString $taskSecure -AsPlainText
  if ($taskToken -notmatch '^[A-Za-z0-9_-]{32,128}$') { throw 'Invalid private access bundle.' }
  [IO.File]::WriteAllText($taskKeyFile,$taskToken,[Text.UTF8Encoding]::new($false))
  $taskCompiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
  & $taskCompiler /nologo /target:winexe /platform:x64 /reference:System.Windows.Forms.dll /reference:System.Security.dll /reference:System.Web.Extensions.dll /reference:System.IO.Compression.dll /reference:System.IO.Compression.FileSystem.dll /reference:Microsoft.CSharp.dll "/resource:$taskPayload,payload.zip" "/resource:$taskKeyFile,preconnected.token" "/out:$OutputPath" (Join-Path $taskProject 'desktop/Setup.cs')
  if ($LASTEXITCODE -ne 0) { throw 'Private installer compilation failed.' }
  'Personal installer built. Keep the file private.'
} finally {
  $taskToken = $null
  if (Test-Path -LiteralPath $taskKeyFile) { Remove-Item -LiteralPath $taskKeyFile -Force }
}
