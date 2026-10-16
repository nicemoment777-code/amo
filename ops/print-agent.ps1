param([Parameter(ValueFromRemainingArguments=$true)][string[]]$AgentArgs)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$secretPath = Join-Path $projectRoot 'data/print-agent-token.xml'
$secureToken = Import-Clixml -LiteralPath $secretPath
try {
  $env:PRINT_AGENT_TOKEN = ConvertFrom-SecureString -SecureString $secureToken -AsPlainText
  $pythonPath = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
  & $pythonPath (Join-Path $PSScriptRoot 'print-agent.py') @AgentArgs
  if ($LASTEXITCODE -ne 0) { throw 'Ошибка агента печати. Проверьте его локальный журнал.' }
} finally { Remove-Item Env:PRINT_AGENT_TOKEN -ErrorAction SilentlyContinue }
