# Igris - Notion-Style Google Assistant AI & Email Workspace

Igris is a sleek, black, minimalistic desktop AI assistant and workspace built with Electron and Python (FastAPI). Designed in the visual language of Notion, Igris functions exactly like a real-time **Google Voice Assistant** powered by **Google Gemini 2.0 Flash Multimodal Live API** (or offline local Ollama), complete with bidirectional speech-to-speech, Google neural voices, cross-platform OS app control, and an integrated IMAP email workspace.

## Features

- **Google Voice Assistant Mode (Cloud AI)**:
  - Powered by Google DeepMind's **Gemini 2.0 Flash Multimodal Live API** via raw WebSockets.
  - Sub-second speech-to-speech with natural intonation and cadence.
  - 5 expressive Google Assistant voices: **Aoede** (warm & natural), **Puck** (upbeat & energetic), **Charon** (calm & deep), **Fenrir** (authoritative), and **Kore** (gentle).
  - Signature Google Assistant 4-color wave animation (Blue, Red, Yellow, Green) responsive to speaking and listening states.
  - Native barge-in: seamlessly speak over the assistant at any moment to interrupt or redirect.
  - Automatic offline fallback: falls back to local Whisper + Ollama (`qwen2.5-coder:3b`) + Edge TTS when offline or if an API key is not supplied.
- **Sleek Notion Dark Aesthetic**:
  - Exact Notion dark theme palette (`#191919` canvas, `#202020` sidebar, `#252525` modal surfaces).
  - Collapsible sidebar with multi-page navigation (`Igris AI` and `Inbox`).
  - Database view with unread filters, real-time search, and unread badges.
  - Notion-style callouts, clean typography, code block syntax highlighting, and side peek drawer.
- **Integrated Email Workspace (IMAP)**:
  - Connect Gmail, Outlook, iCloud, Yahoo, or custom IMAP with one click in Settings.
  - Interactive Inbox database table with unread filters, live search, and unread badges.
  - Side peek drawer to view email headers, attachments, and full bodies.
  - One-click AI summaries for your entire inbox or individual emails.
  - Natural conversational email queries: *"Check my unread emails"*, *"Summarize email #1"*, or *"Do I have any emails from John?"*.
- **Direct Computer Control & System Tools**:
  - Open desktop apps (`VS Code`, `Chrome`, `Spotify`, `Settings`, `Terminal`) cross-platform without URL mistargeting.
  - Run terminal commands (`execute_command`) safely with timeouts.
  - Control media playback (Play, Pause, Skip, Prev) across Linux, macOS, and Windows.
  - Screen capture & visual analysis (`analyze_screen`).
  - DuckDuckGo live web search (`web_search`).
- **Compact Floating Mode**:
  - Click `MINI` in the top bar to snap Igris into a floating desktop widget.

## Keyboard Shortcuts

- `Ctrl + \` / `Cmd + \`: Toggle sidebar
- `Ctrl + ,` / `Cmd + ,`: Open Settings (Cloud AI, Email, Voice, Data)
- `Ctrl + Shift + O` / `Cmd + Shift + O`: Start New Chat
- `Enter`: Send message
- `Shift + Enter`: Multi-line prompt in composer
- `Space` (held in Voice Mode): Push-to-Talk
- `Escape`: Close modals, close email peek, or stop voice mode / generation

---

## Windows Setup Guide

You can easily set up Igris on a Windows machine entirely through the command line (Command Prompt or PowerShell) without needing to manually download zip files. 

### Prerequisites
Before you begin, ensure you have the following installed on your system:
- **Git** (for downloading the repository)
- **Python 3.10+** (for the AI backend)
- **Node.js & npm** (for the frontend UI)
- **Ollama** (for running the local LLM)

---

### Step 1: Clone the Repository
Open Command Prompt or PowerShell and run the following command to download the code:
```cmd
git clone https://github.com/YOUR_USERNAME/igris.git
cd igris
```
*(Note: Replace `YOUR_USERNAME` with your actual GitHub username or repository link if hosted online).*

### Step 2: Setup Ollama (Local AI Model)
Igris relies on a local LLM to process your conversational commands.
1. Download and install **Ollama** for Windows from [ollama.com/download/windows](https://ollama.com/download/windows).
2. Once installed, open a Command Prompt or PowerShell and pull the exact model Igris is configured to use:
```cmd
ollama pull qwen2.5-coder:3b
```
*Wait for the download to finish. Ensure the Ollama app remains running in your system tray.*

### Step 3: Setup the Python Backend
Igris requires a local Python server to run the Whisper AI model and handle system commands. 

Run these commands to create a virtual environment and install the dependencies:
```cmd
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
*Keep this terminal window open. You will need it to run the backend in Step 5.*

### Step 4: Setup the Electron Frontend
Open a **new** Command Prompt or PowerShell window, navigate to the `frontend` folder, and install the Node modules:
```cmd
cd path\to\igris\frontend
npm install
```

### Step 5: Run Igris
To start the application, you need to run both the backend and frontend simultaneously.

**1. Start the Backend:**
In your first terminal (where the virtual environment is activated), run:
```cmd
uvicorn main:app --host 127.0.0.1 --port 8000
```
*(Wait until you see `[SYSTEM] Whisper model loaded successfully.` in the console before starting the frontend).*

**2. Start the Frontend:**
In your second terminal (inside the `frontend` directory), run:
```cmd
npm start
```

### That's it!
Igris should now pop up on your screen. Just click the microphone (or use the hands-free voice trigger) and say, "Open VS Code", "Play a song on Spotify", or "Open Settings" to watch it interact with your Windows environment automatically!
