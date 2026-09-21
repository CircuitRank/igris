# Igris - Cross-Platform AI Assistant (Jarvis)

Igris is a powerful, cross-platform voice-activated AI assistant built with Electron and Python (FastAPI). It natively supports Windows, Linux, and macOS, seamlessly integrating with your operating system to open apps, play music, execute terminal commands, and more.

## Windows Setup Guide

You can easily set up Igris on a Windows machine entirely through the command line (Command Prompt or PowerShell) without needing to manually download zip files. 

### Prerequisites
Before you begin, ensure you have the following installed on your system:
- **Git** (for downloading the repository)
- **Python 3.10+** (for the AI backend)
- **Node.js & npm** (for the frontend UI)

---

### Step 1: Clone the Repository
Open Command Prompt or PowerShell and run the following command to download the code:
```cmd
git clone https://github.com/YOUR_USERNAME/igris.git
cd igris
```
*(Note: Replace `YOUR_USERNAME` with your actual GitHub username or repository link if hosted online. Otherwise, you can initialize it from a local network share).*

### Step 2: Setup the Python Backend
Igris requires a local Python server to run the Whisper AI model and handle system commands. 

Run these commands to create a virtual environment and install the dependencies:
```cmd
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```
*Keep this terminal window open. You will need it to run the backend in Step 4.*

### Step 3: Setup the Electron Frontend
Open a **new** Command Prompt or PowerShell window, navigate to the `frontend` folder, and install the Node modules:
```cmd
cd path\to\igris\frontend
npm install
```

### Step 4: Run Igris
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
