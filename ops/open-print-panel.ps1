param([switch]$BackgroundAgent)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
try {
  $env:PRINT_AGENT_TOKEN = ConvertFrom-SecureString (Import-Clixml (Join-Path $projectRoot 'data/print-agent-token.xml')) -AsPlainText
  $env:SNOWBRICK_HOME = Join-Path $projectRoot 'data/desktop-panel'
  $env:SNOWBRICK_DATA_DIR = Join-Path $projectRoot 'data/printing'
  $pythonPath = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
  $taskAgentArgs = @('--background-agent')
  if (-not $BackgroundAgent) { $taskAgentArgs += '--show-window' }
  $taskInstalled = Join-Path $env:LOCALAPPDATA 'Programs/SnowbrickWebAgent/SnowbrickPrinter.exe'
  if (Test-Path -LiteralPath $taskInstalled) {
    & $taskInstalled @taskAgentArgs --profile-home $env:SNOWBRICK_HOME --printing-data $env:SNOWBRICK_DATA_DIR
  } else {
    & $pythonPath (Join-Path $projectRoot 'desktop/app.py') @taskAgentArgs
  }
} finally {
  Remove-Item Env:PRINT_AGENT_TOKEN -ErrorAction SilentlyContinue
  Remove-Item Env:SNOWBRICK_HOME -ErrorAction SilentlyContinue
  Remove-Item Env:SNOWBRICK_DATA_DIR -ErrorAction SilentlyContinue
}
