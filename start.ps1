$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$nodePath = (Get-Command node -ErrorAction Stop).Source
& $nodePath --env-file-if-exists=.env server.mjs
