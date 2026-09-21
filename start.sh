#!/bin/bash

# Navigate to the project root
cd "$(dirname "$0")"

echo "[SYSTEM] Starting Igris AI Assistant..."

# 1. Setup and start backend
echo "[SYSTEM] Initializing Backend..."
cd backend
if [ ! -d "venv" ]; then
    echo "[SYSTEM] Creating Python virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate
pip install -r requirements.txt
# Start backend in the background
python3 main.py &
BACKEND_PID=$!
cd ..

# 2. Setup and start frontend
echo "[SYSTEM] Initializing Frontend..."
cd frontend
if [ ! -d "node_modules" ]; then
    echo "[SYSTEM] Installing Electron dependencies..."
    npm install
fi
# Start frontend
npm start

# Cleanup on exit
kill $BACKEND_PID
echo "[SYSTEM] Igris AI Assistant Shut Down."
