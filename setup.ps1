param(
    [string]$PythonExe,
    [switch]$ApiOnly
)
$ErrorActionPreference = 'Stop'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    if ($PythonExe) {
        & $PythonExe -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
        if ($LASTEXITCODE -ne 0) { throw 'Укажите Python 3.12.' }
        & $PythonExe -m venv (Join-Path $PSScriptRoot '.venv')
    } elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.12 -m venv (Join-Path $PSScriptRoot '.venv')
    } else {
        throw 'Установите Python 3.12 или передайте -PythonExe с путём к интерпретатору.'
    }
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось создать .venv.' }
}
& $projectPython -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
if ($LASTEXITCODE -ne 0) { throw 'Существующее .venv должно использовать Python 3.12.' }
$requirementsFile = if ($ApiOnly) { 'requirements-api.txt' } else { 'requirements-streamlit.txt' }
& $projectPython -m pip install -r (Join-Path $PSScriptRoot $requirementsFile)
if ($LASTEXITCODE -ne 0) { throw 'Не удалось установить зависимости.' }
& $projectPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Найдены конфликты зависимостей.' }
Write-Output 'Окружение готово. Запуск: .\start.ps1. Проверки: .\verify.ps1.'
