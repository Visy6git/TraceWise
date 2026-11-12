@echo off
setlocal
cd /d "%~dp0.."

if exist ".venv\Scripts\uvicorn.exe" (
  call ".venv\Scripts\uvicorn.exe" app.main:app --reload --reload-dir app --port 8000
) else (
  call uvicorn app.main:app --reload --reload-dir app --port 8000
)
