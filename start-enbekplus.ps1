$ErrorActionPreference = 'Stop'
$serverPath = Join-Path $PSScriptRoot 'server.py'
$serverArgs = @($args)
if (-not (Test-Path -LiteralPath $serverPath -PathType Leaf)) {
    throw 'server.py was not found next to the launcher.'
}

function Start-WithPython312([string]$PythonPath) {
    & $PythonPath -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
    if ($LASTEXITCODE -ne 0) {
        throw 'The selected interpreter is not Python 3.12.'
    }
    & $PythonPath $serverPath @serverArgs
    exit $LASTEXITCODE
}

if ($env:ENBEKPLUS_PYTHON) {
    if (-not (Test-Path -LiteralPath $env:ENBEKPLUS_PYTHON -PathType Leaf)) {
        throw 'ENBEKPLUS_PYTHON does not point to a file.'
    }
    Start-WithPython312 $env:ENBEKPLUS_PYTHON
}

$localVenvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $localVenvPython -PathType Leaf) {
    Start-WithPython312 $localVenvPython
}

$pyLauncher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
if ($pyLauncher) {
    & $pyLauncher.Source -3.12 $serverPath @serverArgs
    exit $LASTEXITCODE
}

$knownPython = 'C:\Users\777\Documents\Codex\2026-09-30\task-2\.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $knownPython -PathType Leaf) {
    Start-WithPython312 $knownPython
}

throw 'Python 3.12 was not found. Install Python 3.12, create .venv, or set ENBEKPLUS_PYTHON.'