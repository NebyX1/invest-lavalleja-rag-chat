# Levanta API + frontend compilado en http://localhost:8010
Set-Location $PSScriptRoot\backend
..\.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8010
