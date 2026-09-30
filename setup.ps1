# Instala dependencias, construye el índice RAG y compila el frontend (Windows).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path .env)) {
    Copy-Item .env.example .env
    Write-Host "Se creo .env: completa OLLAMA_API_KEY y vuelve a ejecutar."; exit 1
}
if (-not (Get-ChildItem rag-data -Filter *.docx -ErrorAction SilentlyContinue)) {
    Write-Host "Falta el .docx en rag-data\ (ver Setup.md)."; exit 1
}

if (-not (Test-Path .venv)) { python -m venv .venv }
# pip escribe avisos en stderr; no deben cortar el script
$ErrorActionPreference = "Continue"
.\.venv\Scripts\python -m pip install -q -r backend\requirements.txt 2>&1 | Out-Null
$ErrorActionPreference = "Stop"

Push-Location backend; ..\.venv\Scripts\python ingest.py; Pop-Location
Push-Location frontend; npm install; npm run build; Pop-Location
Write-Host "Listo. Ejecuta .\start.ps1"
