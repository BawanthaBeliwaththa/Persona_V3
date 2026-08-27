@echo off
echo ===================================================
echo   Starting Persona V3 API Server with Uvicorn
echo ===================================================
cd /d %~dp0
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --loop asyncio
pause
