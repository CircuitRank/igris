import asyncio
import json
import httpx
import subprocess
import sqlite3
import psutil
import re
import threading
import struct
import wave
import tempfile
import urllib.request
import urllib.parse
from contextlib import asynccontextmanager
from faster_whisper import WhisperModel
import os
import sys
import platform
import shutil
import glob
import mss
import base64
from ddgs import DDGS
import fitz  # PyMuPDF
import edge_tts
import speech_recognition as sr
from pydub import AudioSegment
import torch
import torchaudio
import df_compat  # Patch torchaudio for DeepFilterNet compatibility (must be before df imports)
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

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
db_lock = threading.Lock()

# Initialize Whisper (Handle offline error gracefully)
whisper_model = None

# Initialize DeepFilterNet for noise suppression
df_model = None
df_state = None

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

def index_installed_apps():
    apps = {}
    if CURRENT_OS == "Linux":
        app_dirs = ["/usr/share/applications", os.path.expanduser("~/.local/share/applications"), "/var/lib/snapd/desktop/applications"]
        for d in app_dirs:
            if not os.path.exists(d): continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith(".desktop"):
                        try:
                            with open(os.path.join(root, f), 'r', encoding='utf-8') as df:
                                content = df.read()
                                name_match = re.search(r'^Name=(.*)$', content, re.MULTILINE)
                                exec_match = re.search(r'^Exec=(.*)$', content, re.MULTILINE)
                                if name_match and exec_match:
                                    name = name_match.group(1).strip()
                                    cmd = exec_match.group(1).strip().split(' %')[0]
                                    apps[name.lower()] = {"name": name, "cmd": cmd}
                        except: pass
    elif CURRENT_OS == "Windows":
        app_dirs = [
            os.path.join(os.environ.get("ProgramData", "C:\\ProgramData"), "Microsoft\\Windows\\Start Menu\\Programs"),
            os.path.join(os.environ.get("APPDATA", ""), "Microsoft\\Windows\\Start Menu\\Programs")
        ]
        for d in app_dirs:
            if not os.path.exists(d): continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith(".lnk"):
                        name = f[:-4]
                        path = os.path.join(root, f)
                        cmd = f'start "" "{path}"'
                        apps[name.lower()] = {"name": name, "cmd": cmd}
    elif CURRENT_OS == "Darwin":
        app_dirs = ["/Applications", "/System/Applications", os.path.expanduser("~/Applications")]
        for d in app_dirs:
            if not os.path.exists(d): continue
            for app in os.listdir(d):
                if app.endswith(".app"):
                    name = app[:-4]
                    cmd = f"open '{os.path.join(d, app)}'"
                    apps[name.lower()] = {"name": name, "cmd": cmd}
    
    with db_lock:
        cursor.execute("CREATE TABLE IF NOT EXISTS apps (id INTEGER PRIMARY KEY, name TEXT, cmd TEXT)")
        cursor.execute("DELETE FROM apps")
        for k, v in apps.items():
            cursor.execute("INSERT INTO apps (name, cmd) VALUES (?, ?)", (v['name'].lower(), v['cmd']))
        db_conn.commit()
    print(f"[SYSTEM] Indexed {len(apps)} applications.")

@asynccontextmanager
async def lifespan(app):
    """Application lifespan: startup and shutdown events."""
    def _load():
        global whisper_model, df_model, df_state
        def is_model_cached(model_name):
            """Check if a faster-whisper model is already downloaded."""
            cache_dir = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "hub")
            repo_dir = os.path.join(cache_dir, f"models--Systran--faster-whisper-{model_name}")
            return os.path.exists(repo_dir)

        # Load DeepFilterNet for noise suppression
        try:
            print("[SYSTEM] Loading DeepFilterNet model...")
            from df.enhance import init_df
            df_model, df_state, _ = init_df()
            print(f"[SYSTEM] ✓ DeepFilterNet loaded (sample rate: {df_state.sr()}Hz)")
        except Exception as e:
            print(f"[SYSTEM] DeepFilterNet failed to load: {e}")
            print("[SYSTEM] Audio denoising will be disabled.")
            df_model = None
            df_state = None

        try:
            print("[SYSTEM] Loading Whisper model in background...")
            # Try models in order of quality — only use already-cached models
            for model_name in ["large-v3", "medium.en", "small.en"]:
                if not is_model_cached(model_name):
                    print(f"[SYSTEM] Model '{model_name}' not cached, skipping...")
                    continue
                try:
                    whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
                    print(f"[SYSTEM] ✓ Whisper model '{model_name}' loaded successfully.")
                    break
                except Exception as e:
                    print(f"[SYSTEM] Model '{model_name}' failed to load: {e}")
                    continue
            else:
                print("[SYSTEM] No Whisper model cached! Voice will use Google fallback.")
                whisper_model = None
        except Exception as e:
            print(f"[SYSTEM] Failed to initialize WhisperModel: {e}")
            whisper_model = None

        index_installed_apps()

    threading.Thread(target=_load, daemon=True).start()
    yield
    # Shutdown: close database connection
    db_conn.close()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8000", "http://localhost:8000", "file://", "null"],
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
    if not is_command_safe(cmd):
        return f"Command blocked for safety: '{cmd}' matches a dangerous pattern."
    try:
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
# Safety Guards for Command and File Access
# ============================================================

DANGEROUS_COMMAND_PATTERNS = [
    r'rm\s+(-[a-zA-Z]*\s+)?/',
    r'mkfs\.',
    r'dd\s+.*of=/dev/',
    r'>\s*/dev/sd',
    r'format\s+[a-zA-Z]:',
    r'del\s+/[sS]',
    r'curl\s+.*\|\s*(bash|sh|zsh)',
    r'wget\s+.*\|\s*(bash|sh|zsh)',
    r'\bshutdown\b',
    r'\breboot\b',
    r'\binit\s+[06]\b',
    r'\bpoweroff\b',
    r':\(\)\s*\{',
    r'chmod\s+(-[a-zA-Z]*\s+)?777\s+/',
]

RESTRICTED_PATHS = ['.ssh', '.gnupg', '.aws', '.config/gcloud', '.kube']
SENSITIVE_SYSTEM_PATHS = ['/etc/shadow', '/etc/sudoers', '/etc/gshadow']


def is_command_safe(cmd: str) -> bool:
    """Check if a command is safe to execute. Blocks known destructive patterns."""
    for pattern in DANGEROUS_COMMAND_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return False
    return True


def is_path_safe(filepath: str) -> bool:
    """Check if a file path is safe to access. Blocks sensitive directories."""
    abs_path = os.path.abspath(os.path.expanduser(filepath))
    home = os.path.expanduser("~")
    for restricted in RESTRICTED_PATHS:
        restricted_full = os.path.join(home, restricted)
        if abs_path.startswith(restricted_full):
            return False
    for sensitive in SENSITIVE_SYSTEM_PATHS:
        if abs_path.startswith(sensitive):
            return False
    return True


# ============================================================
# Tool Definitions — descriptions made more explicit for the LLM
# ============================================================

TOOLS = [{
    "type": "function",
    "function": {
        "name": "smart_open",
        "description": "Smart open tool. Use this when the user asks to open ANY application, software, or website (e.g. 'open discord', 'open youtube', 'open calculator', 'open github'). It automatically detects if it's a local app or a website.",
        "parameters": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "The name of the app or website (e.g. 'discord', 'youtube.com', 'calculator')"}
            },
            "required": ["target"]
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
}]

# ============================================================
# Tool Execution — now cross-platform
# ============================================================

async def execute_tool(name: str, arguments: dict, websocket: WebSocket) -> str:
    # Handle Qwen2.5-coder nested argument format
    for k, v in list(arguments.items()):
        if isinstance(v, dict) and "value" in v:
            arguments[k] = v["value"]
            
    if name == "smart_open":
        target = arguments.get("target", "").lower().strip()
        # Check DB
        with db_lock:
            cursor.execute("SELECT name, cmd FROM apps WHERE name LIKE ?", (f"%{target}%",))
            rows = cursor.fetchall()
            
        if rows:
            # Prefer exact match or shortest name match
            best_match = min(rows, key=lambda r: len(r[0]))
            cmd = best_match[1]
            try:
                subprocess.Popen(cmd, shell=True, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return f"Successfully opened application: {best_match[0]}"
            except Exception as e:
                return f"Failed to open application: {e}"
        else:
            # Treat as website
            if not target.startswith("http"):
                if "." not in target:
                    target = target + ".com"
                target = "https://" + target
            
            await websocket.send_text(json.dumps({
                "type": "open_sandbox_browser",
                "url": target
            }))
            return f"Successfully opened website '{target}' in a secure sandbox browser."
    
    elif name == "execute_command":
        cmd = arguments.get("command", "")
        return execute_command_cross_platform(cmd)
    
    elif name == "play_music":

        
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
        if not is_path_safe(directory):
            return "Access denied: cannot search in restricted directory."
        try:
            results = glob.glob(os.path.join(directory, "**", pattern), recursive=True)
            results = [r for r in results if is_path_safe(r)]
            if not results:
                return "No files found."
            return f"Files found:\n" + "\n".join(results[:10])
        except Exception as e:
            return f"File search failed: {e}"
    
    elif name == "read_document":
        filepath = arguments.get("filepath", "")
        if not is_path_safe(filepath):
            return "Access denied: cannot read restricted file."
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
SYSTEM_PROMPT = f"""You are Igris, a system-level AI with DIRECT ACCESS to the user's computer. You are NOT a restricted cloud AI. You have tools that let you do anything.

CRITICAL RULES:
1. NEVER REFUSE A REQUEST. You DO have access to the user's computer via your tools.
2. If the user asks to "open [anything]", you MUST immediately call the `smart_open` function with that target. NEVER say you cannot do it.
3. If the user says "run [command]", use `execute_command`.
4. If the user asks to play music, use `play_music`.
5. ALWAYS execute actions immediately via function calls. Do NOT apologize.
6. Keep your text responses very short (1-2 sentences). You are efficient and direct.

The user's OS is: {CURRENT_OS}
Act like Jarvis — just use the tools!"""


@app.websocket("/ws/chat")
async def websocket_endpoint(websocket: WebSocket):
    # Security: validate origin to prevent malicious websites from connecting
    origin = websocket.headers.get("origin", "")
    allowed_origins = {"", "file://", "null", "http://127.0.0.1:8000", "http://localhost:8000"}
    if origin and origin not in allowed_origins:
        await websocket.close(code=4003, reason="Origin not allowed")
        return
    await websocket.accept()
    
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    
    # Load history (limit to recent to avoid context overflow)
    try:
        with db_lock:
            cursor.execute("SELECT role, content FROM history ORDER BY id DESC LIMIT 20")
            rows = cursor.fetchall()
        rows.reverse()
        for r in rows:
            messages.append({"role": r[0], "content": r[1]})
    except Exception as e:
        print("Error loading history:", e)
    
    current_task = None
    is_interrupted = False
    

    
    recognizer = sr.Recognizer()
    
    def check_audio_energy(wav_path, threshold=60):
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
            
            # DeepFilterNet noise suppression — runs at 48kHz
            if df_model is not None and df_state is not None:
                try:
                    from df.enhance import enhance
                    import numpy as np
                    # Convert pydub audio to 48kHz mono for DeepFilterNet
                    audio_48k = audio.set_frame_rate(48000).set_channels(1)
                    
                    # pydub AudioSegment → numpy float32 → torch tensor [1, T]
                    samples = np.array(audio_48k.get_array_of_samples(), dtype=np.float32)
                    samples /= 32768.0  # int16 → float32 normalized to [-1, 1]
                    noisy_tensor = torch.from_numpy(samples).unsqueeze(0)  # [1, T]
                    
                    # Denoise
                    enhanced_tensor = enhance(df_model, df_state, noisy_tensor)
                    
                    # torch tensor → numpy int16 → pydub AudioSegment
                    enhanced_np = (enhanced_tensor.squeeze(0).numpy() * 32768.0).clip(-32768, 32767).astype(np.int16)
                    audio = AudioSegment(
                        data=enhanced_np.tobytes(),
                        sample_width=2,  # 16-bit
                        frame_rate=48000,
                        channels=1,
                    )
                    print("[DENOISE] ✓ Audio denoised with DeepFilterNet")
                except Exception as e:
                    print(f"[DENOISE] DeepFilterNet processing failed, using raw audio: {e}")
            
            # Resample to 16kHz mono — Whisper's native sample rate for best accuracy
            audio = audio.set_frame_rate(16000).set_channels(1)
            audio.export(temp_wav_path, format="wav")
            
            # Check audio energy — reject if it's just noise
            if not check_audio_energy(temp_wav_path):
                return None
            
            # Transcribe with faster-whisper or fallback
            if whisper_model is not None:
                segments, info = whisper_model.transcribe(
                    temp_wav_path,
                    language="en",  # Force English — prevents misdetection on short clips
                    beam_size=5,
                    best_of=3,
                    vad_filter=True,
                    vad_parameters=dict(
                        min_silence_duration_ms=300,
                        speech_pad_ms=200,
                    )
                )
                transcribed_text = " ".join([segment.text for segment in segments]).strip()
            else:
                print("[STT] Whisper model still loading, using Google fallback...")
                try:
                    with sr.AudioFile(temp_wav_path) as source:
                        audio_data = recognizer.record(source)
                        transcribed_text = recognizer.recognize_google(audio_data)
                except sr.UnknownValueError:
                    print("[STT] Google could not understand the audio")
                    transcribed_text = None
                except sr.RequestError as e:
                    print(f"[STT] Google API request failed: {e}")
                    transcribed_text = None
                except Exception as e:
                    print(f"[STT] Google fallback error: {e}")
                    transcribed_text = None
            
            if not transcribed_text:
                return None
                
            # Filter hallucinations
            if is_whisper_hallucination(transcribed_text):
                return None
            
            return transcribed_text
            
        finally:
            for p in [temp_webm_path, temp_wav_path]:
                if p and os.path.exists(p):
                    try:
                        os.remove(p)
                    except OSError:
                        pass
    
    async def try_direct_command(user_text):
        """Intercept obvious commands and execute them directly, bypassing the LLM."""
        # Strip punctuation and normalize — Whisper often adds periods, commas, etc.
        text = re.sub(r'[.,!?;:"\']', '', user_text).strip().lower()
        
        # Strip wakewords and their common mistranscriptions first so they don't block the command
        wakewords = r'^(hey |hi |hello |yo )?(igris|grinch|iris|aegis|egris|igress|tigris)\b\s*,?\s*'
        text = re.sub(wakewords, '', text).strip()
        
        # Strip filler words Whisper sometimes adds
        text = re.sub(r'^(hey |okay |so |um |uh |well |please )+', '', text).strip()

        # Fix common Whisper mistranscriptions (now that filler/wakewords are stripped)
        whisper_fixes = {
            r'^on\b': 'open',          # "on YouTube" → "open YouTube"
            r'^upon\b': 'open',        # "upon chrome" → "open chrome"  
            r'^oh pen\b': 'open',      # "oh pen" → "open"
            r'^than\b': 'open',        # "than YouTube" → "open YouTube"
            r'^lunch\b': 'launch',     # "lunch discord" → "launch discord"
            r'^place\b': 'play',       # "place music" → "play music"
        }
        for pattern, replacement in whisper_fixes.items():
            text = re.sub(pattern, replacement, text)
        
        # "open X" commands
        open_patterns = [
            r'^(?:open|launch|start|run)\s+(.+?)(?:\s+(?:app|application|please|for me))?$',
            r'^(?:can you |could you |please )?(?:open|launch|start)\s+(.+?)(?:\s+(?:please|for me))?$',
        ]
        for pattern in open_patterns:
            match = re.match(pattern, text)
            if match:
                target = match.group(1).strip()
                result = await execute_tool("smart_open", {"target": target}, websocket)
                return result
        
        # "play X" commands  
        play_match = re.match(r'^(?:play|put on)\s+(.+?)(?:\s+on\s+(spotify|youtube|youtube music))?$', text)
        if play_match:
            query = play_match.group(1).strip()
            platform = play_match.group(2) or "youtube"
            platform = platform.replace(" ", "_")
            result = await execute_tool("play_music", {"query": query, "platform": platform}, websocket)
            return result
        
        # "search for X" commands
        search_match = re.match(r'^(?:search|google|look up|search for|what is|who is|what are)\s+(.+)$', text)
        if search_match:
            query = search_match.group(1).strip()
            result = await execute_tool("web_search", {"query": query}, websocket)
            return result
        
        # Media control
        media_map = {
            "pause": "Pause", "stop": "Pause", "resume": "Play",
            "next": "Next", "next song": "Next", "skip": "Next",
            "previous": "Previous", "prev": "Previous", "go back": "Previous",
        }
        if text in media_map:
            result = await execute_tool("control_media", {"action": media_map[text]}, websocket)
            return result
        
        return None  # Not a direct command, let the LLM handle it

    async def process_llm(user_text, is_voice=False):
        nonlocal is_interrupted
        is_interrupted = False
        
        # Try direct command execution first (bypasses LLM for reliability)
        direct_result = await try_direct_command(user_text)
        if direct_result:
            messages.append({"role": "user", "content": user_text})
            messages.append({"role": "assistant", "content": direct_result})
            with db_lock:
                cursor.execute("INSERT INTO history (role, content) VALUES (?, ?)", ("user", user_text))
                cursor.execute("INSERT INTO history (role, content) VALUES (?, ?)", ("assistant", direct_result))
                db_conn.commit()
            
            await websocket.send_text(json.dumps({"type": "stream_start"}))
            await websocket.send_text(json.dumps({"type": "stream_chunk", "content": direct_result}))
            await websocket.send_text(json.dumps({"type": "stream_end"}))
            
            # TTS for voice mode
            if is_voice and not is_interrupted:
                try:
                    text_to_speak = direct_result.replace('*', '')
                    await websocket.send_text(json.dumps({"type": "speaking_start"}))
                    communicate = edge_tts.Communicate(text_to_speak, "en-US-ChristopherNeural")
                    audio_data = b""
                    async for ac in communicate.stream():
                        if is_interrupted: break
                        if ac["type"] == "audio":
                            audio_data += ac["data"]
                    if audio_data and not is_interrupted:
                        b64_audio = base64.b64encode(audio_data).decode('utf-8')
                        await websocket.send_text(json.dumps({"type": "audio", "data": b64_audio}))
                    await websocket.send_text(json.dumps({"type": "speaking_end"}))
                except Exception as e:
                    print(f"TTS Error: {e}")
            return
        
        messages.append({"role": "user", "content": user_text})
        with db_lock:
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
                                            result_text = await execute_tool(name, arguments, websocket)
                                            messages.append({"role": "tool", "content": result_text})
                                            
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
                            result_text = await execute_tool(name, arguments, websocket)
                            messages.append({"role": "tool", "content": result_text})
                            
                            tool_call_count += 1
                            continue 
                        except Exception as e:
                            messages.append({"role": "assistant", "content": response_content.strip()})
                            messages.append({"role": "tool", "content": f"Tool execution failed: {e}"})
                            tool_call_count += 1
                            continue
                    else:
                        messages.append({"role": "assistant", "content": response_content.strip()})
                        with db_lock:
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
                            # Notify frontend so it exits SPEAKING state
                            await websocket.send_text(json.dumps({"type": "interrupted"}))
                            await websocket.send_text(json.dumps({"type": "speaking_end"}))
                            await websocket.send_text(json.dumps({"type": "stream_end"}))
                        
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

                elif parsed_data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
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
