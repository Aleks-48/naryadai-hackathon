param([switch]$ApiOnly)
$ErrorActionPreference = 'Stop'
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) { throw 'Сначала выполните .\setup.ps1.' }
if (-not (Get-Command node -ErrorAction SilentlyContinue)) { throw 'Для проверок PWA установите Node.js.' }
Push-Location $PSScriptRoot
try {
    & $projectPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Конфликты зависимостей.' }
    if ($ApiOnly) {
        & $projectPython -X utf8 -m unittest tests.test_app tests.test_independent_security tests.test_reporting tests.test_review_acceptance -q
    } else {
        & $projectPython -X utf8 -m unittest discover -q
    }
    if ($LASTEXITCODE -ne 0) { throw 'Python-тесты не пройдены.' }
    & node --check static/app.js
    if ($LASTEXITCODE -ne 0) { throw 'Ошибка синтаксиса PWA.' }
    & node --test tests/test_frontend_races.js
    if ($LASTEXITCODE -ne 0) { throw 'Node-тесты не пройдены.' }
    if (-not $ApiOnly) {
        & $projectPython -X utf8 tests/run_streamlit_apptest.py
        if ($LASTEXITCODE -ne 0) { throw 'Streamlit AppTest не пройден.' }
        & $projectPython -X utf8 tests/run_streamlit_cloud_smoke.py
        if ($LASTEXITCODE -ne 0) { throw 'Streamlit HTTP smoke не пройден.' }
    }
    Write-Output 'Все выбранные локальные проверки пройдены. Внешние LLM/Telegram и Android проверяются отдельно.'
} finally {
    Pop-Location
}
