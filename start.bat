@echo off
setlocal enabledelayedexpansion
title Shorts Engine
cd /d "%~dp0"

echo ========================================================
echo                SHORTS ENGINE - AUTOPILOT
echo ========================================================
echo.

rem 1. Set environment variables for local models
set "OLLAMA_MODELS=D:\Open_Source_Weights\ollama"
set "OLLAMA_HOST=127.0.0.1:11434"

rem 2. Activate virtual environment (create if missing)
if not exist ".venv\Scripts\activate.bat" (
    echo [.venv not found] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment. Ensure Python 3.12 is installed.
        pause
        exit /b 1
    )
    call .venv\Scripts\activate.bat
    echo Installing requirements...
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

rem 3. Ensure Ollama local LLM service is running
echo [1/3] Ensuring Ollama local LLM service is running...
python scripts\ensure_ollama.py

rem 4. Run environment checks
echo [2/3] Checking runtime environment...
python scripts\check_env.py

rem 5. Launch web browser in background as soon as server is responsive
echo [3/3] Starting web server on http://127.0.0.1:8000 ...
start /B "" python scripts\open_browser.py

echo.
echo ========================================================
echo  Ready! Opening http://127.0.0.1:8000 in your browser...
echo  Paste your YouTube link into the interface to begin.
echo  Keep this console window open while clipping.
echo ========================================================
echo.

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
if errorlevel 1 (
    echo.
    echo [ERROR] Web server stopped with error code %errorlevel%.
    pause
)
