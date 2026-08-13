@echo off
setlocal
set "PROJECT_ROOT=%~dp0.."
cd /d "%PROJECT_ROOT%\services\api"
if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  .venv\Scripts\python.exe -m pip install -r requirements.txt
)
if not exist ".data\uploads" mkdir ".data\uploads"
if not exist ".data\backups" mkdir ".data\backups"
start "拼豆工作台 API" /B .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd /d "%PROJECT_ROOT%"
if not exist "node_modules" call npm ci
set "NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000"
start "" http://127.0.0.1:3000
call npm run dev -- --host 127.0.0.1 --port 3000
