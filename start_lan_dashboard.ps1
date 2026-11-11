param([int] $Port = 8000)

$ErrorActionPreference = "Stop"
$Project = $PSScriptRoot
$Python = Join-Path $Project ".venv-yolo-new\Scripts\python.exe"

if (Test-Path -LiteralPath $Python) {
    & $Python (Join-Path $Project "web_dashboard.py") --host 0.0.0.0 --port $Port
} else {
    & py -3.12 (Join-Path $Project "web_dashboard.py") --host 0.0.0.0 --port $Port
}
