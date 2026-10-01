# Web http://localhost:8080 y API http://localhost:8010.
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose --env-file backend/.env -f compose.yaml -f compose.local.yaml up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Invest Lavalleja: http://localhost:8080/gianna/'
