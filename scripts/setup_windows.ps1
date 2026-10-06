$ErrorActionPreference = "Stop"

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "No se encontró Python Launcher (py). Instala Python 3.12."
}

py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Se creó .env. Edita DATABASE_URL y BOT_ADMIN_TOKEN antes de continuar."
}

Write-Host ""
Write-Host "Entorno preparado."
Write-Host "1) Edita .env"
Write-Host "2) Ejecuta: .\.venv\Scripts\alembic.exe upgrade head"
Write-Host "3) API: .\.venv\Scripts\uvicorn.exe app.main:app --reload"
Write-Host "4) Worker PAPER: .\.venv\Scripts\python.exe -m app.worker"
