@echo off
setlocal enabledelayedexpansion
title Shorts Engine
cd /d "%~dp0"

echo ========================================================
echo                SHORTS ENGINE - AUTOPILOT
echo ========================================================
echo.

rem 1. Ensure .env exists (initialize from .env.example on first clone)
if not exist ".env" (
    if exist ".env.example" (
        copy ".env.example" ".env" >nul
        echo [SETUP] Initialized .env from .env.example
    )
)

rem 2. Load settings from .env file
if exist ".env" (
    for /f "usebackq eol=# tokens=1,* delims==" %%A in (".env") do (
        set "%%A=%%B"
    )
)

rem 3. Set absolute paths for local models (resolving relative paths from .env)
if defined WEIGHTS_DIR (
    for %%I in ("!WEIGHTS_DIR!") do set "WEIGHTS_DIR=%%~fI"
) else (
    set "WEIGHTS_DIR=%~dp0weights"
)
if defined OLLAMA_MODELS (
    for %%I in ("!OLLAMA_MODELS!") do set "OLLAMA_MODELS=%%~fI"
) else (
    set "OLLAMA_MODELS=!WEIGHTS_DIR!\ollama"
)
if defined HF_HOME (
    for %%I in ("!HF_HOME!") do set "HF_HOME=%%~fI"
) else (
    set "HF_HOME=!WEIGHTS_DIR!\huggingface"
)
if defined HF_HUB_CACHE (
    for %%I in ("!HF_HUB_CACHE!") do set "HF_HUB_CACHE=%%~fI"
) else (
    set "HF_HUB_CACHE=!HF_HOME!\hub"
)
if defined TORCH_HOME (
    for %%I in ("!TORCH_HOME!") do set "TORCH_HOME=%%~fI"
) else (
    set "TORCH_HOME=!WEIGHTS_DIR!\torch"
)
if not defined OLLAMA_HOST (
    set "OLLAMA_HOST=127.0.0.1:11434"
)
set "OLLAMA_KEEP_ALIVE=60m"
set "OLLAMA_MAX_LOADED_MODELS=3"
set "OLLAMA_NUM_PARALLEL=1"

rem 4. Activate virtual environment (create if missing)
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

rem 5. Clean up any leftover detached runners to prevent popup windows
taskkill /F /IM "llama-server.exe" >nul 2>&1
taskkill /F /IM "ollama.exe" >nul 2>&1

rem 6. Check components & run interactive setup wizard if any models are missing
echo [1/3] Checking models and first-time setup...
python scripts\setup_wizard.py

rem 7. Ensure Ollama local LLM service is running with configured models
echo [2/3] Ensuring Ollama local LLM service is active...
python scripts\ensure_ollama.py

rem 8. Run environment checks
echo [3/3] Checking runtime environment...
python scripts\check_env.py

rem 9. Launch web browser in background as soon as server is responsive
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
