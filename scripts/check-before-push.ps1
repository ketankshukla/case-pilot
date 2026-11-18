$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot '.venv\Scripts\python.exe'

Push-Location -LiteralPath (Join-Path $repoRoot 'backend')
try {
    & $python -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Pop-Location
}

npm --prefix (Join-Path $repoRoot 'frontend') run build
exit $LASTEXITCODE
