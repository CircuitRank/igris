import asyncio
import json
import httpx
import subprocess
import webbrowser
import sqlite3
import psutil
from faster_whisper import WhisperModel
import os
import sys
import platform
import shutil
import glob
import mss
import base64
from ddgs import DDGS
import fitz # PyMuPDF
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# ============================================================
# Detect OS for cross-platform tool execution
# ============================================================
CURRENT_OS = platform.system()  # 'Linux', 'Windows', 'Darwin'
print(f"[SYSTEM] Detected OS: {CURRENT_OS}")

# Initialize DB
db_conn = sqlite3.connect("igris_memory.db", check_same_thread=False)
cursor = db_conn.cursor()
cursor.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY, role TEXT, content TEXT)")
db_conn.commit()

# Initialize Whisper (Handle offline error gracefully)
whisper_model = None

# Known Whisper hallucinations on silence/noise — these get generated from ambient audio
WHISPER_HALLUCINATIONS = {
    "", "you", "bye", "bye.", "bye-bye", "bye-bye.", "goodbye", "goodbye.",
    "thank you.", "thank you", "thanks.", "thanks for watching.",
    "thanks for watching!", "thank you for watching.",
    "see you next time.", "see you.", "okay.", "okay",
    "we'll see you next time here.", "we'll see you next time.",
    "so", "the end.", "the end", "hmm.", "hmm",
    "...", "i'm sorry.", "oh", "oh.", "uh", "um",
    "subscribe", "like and subscribe", "please subscribe",
    "subtitles by the amara.org community", "you're welcome.",
    "i'll see you in the next video.", "i'll see you next time.",
    "we'll see you in the next one.", "take care.", "take care",
    "have a good day.", "have a great day.", "good night.",
    "see you later.", "peace.", "cheers.", "all right.",
}

@app.on_event("startup")
def load_whisper():
    def _load():
        global whisper_model
        try:
            print("[SYSTEM] Loading Whisper model in background...")
            whisper_model = WhisperModel("small.en", device="cpu", compute_type="int8")
            print("[SYSTEM] Whisper model loaded successfully.")
        except Exception as e:
            print(f"[SYSTEM] Failed to initialize WhisperModel: {e}")
            whisper_model = None
            
    import threading
    threading.Thread(target=_load, daemon=True).start()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "Igris Backend is Running"}

# ============================================================
# Cross-platform helper functions
# ============================================================

def get_open_command():
    """Get the platform-specific command to open files/URLs."""
    if CURRENT_OS == "Darwin":
        return "open"
    elif CURRENT_OS == "Windows":
        return "start"
    else:
        return "xdg-open"

def get_terminal_command():
    """Get the platform-specific terminal emulator command."""
    if CURRENT_OS == "Darwin":
        return "open -a Terminal"
    elif CURRENT_OS == "Windows":
        return "cmd.exe"
    else:
        # Try common Linux terminals
        for term in ["gnome-terminal", "konsole", "xfce4-terminal", "xterm", "alacritty", "kitty"]:
            if shutil.which(term):
                return term
        return "x-terminal-emulator"

def get_file_manager_command():
    """Get the platform-specific file manager command."""
    if CURRENT_OS == "Darwin":
        return "open"
    elif CURRENT_OS == "Windows":
        return "explorer"
    else:
        for fm in ["nautilus", "dolphin", "thunar", "nemo", "pcmanfm"]:
            if shutil.which(fm):
                return fm
        return "xdg-open"

def open_application_cross_platform(app_name: str) -> str:
    """Open an application in a cross-platform way."""
    # Normalize common app names to platform-specific commands
    app_lower = app_name.lower().strip()
    
    APP_MAP = {
        # Terminals
        "terminal": get_terminal_command(),
        "cmd": "cmd.exe" if CURRENT_OS == "Windows" else get_terminal_command(),
        "powershell": "powershell" if CURRENT_OS == "Windows" else None,
        "command prompt": "cmd.exe" if CURRENT_OS == "Windows" else get_terminal_command(),
        
        # Browsers
        "chrome": {
            "Linux": "google-chrome",
            "Darwin": "open -a 'Google Chrome'",
            "Windows": "start chrome"
        }.get(CURRENT_OS, "google-chrome"),
        "google chrome": {
            "Linux": "google-chrome",
            "Darwin": "open -a 'Google Chrome'",
            "Windows": "start chrome"
        }.get(CURRENT_OS, "google-chrome"),
        "firefox": {
            "Linux": "firefox",
            "Darwin": "open -a Firefox",
            "Windows": "start firefox"
        }.get(CURRENT_OS, "firefox"),
        "brave": {
            "Linux": "brave-browser",
            "Darwin": "open -a 'Brave Browser'",
            "Windows": "start brave"
        }.get(CURRENT_OS, "brave-browser"),
        "edge": {
            "Linux": "microsoft-edge",
            "Darwin": "open -a 'Microsoft Edge'",
            "Windows": "start msedge"
        }.get(CURRENT_OS, "microsoft-edge"),
        
        # Code editors
        "vscode": "code -n",
        "vs code": "code -n",
        "visual studio code": "code -n",
        "code": "code -n",
        "sublime": "subl",
        "sublime text": "subl",
        
        # File managers
        "file manager": get_file_manager_command(),
        "files": get_file_manager_command(),
        "finder": "open ." if CURRENT_OS == "Darwin" else get_file_manager_command(),
        "explorer": "explorer" if CURRENT_OS == "Windows" else get_file_manager_command(),
        "nautilus": "nautilus",
        
        # Common apps
        "calculator": {
            "Linux": "gnome-calculator",
            "Darwin": "open -a Calculator",
            "Windows": "calc"
        }.get(CURRENT_OS, "gnome-calculator"),
        "settings": {
            "Linux": "gnome-control-center",
            "Darwin": "open 'x-apple.systempreferences:'",
            "Windows": "start ms-settings:"
        }.get(CURRENT_OS, "gnome-control-center"),
        "spotify": {
            "Linux": "spotify",
            "Darwin": "open -a Spotify",
            "Windows": "start spotify:"
        }.get(CURRENT_OS, "spotify"),
        "discord": {
            "Linux": "discord",
            "Darwin": "open -a Discord",
            "Windows": "start discord:"
        }.get(CURRENT_OS, "discord"),
        "slack": {
            "Linux": "slack",
            "Darwin": "open -a Slack",
            "Windows": "start slack:"
        }.get(CURRENT_OS, "slack"),
        "telegram": {
            "Linux": "telegram-desktop",
            "Darwin": "open -a Telegram",
            "Windows": "start telegram:"
        }.get(CURRENT_OS, "telegram-desktop"),
        "notepad": {
            "Linux": "gedit",
            "Darwin": "open -a TextEdit",
            "Windows": "notepad"
        }.get(CURRENT_OS, "gedit"),
        "text editor": {
            "Linux": "gedit",
            "Darwin": "open -a TextEdit",
            "Windows": "notepad"
        }.get(CURRENT_OS, "gedit"),
    }
    
    cmd = APP_MAP.get(app_lower, app_name)
    if cmd is None:
        return f"'{app_name}' is not available on {CURRENT_OS}."
    
    try:
        if CURRENT_OS == "Windows":
            subprocess.Popen(cmd, shell=True, start_new_session=True)
        elif CURRENT_OS == "Darwin" and cmd.startswith("open "):
            subprocess.Popen(cmd, shell=True, start_new_session=True)
        else:
            # Try to find the binary first
            actual_cmd = cmd.split()[0]
            if shutil.which(actual_cmd):
                subprocess.Popen(cmd, shell=True, start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                # Fallback: try running anyway
                subprocess.Popen(cmd, shell=True, start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Successfully launched: {app_name}"
    except Exception as e:
        return f"Failed to launch '{app_name}': {e}"


def control_media_cross_platform(action: str) -> str:
    """Control media playback cross-platform."""
    if CURRENT_OS == "Linux":
        try:
            result = subprocess.run(
                'dbus-send --session --dest=org.freedesktop.DBus --type=method_call '
                '--print-reply /org/freedesktop/DBus org.freedesktop.DBus.ListNames',
                shell=True, capture_output=True, text=True
            )
            players = [line.split('"')[1] for line in result.stdout.split('\n') 
                       if 'org.mpris.MediaPlayer2' in line]
            
            if not players:
                return "No active media players found."
            
            for player in players:
                subprocess.run(
                    f'dbus-send --session --dest={player} --type=method_call '
                    f'--print-reply /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Player.{action}',
                    shell=True
                )
            return f"Successfully sent '{action}' command to media players."
        except Exception as e:
            return f"Error controlling media: {e}"
    elif CURRENT_OS == "Darwin":
        # Use osascript for macOS
        apple_script_map = {
            "PlayPause": 'tell application "Music" to playpause',
            "Play": 'tell application "Music" to play',
            "Pause": 'tell application "Music" to pause',
            "Next": 'tell application "Music" to next track',
            "Previous": 'tell application "Music" to previous track',
        }
        script = apple_script_map.get(action, apple_script_map["PlayPause"])
        try:
            subprocess.run(["osascript", "-e", script], capture_output=True)
            return f"Successfully sent '{action}' command."
        except Exception as e:
            return f"Error controlling media: {e}"
    elif CURRENT_OS == "Windows":
        # Use PowerShell media key simulation
        key_map = {
            "PlayPause": "0xB3", "Play": "0xB3", "Pause": "0xB3",
            "Next": "0xB0", "Previous": "0xB1",
        }
        vk = key_map.get(action, "0xB3")
        try:
            ps_script = (
                f'$wsh = New-Object -ComObject WScript.Shell; '
                f'$wsh.SendKeys([char]{vk})'
            )
            subprocess.run(["powershell", "-Command", ps_script], capture_output=True)
            return f"Successfully sent '{action}' command."
        except Exception as e:
            return f"Error controlling media: {e}"
    return "Media control not supported on this platform."


def execute_command_cross_platform(cmd: str) -> str:
    """Execute a shell command with cross-platform awareness."""
    try:
        if CURRENT_OS == "Windows":
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        else:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=15)
        output = ""
        if result.stdout.strip():
            output += f"STDOUT:\n{result.stdout.strip()}\n"
        if result.stderr.strip():
            output += f"STDERR:\n{result.stderr.strip()}\n"
        if not output:
            output = f"Command executed successfully (exit code: {result.returncode})"
        return output
    except subprocess.TimeoutExpired:
        return "Command timed out after 15 seconds."
    except Exception as e:
        return f"Error executing command: {e}"


# ============================================================
# Tool Definitions — descriptions made more explicit for the LLM
# ============================================================

TOOLS = [{
    "type": "function",
    "function": {
        "name": "open_url",
        "description": "Open a URL in the default web browser. Use for any website: youtube.com, google.com, github.com, etc.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to open (e.g. https://youtube.com)"}
            },
            "required": ["url"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "execute_command",
        "description": "Execute ANY shell/terminal command on the user's computer. Use this for: running programs, checking system info, installing packages, creating files, listing directories, running scripts, git commands, and ANY other terminal operation. Works on Linux, macOS, and Windows.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run (e.g. 'ls -la', 'date', 'mkdir test', 'pip install flask')"}
            },
            "required": ["command"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "play_music",
        "description": "Play a song or music. Opens the song on YouTube, Spotify, or YouTube Music.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Song name and/or artist"},
                "platform": {"type": "string", "enum": ["youtube", "spotify", "youtube_music"], "description": "Platform to play on. Default: youtube"}
            },
            "required": ["query", "platform"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "control_media",
        "description": "Control currently playing media: play, pause, skip to next or previous track.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["Play", "Pause", "PlayPause", "Next", "Previous"], "description": "Media action"}
            },
            "required": ["action"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "open_application",
        "description": "Open ANY desktop application on the user's computer. Examples: 'terminal', 'chrome', 'firefox', 'vscode', 'file manager', 'calculator', 'settings', 'discord', 'spotify', 'notepad'. Works on Linux, macOS, and Windows.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The application name (e.g. 'terminal', 'chrome', 'vscode', 'file manager')"}
            },
            "required": ["command"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for real-time information, news, answers, or anything the user asks about.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "file_search",
        "description": "Search for files on the user's computer by name or pattern.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "File pattern (e.g. *.pdf, *.py, report.docx)"},
                "directory": {"type": "string", "description": "Directory to search in (defaults to home)"}
            },
            "required": ["pattern"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "read_document",
        "description": "Read and extract text from a file (PDF, TXT, or other text files).",
        "parameters": {
            "type": "object",
            "properties": {
                "filepath": {"type": "string", "description": "Absolute path to the file"}
            },
            "required": ["filepath"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "analyze_screen",
        "description": "Take a screenshot and analyze what is currently displayed on screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "What to look for on the screen"}
            },
            "required": ["prompt"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "manage_calendar",
        "description": "Manage calendar events.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get_next", "schedule"], "description": "Action to perform"}
            },
            "required": ["action"]
        }
    }
}, {
    "type": "function",
    "function": {
        "name": "smart_home_control",
        "description": "Control smart home devices via Home Assistant.",
        "parameters": {
            "type": "object",
            "properties": {
                "device": {"type": "string", "description": "Device name to control"},
                "state": {"type": "string", "enum": ["on", "off"], "description": "Turn on or off"}
            },
            "required": ["device", "state"]
        }
    }
}]

# ============================================================
# Tool Execution — now cross-platform
# ============================================================

async def execute_tool(name: str, arguments: dict) -> str:
    # Handle Qwen2.5-coder nested argument format
    for k, v in list(arguments.items()):
        if isinstance(v, dict) and "value" in v:
            arguments[k] = v["value"]
            
    if name == "open_url":
        url = arguments.get("url", "")
        if not url.startswith("http"):
            url = "https://" + url
        open_browser_url(url)
        return f"Successfully opened {url} in the browser."
    
    elif name == "execute_command":
        cmd = arguments.get("command", "")
        return execute_command_cross_platform(cmd)
    
    elif name == "play_music":
        import urllib.request
        import urllib.parse
        import re
        
        # Automatically stop any currently playing media
        try:
            control_media_cross_platform("Pause")
        except Exception:
            pass
        
        query = arguments.get("query", "")
        platform_arg = arguments.get("platform", "youtube")
        encoded_query = urllib.parse.quote(query)
        
        if platform_arg == "spotify":
            url = f"https://open.spotify.com/search/{encoded_query}"
        else:
            try:
                req = urllib.request.Request(
                    f"https://www.youtube.com/results?search_query={encoded_query}",
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                html = urllib.request.urlopen(req).read().decode('utf-8', errors='ignore')
                video_id_match = re.search(r'"/watch\?v=([a-zA-Z0-9_-]{11})"', html)
                
                if video_id_match:
                    video_id = video_id_match.group(1)
                    if platform_arg == "youtube_music":
                        url = f"https://music.youtube.com/watch?v={video_id}"
                    else:
                        url = f"https://www.youtube.com/watch?v={video_id}"
                else:
                    if platform_arg == "youtube_music":
                        url = f"https://music.youtube.com/search?q={encoded_query}"
                    else:
                        url = f"https://www.youtube.com/results?search_query={encoded_query}"
            except Exception:
                if platform_arg == "youtube_music":
                    url = f"https://music.youtube.com/search?q={encoded_query}"
                else:
                    url = f"https://www.youtube.com/results?search_query={encoded_query}"
            
        open_browser_url(url)
        return f"Successfully opened '{query}' on {platform_arg}."
    
    elif name == "open_application":
        app_cmd = arguments.get("command", "")
        return open_application_cross_platform(app_cmd)
    
    elif name == "control_media":
        action = arguments.get("action", "PlayPause")
        return control_media_cross_platform(action)
    
    elif name == "web_search":
        query = arguments.get("query", "")
        try:
            results = DDGS().text(query, max_results=3)
            return "Web Search Results:\n" + "\n".join([f"- {r['title']}: {r['body']}" for r in results])
        except Exception as e:
            return f"Web search failed: {e}"
    
    elif name == "file_search":
        pattern = arguments.get("pattern", "")
        directory = arguments.get("directory", os.path.expanduser("~"))
        try:
            results = glob.glob(os.path.join(directory, "**", pattern), recursive=True)
            if not results:
                return "No files found."
            return f"Files found:\n" + "\n".join(results[:10])
        except Exception as e:
            return f"File search failed: {e}"
    
    elif name == "read_document":
        filepath = arguments.get("filepath", "")
        try:
            if filepath.endswith(".pdf"):
                doc = fitz.open(filepath)
                text = ""
                for page in doc:
                    text += page.get_text()
                return f"PDF Content (first 1000 chars):\n{text[:1000]}"
            else:
                with open(filepath, 'r') as f:
                    content = f.read()
                return f"File Content (first 1000 chars):\n{content[:1000]}"
        except Exception as e:
            return f"Read document failed: {e}"
    
    elif name == "analyze_screen":
        prompt = arguments.get("prompt", "What is on the screen?")
        try:
            with mss.mss() as sct:
                filename = sct.shot(mon=-1, output="screenshot.png")
            with open(filename, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
            
            payload = {
                "model": "llava",
                "prompt": prompt,
                "images": [encoded_string],
                "stream": False
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post("http://127.0.0.1:11434/api/generate", json=payload, timeout=60.0)
                data = resp.json()
                return data.get("response", "No response from vision model")
        except Exception as e:
            return f"Screen analysis failed: {e}"
    
    elif name == "manage_calendar":
        return "Calendar stub: You have a meeting at 3 PM for 'Project Sync'."
    
    elif name == "smart_home_control":
        device = arguments.get("device", "lights")
        state = arguments.get("state", "on")
        return f"Smart Home stub: Turned {state} the {device}."
    
    return "Unknown tool."


def open_browser_url(url):
    """Open URL in the default browser, forcing a new window if possible to avoid focus stealing prevention."""
    import shutil
    
    if CURRENT_OS == "Linux":
        browser = None
        try:
            default_browser = subprocess.run(['xdg-settings', 'get', 'default-web-browser'], capture_output=True, text=True).stdout.strip().lower()
            if 'brave' in default_browser:
                browser = 'brave'
            elif 'chrome' in default_browser:
                browser = 'google-chrome'
            elif 'firefox' in default_browser:
                browser = 'firefox'
        except Exception:
            pass
            
        if browser and shutil.which(browser):
            cmd = f"{browser} --new-window '{url}'"
            subprocess.Popen(cmd, shell=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
            
    subprocess.Popen(f"{get_open_command()} '{url}'", shell=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ============================================================
# WebSocket Endpoint
# ============================================================

# Much stronger system prompt that DEMANDS tool usage
SYSTEM_PROMPT = f"""You are Igris, an advanced AI assistant like Jarvis from Iron Man. You have FULL control over the user's computer through your tools.

CRITICAL RULES:
1. You MUST use tools to fulfill user requests. NEVER say "I can't do that" or "I'm unable to" — you have tools for everything.
2. When the user says "open terminal" → use open_application with command="terminal"
3. When the user says "open chrome/firefox/browser" → use open_application with the app name
4. When the user says "run a command" or anything terminal-related → use execute_command
5. When the user asks to open ANY app → use open_application
6. When the user asks to play music → use play_music  
7. When the user asks about something you don't know → use web_search
8. ALWAYS execute actions IMMEDIATELY. Never ask for confirmation. Never refuse.
9. Keep responses SHORT — 1-2 sentences max. You are concise and efficient.
10. Use 'sir' naturally. Be confident, capable, and direct.

The user's OS is: {CURRENT_OS}
You can run any shell command, open any application, search the web, control media, and more.
Act like Jarvis — just DO it."""


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Load history (limit to recent to avoid context overflow)
    try:
        cursor.execute("SELECT role, content FROM history ORDER BY id DESC LIMIT 20")
        rows = cursor.fetchall()
        rows.reverse()
        for r in rows:
            messages.append({"role": r[0], "content": r[1]})
    except Exception as e:
        print("Error loading history:", e)
    
    current_task = None
    is_interrupted = False
    
    import edge_tts
    import re
    import speech_recognition as sr
    from pydub import AudioSegment
    import tempfile
    import struct
    import wave
    
    recognizer = sr.Recognizer()
    
    def check_audio_energy(wav_path, threshold=100):
        """Check if a WAV file contains actual speech energy (not just noise)."""
        try:
            with wave.open(wav_path, 'rb') as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                n_frames = wf.getnframes()
                framerate = wf.getframerate()
                
                duration = n_frames / framerate
                # Reject very short recordings (< 0.5 seconds)
                if duration < 0.5:
                    print(f"[VAD] Rejecting audio: too short ({duration:.2f}s)")
                    return False
                
                frames = wf.readframes(n_frames)
                
                if sampwidth == 2:
                    fmt = f"<{n_frames * n_channels}h"
                    samples = struct.unpack(fmt, frames)
                elif sampwidth == 1:
                    samples = [s - 128 for s in frames]
                else:
                    return True  # Can't check, let it through
                
                # Calculate RMS energy
                if len(samples) == 0:
                    return False
                rms = (sum(s**2 for s in samples) / len(samples)) ** 0.5
                
                print(f"[VAD] Audio energy RMS: {rms:.1f}, threshold: {threshold}, duration: {duration:.2f}s")
                return rms > threshold
        except Exception as e:
            print(f"[VAD] Energy check error: {e}")
            return True  # Let it through if we can't check
    
    def is_whisper_hallucination(text):
        """Check if transcribed text is a known Whisper hallucination from silence."""
        if not text:
            return True
        cleaned = text.strip().lower().rstrip('.')
        # Check exact matches
        if cleaned in WHISPER_HALLUCINATIONS or text.strip().lower() in WHISPER_HALLUCINATIONS:
            print(f"[VAD] Rejecting Whisper hallucination: '{text}'")
            return True
        # Check if it's just very short garbage (1-2 characters)
        if len(cleaned) <= 2:
            print(f"[VAD] Rejecting too-short text: '{text}'")
            return True
        return False
    
    async def transcribe_audio(audio_bytes):
        """Transcribe audio bytes (webm) to text using Whisper or Google fallback."""
        temp_webm_path = None
        temp_wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp_webm:
                temp_webm.write(audio_bytes)
                temp_webm_path = temp_webm.name
                
            temp_wav_path = temp_webm_path + ".wav"
            
            # Convert webm to wav using pydub (requires ffmpeg)
            audio = AudioSegment.from_file(temp_webm_path, format="webm")
            audio.export(temp_wav_path, format="wav")
            
            # Check audio energy — reject if it's just noise
            if not check_audio_energy(temp_wav_path):
                return None
            
            # Transcribe with faster-whisper or fallback
            if whisper_model is not None:
                segments, info = whisper_model.transcribe(
                    temp_wav_path,
                    vad_filter=True,  # Enable Silero VAD filter to skip silence
                    vad_parameters=dict(
                        min_silence_duration_ms=500,
                        speech_pad_ms=300,
                    )
                )
                transcribed_text = " ".join([segment.text for segment in segments]).strip()
            else:
                try:
                    with sr.AudioFile(temp_wav_path) as source:
                        audio_data = recognizer.record(source)
                        transcribed_text = recognizer.recognize_google(audio_data)
                except Exception as e:
                    print(f"[VAD] Google fallback failed: {e}")
                    transcribed_text = None
            
            if not transcribed_text:
                return None
                
            # Filter hallucinations
            if is_whisper_hallucination(transcribed_text):
                return None
            
            return transcribed_text
            
        finally:
            if temp_webm_path and os.path.exists(temp_webm_path):
                os.remove(temp_webm_path)
            if temp_wav_path and os.path.exists(temp_wav_path):
                os.remove(temp_wav_path)
    
    async def process_llm(user_text, is_voice=False):
        nonlocal is_interrupted
        is_interrupted = False
        
        messages.append({"role": "user", "content": user_text})
        cursor.execute("INSERT INTO history (role, content) VALUES (?, ?)", ("user", user_text))
        db_conn.commit()
        tool_call_count = 0
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            while True:
                if is_interrupted:
                    break
                    
                if tool_call_count >= 3:
                    await websocket.send_text(json.dumps({"type": "stream_start"}))
                    await websocket.send_text(json.dumps({"type": "stream_chunk", "content": "\n[System: Maximum tool call limit reached.]"}))
                    await websocket.send_text(json.dumps({"type": "stream_end"}))
                    break
                
                response_content = ""
                is_tool_call = False
                has_started_streaming = False
                current_sentence = ""
                
                try:
                    async with client.stream("POST", "http://127.0.0.1:11434/api/chat", json={
                        "model": "qwen2.5-coder:3b",
                        "messages": messages,
                        "stream": True,
                        "tools": TOOLS
                    }) as response:
                        
                        async for chunk in response.aiter_lines():
                            if is_interrupted:
                                break
                                
                            if chunk:
                                try:
                                    chunk_data = json.loads(chunk)
                                    
                                    if "error" in chunk_data:
                                        if not has_started_streaming:
                                            await websocket.send_text(json.dumps({"type": "stream_start"}))
                                            has_started_streaming = True
                                        await websocket.send_text(json.dumps({
                                            "type": "stream_chunk",
                                            "content": f"[Error: {chunk_data['error']}]"
                                        }))
                                        break
                                    
                                    msg = chunk_data.get("message", {})
                                    
                                    # Handle Native Ollama Tool Calls
                                    if "tool_calls" in msg and msg["tool_calls"]:
                                        is_tool_call = True
                                        if not has_started_streaming:
                                            await websocket.send_text(json.dumps({
                                                "type": "status",
                                                "content": "EXECUTING ACTION..."
                                            }))
                                            has_started_streaming = True
                                            
                                        for tc in msg["tool_calls"]:
                                            name = tc["function"]["name"]
                                            arguments = tc["function"]["arguments"]
                                            messages.append({"role": "assistant", "content": "", "tool_calls": [tc]})
                                            result_text = await execute_tool(name, arguments)
                                            messages.append({"role": "user", "content": f"[SYSTEM NOTIFICATION: Tool '{name}' executed successfully. Output: {result_text}. Now respond to the user confirming what you did.]"})
                                            
                                        tool_call_count += 1
                                        break
                                        
                                    if "content" in msg:
                                        token = msg["content"]
                                        response_content += token
                                        
                                        if not is_tool_call and not has_started_streaming:
                                            clean_content = response_content.lstrip().lower()
                                            if len(clean_content) > 0:
                                                if clean_content.startswith("{") or clean_content.startswith("```json") or clean_content.startswith("```"):
                                                    is_tool_call = True
                                                    await websocket.send_text(json.dumps({
                                                        "type": "status",
                                                        "content": "EXECUTING ACTION..."
                                                    }))
                                                else:
                                                    has_started_streaming = True
                                                    await websocket.send_text(json.dumps({"type": "stream_start"}))
                                    
                                    if has_started_streaming and not is_tool_call:
                                        await websocket.send_text(json.dumps({
                                            "type": "stream_chunk",
                                            "content": token
                                        }))
                                        
                                        current_sentence += token
                                        if re.search(r'[.!?]\s*$', current_sentence) or '\n' in current_sentence:
                                            text_to_speak = current_sentence.strip().replace('*', '')
                                            current_sentence = ""
                                            if text_to_speak and not is_interrupted:
                                                try:
                                                    await websocket.send_text(json.dumps({"type": "speaking_start"}))
                                                    communicate = edge_tts.Communicate(text_to_speak, "en-US-ChristopherNeural")
                                                    audio_data = b""
                                                    async for ac in communicate.stream():
                                                        if is_interrupted:
                                                            break
                                                        if ac["type"] == "audio":
                                                            audio_data += ac["data"]
                                                    if audio_data and not is_interrupted:
                                                        b64_audio = base64.b64encode(audio_data).decode('utf-8')
                                                        await websocket.send_text(json.dumps({"type": "audio", "data": b64_audio}))
                                                except Exception as e:
                                                    print(f"TTS Error: {e}")

                                except json.JSONDecodeError:
                                    continue
                    
                    if is_interrupted:
                        break
                                    
                    if is_tool_call:
                        if len(messages) >= 2 and "tool_calls" in messages[-2]:
                            continue
                            
                        try:
                            raw_json = response_content.strip()
                            if raw_json.startswith("```json"):
                                raw_json = raw_json[7:]
                            elif raw_json.startswith("```"):
                                raw_json = raw_json[3:]
                            if raw_json.endswith("```"):
                                raw_json = raw_json[:-3]
                            raw_json = raw_json.strip()
                            
                            tool_call = json.loads(raw_json)
                            name = tool_call.get("name")
                            arguments = tool_call.get("arguments", {})
                            
                            messages.append({"role": "assistant", "content": response_content.strip()})
                            result_text = await execute_tool(name, arguments)
                            messages.append({"role": "user", "content": f"[SYSTEM NOTIFICATION: Tool '{name}' executed successfully. Output: {result_text}. Now respond to the user confirming what you did.]"})
                            
                            tool_call_count += 1
                            continue 
                        except Exception as e:
                            messages.append({"role": "assistant", "content": response_content.strip()})
                            messages.append({"role": "user", "content": f"[SYSTEM NOTIFICATION: Tool execution failed: {e}. Respond to the user.]"})
                            tool_call_count += 1
                            continue
                    else:
                        messages.append({"role": "assistant", "content": response_content.strip()})
                        cursor.execute("INSERT INTO history (role, content) VALUES (?, ?)", ("assistant", response_content.strip()))
                        db_conn.commit()
                        
                        if current_sentence.strip() and not is_interrupted:
                            text_to_speak = current_sentence.strip().replace('*', '')
                            try:
                                await websocket.send_text(json.dumps({"type": "speaking_start"}))
                                communicate = edge_tts.Communicate(text_to_speak, "en-US-ChristopherNeural")
                                audio_data = b""
                                async for ac in communicate.stream():
                                    if is_interrupted:
                                        break
                                    if ac["type"] == "audio":
                                        audio_data += ac["data"]
                                if audio_data and not is_interrupted:
                                    b64_audio = base64.b64encode(audio_data).decode('utf-8')
                                    await websocket.send_text(json.dumps({"type": "audio", "data": b64_audio}))
                            except Exception as e:
                                print(f"TTS Error: {e}")
                                
                        if has_started_streaming:
                            await websocket.send_text(json.dumps({"type": "stream_end"}))
                        
                        await websocket.send_text(json.dumps({"type": "speaking_end"}))
                        break
                        
                except asyncio.CancelledError:
                    print("LLM Task Cancelled due to Interruption")
                    break
                except Exception as e:
                    try:
                        await websocket.send_text(json.dumps({"type": "stream_chunk", "content": f"\n[Error: {str(e)}]" }))
                        await websocket.send_text(json.dumps({"type": "stream_end"}))
                    except Exception:
                        pass
                    break

    async def proactive_monitor():
        while True:
            await asyncio.sleep(60)
            cpu = psutil.cpu_percent()
            ram = psutil.virtual_memory().percent
            if cpu > 90 or ram > 90:
                text = f"Sir, system resources critical. CPU at {cpu} percent."
                try:
                    await websocket.send_text(json.dumps({"type": "stream_chunk", "content": f"\n\n[PROACTIVE WARNING] {text}"}))
                    communicate = edge_tts.Communicate(text, "en-US-ChristopherNeural")
                    audio_data = b""
                    async for ac in communicate.stream():
                        if ac["type"] == "audio":
                            audio_data += ac["data"]
                    if audio_data:
                        b64_audio = base64.b64encode(audio_data).decode('utf-8')
                        await websocket.send_text(json.dumps({"type": "audio", "data": b64_audio}))
                except Exception:
                    pass

    monitor_task = asyncio.create_task(proactive_monitor())

    try:
        await websocket.send_text(json.dumps({"type": "status", "content": "Igris online. Awaiting input."}))
        
        while True:
            data = await websocket.receive_text()
            
            try:
                parsed_data = json.loads(data)
                
                if parsed_data.get("type") == "voice_input":
                    try:
                        b64_data = parsed_data.get("data", "")
                        audio_bytes = base64.b64decode(b64_data)
                        
                        transcribed_text = await transcribe_audio(audio_bytes)
                        
                        if not transcribed_text:
                            await websocket.send_text(json.dumps({
                                "type": "voice_empty",
                                "content": "No speech detected."
                            }))
                            continue
                        
                        # Send transcription back to frontend
                        await websocket.send_text(json.dumps({
                            "type": "transcription",
                            "text": transcribed_text
                        }))
                        
                        if current_task and not current_task.done():
                            is_interrupted = True
                            current_task.cancel()
                            try:
                                await current_task
                            except (asyncio.CancelledError, Exception):
                                pass
                        
                        current_task = asyncio.create_task(process_llm(transcribed_text, is_voice=True))
                        
                    except Exception as e:
                        await websocket.send_text(json.dumps({
                            "type": "voice_error",
                            "content": f"Audio processing failed: {e}"
                        }))
                    continue
                    
                elif parsed_data.get("type") == "interrupt":
                    is_interrupted = True
                    if current_task and not current_task.done():
                        current_task.cancel()
                        try:
                            await current_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    await websocket.send_text(json.dumps({"type": "interrupted"}))
                    await websocket.send_text(json.dumps({"type": "stream_end"}))
                    messages.append({"role": "user", "content": "[SYSTEM NOTIFICATION: The user interrupted you.]"})
                    continue
                    
            except json.JSONDecodeError:
                pass
            
            if current_task and not current_task.done():
                is_interrupted = True
                current_task.cancel()
                try:
                    await current_task
                except (asyncio.CancelledError, Exception):
                    pass
                
            current_task = asyncio.create_task(process_llm(data))
            
    except WebSocketDisconnect:
        print("Client disconnected")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
