$ErrorActionPreference = "Stop"

function Fail($Message) {
    Write-Host ""
    Write-Host "[ERROR] $Message" -ForegroundColor Red
    exit 1
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    Fail "No se encontró Python Launcher (py). Instala Python 3.12 y vuelve a ejecutar este script."
}

& py -3.12 --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Python 3.12 no está instalado." -ForegroundColor Red
    Write-Host ""
    Write-Host "Opción recomendada si tu launcher lo soporta:"
    Write-Host "  py install 3.12"
    Write-Host ""
    Write-Host "Alternativa con Windows Package Manager:"
    Write-Host "  winget install -e --id Python.Python.3.12"
    Write-Host ""
    Write-Host "Después cerrá y abrí PowerShell y ejecutá nuevamente:"
    Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1"
    exit 1
}

Write-Host "Python detectado:"
& py -3.12 --version

if (Test-Path ".venv") {
    Write-Host "El entorno .venv ya existe. Se reutilizará."
} else {
    Write-Host "Creando entorno virtual .venv..."
    & py -3.12 -m venv .venv
    if ($LASTEXITCODE -ne 0) {
        Fail "No se pudo crear el entorno virtual .venv."
    }
}

$venvPython = ".\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Fail "No existe $venvPython. El entorno virtual no se creó correctamente."
}

Write-Host "Actualizando pip..."
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Fail "No se pudo actualizar pip."
}

Write-Host "Instalando dependencias..."
& $venvPython -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) {
    Fail "No se pudieron instalar las dependencias."
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Se creó .env. Edita DATABASE_URL y BOT_ADMIN_TOKEN antes de continuar."
}

Write-Host ""
Write-Host "Entorno preparado correctamente." -ForegroundColor Green
Write-Host "1) Edita .env"
Write-Host "2) Ejecuta: .\.venv\Scripts\alembic.exe upgrade head"
Write-Host "3) API: .\.venv\Scripts\uvicorn.exe app.main:app --reload"
Write-Host "4) Worker PAPER: .\.venv\Scripts\python.exe -m app.worker"
