$ErrorActionPreference = "Stop"
$preferredPython = 'C:\Users\777\Documents\Codex\2026-09-30\task-2\.venv\Scripts\python.exe'
$projectServer = Join-Path $PSScriptRoot 'server.py'

if (Test-Path -LiteralPath $preferredPython) {
    & $preferredPython $projectServer @args
    exit $LASTEXITCODE
}

if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    & py.exe -3.12 $projectServer @args
    exit $LASTEXITCODE
}

throw 'Python 3.12 не найден. Укажите рабочий интерпретатор Python 3.12 и запустите server.py вручную.'
