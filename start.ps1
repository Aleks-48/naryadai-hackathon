$ErrorActionPreference = "Stop"
$preferredPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$projectServer = Join-Path $PSScriptRoot 'server.py'

if (Test-Path -LiteralPath $preferredPython) {
    & $preferredPython -X utf8 $projectServer @args
    exit $LASTEXITCODE
}

if (Get-Command py.exe -ErrorAction SilentlyContinue) {
    & py.exe -3.12 -c 'import PIL' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw 'Подготовьте окружение: .\setup.ps1. Нужны Python 3.12 и Pillow.'
    }
    & py.exe -3.12 -X utf8 $projectServer @args
    exit $LASTEXITCODE
}

throw 'Окружение не найдено. Выполните .\setup.ps1 -PythonExe <путь к Python 3.12>.'
