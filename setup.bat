@echo off
setlocal EnableDelayedExpansion
title IGRIS AI Assistant - Setup
color 0A

echo ============================================================
echo              IGRIS AI ASSISTANT - WINDOWS SETUP
echo ============================================================
echo.

:: ============================================================
:: Check Prerequisites
:: ============================================================

echo [SETUP] Checking prerequisites...
echo.

:: Check Python
where python >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo         Download from: https://www.python.org/downloads/
    echo         IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo [OK]    Python %PYTHON_VERSION% found.

:: Check pip
python -m pip --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] pip is not available. Reinstall Python with pip enabled.
    pause
    exit /b 1
)
echo [OK]    pip found.

:: Check Node.js
where node >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Node.js is not installed or not in PATH.
    echo         Download from: https://nodejs.org/
    echo.
    pause
    exit /b 1
)

for /f "tokens=1" %%i in ('node --version 2^>^&1') do set NODE_VERSION=%%i
echo [OK]    Node.js %NODE_VERSION% found.

:: Check npm
where npm >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] npm is not available. Reinstall Node.js.
    pause
    exit /b 1
)
echo [OK]    npm found.

:: Check FFmpeg
where ffmpeg >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [WARNING] FFmpeg is not installed or not in PATH.
    echo           FFmpeg is REQUIRED for audio processing (voice input).
    echo.
    echo           Install options:
    echo             1. winget install Gyan.FFmpeg
    echo             2. choco install ffmpeg    (if Chocolatey is installed)
    echo             3. Download from https://ffmpeg.org/download.html
    echo                and add to PATH manually.
    echo.
    set /p CONTINUE="Continue setup without FFmpeg? (y/N): "
    if /i not "!CONTINUE!"=="y" (
        exit /b 1
    )
) else (
    echo [OK]    FFmpeg found.
)

:: Check Ollama
where ollama >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Ollama is not installed or not in PATH.
    echo         Ollama is REQUIRED for the AI brain (LLM).
    echo.
    echo         Download from: https://ollama.com/download
    echo.
    pause
    exit /b 1
)
echo [OK]    Ollama found.

:: Check if Ollama is running
curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [SETUP] Ollama is not running. Starting Ollama...
    start "Ollama" /min ollama serve
    timeout /t 3 /nobreak >nul
    curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Could not start Ollama. Please start it manually:
        echo         ollama serve
        echo.
        pause
        exit /b 1
    )
)
echo [OK]    Ollama is running.

:: Check and pull required Ollama models
echo [SETUP] Checking required AI models...

ollama list 2>nul | findstr /i "qwen2.5-coder:3b" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [SETUP] Downloading qwen2.5-coder:3b model (~2GB)...
    echo         This is the main AI brain. Please wait...
    ollama pull qwen2.5-coder:3b
    if !ERRORLEVEL! NEQ 0 (
        echo [ERROR] Failed to download qwen2.5-coder:3b model.
        pause
        exit /b 1
    )
    echo [OK]    qwen2.5-coder:3b downloaded.
) else (
    echo [OK]    qwen2.5-coder:3b model found.
)

ollama list 2>nul | findstr /i "llava" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [SETUP] Downloading llava vision model (~4GB)...
    echo         This enables screen analysis. Please wait...
    ollama pull llava
    if !ERRORLEVEL! NEQ 0 (
        echo [WARNING] Failed to download llava model. Screen analysis will be unavailable.
    ) else (
        echo [OK]    llava model downloaded.
    )
) else (
    echo [OK]    llava model found.
)

echo.
echo [SETUP] All prerequisites checked.
echo.

:: ============================================================
:: Backend Setup
:: ============================================================

echo ============================================================
echo [SETUP] Setting up Backend (Python)...
echo ============================================================
echo.

cd /d "%~dp0backend"

:: Create virtual environment
if not exist "venv" (
    echo [SETUP] Creating Python virtual environment...
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK]    Virtual environment created.
) else (
    echo [OK]    Virtual environment already exists.
)

:: Activate venv and install dependencies
echo [SETUP] Installing Python dependencies (this may take several minutes)...
echo         Packages: FastAPI, Whisper, DeepFilterNet, PyTorch, edge-tts, etc.
echo.

call venv\Scripts\activate.bat

:: Upgrade pip first
python -m pip install --upgrade pip --quiet

:: Install PyTorch CPU first (large download ~200MB)
echo [SETUP] Installing PyTorch (CPU)...
pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cpu
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] PyTorch installation had issues. Retrying...
    pip install torch torchaudio --extra-index-url https://download.pytorch.org/whl/cpu
)

:: Install remaining dependencies
echo [SETUP] Installing remaining dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Failed to install some Python dependencies.
    echo         Check the error messages above.
    pause
    exit /b 1
)

echo.
echo [OK]    All Python dependencies installed.

:: ============================================================
:: Download Whisper Model
:: ============================================================

echo.
echo [SETUP] Pre-downloading Whisper speech recognition model...
echo         This is a one-time download (~3GB for large-v3).
echo         Please wait, this may take a while...
echo.

python -c "from faster_whisper import WhisperModel; m = WhisperModel('large-v3', device='cpu', compute_type='int8'); print('[OK]    Whisper model (large-v3) downloaded successfully.')" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Could not download large-v3 model. Trying medium.en as fallback...
    python -c "from faster_whisper import WhisperModel; m = WhisperModel('medium.en', device='cpu', compute_type='int8'); print('[OK]    Whisper model (medium.en) downloaded successfully.')" 2>nul
    if !ERRORLEVEL! NEQ 0 (
        echo [WARNING] Could not pre-download Whisper model. It will download on first use.
    )
)

:: ============================================================
:: DeepFilterNet Model Check
:: ============================================================

echo.
echo [SETUP] Pre-downloading DeepFilterNet noise suppression model...

python -c "import df_compat; from df.enhance import init_df; m, s, _ = init_df(); print('[OK]    DeepFilterNet model downloaded successfully.')" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Could not pre-download DeepFilterNet model. It will download on first use.
)

call deactivate

:: ============================================================
:: Frontend Setup
:: ============================================================

echo.
echo ============================================================
echo [SETUP] Setting up Frontend (Electron)...
echo ============================================================
echo.

cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo [SETUP] Installing Electron and frontend dependencies...
    call npm install
    if %ERRORLEVEL% NEQ 0 (
        echo [ERROR] Failed to install Node.js dependencies.
        pause
        exit /b 1
    )
    echo [OK]    Frontend dependencies installed.
) else (
    echo [OK]    Frontend dependencies already installed.
)

:: ============================================================
:: Done
:: ============================================================

cd /d "%~dp0"

echo.
echo ============================================================
echo           IGRIS AI ASSISTANT - SETUP COMPLETE!
echo ============================================================
echo.
echo  You can now launch Igris by running:
echo.
echo      start.bat
echo.
echo  Or double-click start.bat in File Explorer.
echo ============================================================
echo.
pause
