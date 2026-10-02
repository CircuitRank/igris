@echo off
setlocal EnableDelayedExpansion
title IGRIS AI Assistant
color 0A

:: Navigate to the project root
cd /d "%~dp0"

echo ============================================================
echo              IGRIS AI ASSISTANT - Starting...
echo ============================================================
echo.

:: ============================================================
:: Check if setup has been run
:: ============================================================

if not exist "backend\venv" (
    echo [ERROR] Backend virtual environment not found.
    echo         Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

if not exist "frontend\node_modules" (
    echo [ERROR] Frontend dependencies not found.
    echo         Please run setup.bat first.
    echo.
    pause
    exit /b 1
)

:: ============================================================
:: Ensure Ollama is running
:: ============================================================

echo [SYSTEM] Checking Ollama...

curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [SYSTEM] Ollama is not running. Starting Ollama...
    start "Ollama" /min ollama serve
    timeout /t 3 /nobreak >nul
    curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Could not start Ollama. Please start it manually and try again.
        pause
        exit /b 1
    )
)
echo [OK]    Ollama is running.

:: ============================================================
:: Start Backend
:: ============================================================

echo [SYSTEM] Starting Backend...

cd /d "%~dp0backend"
call venv\Scripts\activate.bat

:: Start backend in the background
start "Igris Backend" /min cmd /c "python main.py"

:: Give the backend a moment to start
echo [SYSTEM] Waiting for backend to initialize...
timeout /t 3 /nobreak >nul

:: Check if backend started
curl -s http://127.0.0.1:8000/ >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [SYSTEM] Backend still starting, waiting a bit more...
    timeout /t 5 /nobreak >nul
)

echo [SYSTEM] Backend started.

:: ============================================================
:: Start Frontend
:: ============================================================

echo [SYSTEM] Starting Frontend...

cd /d "%~dp0frontend"
call npm start

:: ============================================================
:: Cleanup on exit
:: ============================================================

echo.
echo [SYSTEM] Shutting down Igris...

:: Kill the backend process
taskkill /fi "WINDOWTITLE eq Igris Backend" /f >nul 2>&1

:: Also kill any uvicorn processes we started
for /f "tokens=2" %%a in ('tasklist /fi "IMAGENAME eq python.exe" /fo list ^| findstr "PID"') do (
    wmic process where "ProcessId=%%a" get CommandLine 2>nul | findstr "main.py" >nul 2>&1
    if !ERRORLEVEL! EQU 0 (
        taskkill /pid %%a /f >nul 2>&1
    )
)

echo [SYSTEM] Igris AI Assistant Shut Down.
pause
