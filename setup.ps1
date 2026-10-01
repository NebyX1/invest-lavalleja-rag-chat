# Construye frontend y backend con sus contextos Docker independientes.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (-not (Test-Path -LiteralPath backend/.env)) {
    Copy-Item -LiteralPath backend/.env.example -Destination backend/.env
    Write-Host 'Se creó backend/.env. Configurá Ollama, ADMIN_SECRET_KEY y SMTP.'
    exit 1
}
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Imágenes listas. Ejecutá .\start.ps1'
