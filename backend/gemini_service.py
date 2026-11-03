"""
Google Gemini Cloud AI Integration for Igris Assistant.

Supports:
1. Gemini 2.0 Flash Multimodal Live API (Bidirectional WebSocket)
   - Real-time speech-to-speech with Google DeepMind neural voices (Aoede, Puck, Charon, Fenrir, Kore)
   - Sub-second latency (<800ms)
   - Native bidirectional tool calling (email, apps, media, shell)
   - Native conversational turn-taking & barge-in
2. Gemini 2.0 Flash REST/Streaming API for text chat & email summaries
3. Seamless fallback to local Ollama when offline or when no API key is provided
"""

import asyncio
import json
import os
import ssl
from typing import Any, AsyncGenerator, Callable, Optional
import httpx
import websockets

GEMINI_LIVE_HOST = "generativelanguage.googleapis.com"
GEMINI_LIVE_PATH = "/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
DEFAULT_MODEL = "models/gemini-2.0-flash-exp"
DEFAULT_VOICE = "Aoede"  # Warm, engaging, natural Google voice

AVAILABLE_VOICES = [
    {"id": "Aoede", "name": "Aoede", "desc": "Warm, natural & engaging (Default)"},
    {"id": "Puck", "name": "Puck", "desc": "Upbeat, energetic & clear"},
    {"id": "Charon", "name": "Charon", "desc": "Calm, thoughtful & deep"},
    {"id": "Fenrir", "name": "Fenrir", "desc": "Confident & authoritative"},
    {"id": "Kore", "name": "Kore", "desc": "Soft, calm & gentle"},
]

GEMINI_TOOLS_DECLARATION = [
    {
        "functionDeclarations": [
            {
                "name": "check_emails",
                "description": "Check the user's email inbox via IMAP for unread or recent messages.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "unread_only": {
                            "type": "BOOLEAN",
                            "description": "Set true to check only unread emails, false for recent emails",
                        },
                        "limit": {
                            "type": "INTEGER",
                            "description": "Maximum number of emails to return (default 6)",
                        },
                        "search_query": {
                            "type": "STRING",
                            "description": "Optional search term for sender, email address, or subject keyword",
                        },
                    },
                },
            },
            {
                "name": "read_email",
                "description": "Read the full body and attachments of an email by its UID or 1-based index from the latest inbox check.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "uid": {
                            "type": "STRING",
                            "description": "Email UID string",
                        },
                        "index": {
                            "type": "INTEGER",
                            "description": "1-based index number from the latest email list",
                        },
                    },
                },
            },
            {
                "name": "smart_open",
                "description": "Open an application or website on the user's computer (e.g. 'vscode', 'spotify', 'chrome', 'calculator', 'youtube.com', 'settings', 'terminal').",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "target": {
                            "type": "STRING",
                            "description": "The application name or website URL to open",
                        }
                    },
                    "required": ["target"],
                },
            },
            {
                "name": "play_music",
                "description": "Play a song, artist, or playlist on YouTube, Spotify, or YouTube Music.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "Song title or artist",
                        },
                        "platform": {
                            "type": "STRING",
                            "enum": ["youtube", "spotify", "youtube_music"],
                            "description": "Platform to play on (default youtube)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "control_media",
                "description": "Control currently playing media: play, pause, skip, next, or previous.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "action": {
                            "type": "STRING",
                            "enum": ["Play", "Pause", "PlayPause", "Next", "Previous"],
                            "description": "Media playback action",
                        }
                    },
                    "required": ["action"],
                },
            },
            {
                "name": "execute_command",
                "description": "Execute a safe terminal / shell command on the user's computer.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "command": {
                            "type": "STRING",
                            "description": "The shell command to execute",
                        }
                    },
                    "required": ["command"],
                },
            },
            {
                "name": "web_search",
                "description": "Search the web for real-time information, news, weather, or facts.",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {
                        "query": {
                            "type": "STRING",
                            "description": "The search query",
                        }
                    },
                    "required": ["query"],
                },
            },
        ]
    }
]

SYSTEM_INSTRUCTION = (
    "You are Igris, a real-time voice AI assistant inspired by Google Assistant. "
    "You communicate naturally, concisely, and directly. "
    "Keep spoken responses brief (1-3 sentences) suitable for voice. "
    "You have real tools that directly interact with the user's computer and email inbox. "
    "Always call tools immediately when the user asks to check emails, open apps, play music, "
    "run commands, or search the web. Never refuse to execute an action."
)


def get_ai_settings(db_conn, db_lock, mask_key: bool = True) -> dict[str, Any]:
    """Retrieve Cloud AI configuration from SQLite."""
    with db_lock:
        cur = db_conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = 'gemini_api_key'")
        r_key = cur.fetchone()
        raw_key = r_key[0] if r_key and r_key[0] else os.environ.get("GEMINI_API_KEY", "")

        cur.execute("SELECT value FROM settings WHERE key = 'ai_provider'")
        r_prov = cur.fetchone()
        provider = r_prov[0] if r_prov and r_prov[0] else ("gemini" if raw_key else "local")

        cur.execute("SELECT value FROM settings WHERE key = 'gemini_voice'")
        r_voice = cur.fetchone()
        voice = r_voice[0] if r_voice and r_voice[0] else DEFAULT_VOICE

        cur.execute("SELECT value FROM settings WHERE key = 'gemini_model'")
        r_model = cur.fetchone()
        model = r_model[0] if r_model and r_model[0] else "gemini-2.0-flash"

    has_key = bool(raw_key.strip())
    masked = ""
    if raw_key:
        if len(raw_key) > 8:
            masked = f"{raw_key[:4]}••••••••{raw_key[-4:]}"
        else:
            masked = "••••••••"

    return {
        "provider": provider,
        "has_key": has_key,
        "api_key": masked if mask_key else raw_key,
        "voice": voice,
        "model": model,
        "available_voices": AVAILABLE_VOICES,
    }


def save_ai_settings(
    db_conn,
    db_lock,
    provider: str,
    api_key: Optional[str] = None,
    voice: Optional[str] = None,
    model: Optional[str] = None,
) -> dict[str, Any]:
    """Persist Cloud AI configuration to SQLite."""
    with db_lock:
        cur = db_conn.cursor()
        cur.execute(
            "INSERT INTO settings (key, value) VALUES ('ai_provider', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (provider or "gemini",),
        )
        if api_key is not None and api_key != "":
            cur.execute(
                "INSERT INTO settings (key, value) VALUES ('gemini_api_key', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (api_key.strip(),),
            )
        if voice:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES ('gemini_voice', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (voice.strip(),),
            )
        if model:
            cur.execute(
                "INSERT INTO settings (key, value) VALUES ('gemini_model', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (model.strip(),),
            )
        db_conn.commit()

    return get_ai_settings(db_conn, db_lock, mask_key=True)


async def test_gemini_api_key(api_key: str) -> dict[str, Any]:
    """Test a Google Gemini API key by calling the models list API."""
    clean_key = (api_key or "").strip()
    if not clean_key:
        return {"ok": False, "message": "API key cannot be empty."}

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={clean_key}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                has_gemini = any("gemini" in m for m in models)
                return {
                    "ok": True,
                    "message": "Valid Gemini API Key! Cloud AI is ready to use.",
                    "models_count": len(models),
                }
            elif resp.status_code == 400:
                return {
                    "ok": False,
                    "message": "Invalid API key. Please check the key from Google AI Studio.",
                }
            else:
                return {
                    "ok": False,
                    "message": f"Gemini API returned status {resp.status_code}: {resp.text[:200]}",
                }
    except Exception as e:
        return {"ok": False, "message": f"Connection to Google Gemini failed: {e}"}


async def gemini_chat_stream(
    api_key: str,
    messages: list[dict[str, Any]],
    model: str = "gemini-2.0-flash",
) -> AsyncGenerator[str, None]:
    """Stream text tokens using Gemini 2.0 Flash REST SSE API (~200ms latency)."""
    clean_key = api_key.strip()
    clean_model = model.replace("models/", "")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{clean_model}:streamGenerateContent?key={clean_key}&alt=sse"

    # Convert OpenAI-style messages to Gemini contents format
    contents = []
    system_text = SYSTEM_INSTRUCTION
    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            system_text = content
            continue
        gemini_role = "user" if role in ("user", "tool") else "model"
        contents.append({"role": gemini_role, "parts": [{"text": str(content)}]})

    if not contents:
        contents = [{"role": "user", "parts": [{"text": "Hello"}]}]

    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_text}]},
        "generationConfig": {
            "temperature": 0.7,
            "maxOutputTokens": 2048,
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        async with client.stream("POST", url, json=payload) as resp:
            if resp.status_code != 200:
                err_text = await resp.aread()
                yield f"[Gemini Error {resp.status_code}: {err_text.decode('utf-8', errors='ignore')[:300]}]"
                return

            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if not data_str or data_str == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data_str)
                        cands = chunk.get("candidates", [])
                        if cands:
                            content = cands[0].get("content", {})
                            parts = content.get("parts", [])
                            for p in parts:
                                if "text" in p:
                                    yield p["text"]
                    except Exception:
                        continue


class GeminiLiveSession:
    """
    Manages a live bidirectional WebSocket session with Gemini 2.0 Flash Multimodal Live API.
    Streams 16kHz audio from Electron up to Gemini, and streams back 24kHz audio + tool calls.
    """

    def __init__(
        self,
        api_key: str,
        voice: str = DEFAULT_VOICE,
        model: str = DEFAULT_MODEL,
        tool_executor: Optional[Callable[[str, dict], Any]] = None,
        on_audio_out: Optional[Callable[[str], Any]] = None,
        on_text_out: Optional[Callable[[str], Any]] = None,
        on_interrupted: Optional[Callable[[], Any]] = None,
        on_turn_complete: Optional[Callable[[], Any]] = None,
    ):
        self.api_key = api_key.strip()
        self.voice = voice or DEFAULT_VOICE
        self.model = model or DEFAULT_MODEL
        self.tool_executor = tool_executor
        self.on_audio_out = on_audio_out
        self.on_text_out = on_text_out
        self.on_interrupted = on_interrupted
        self.on_turn_complete = on_turn_complete

        self._ws = None
        self._receive_task = None
        self._is_running = False

    @property
    def is_active(self) -> bool:
        return self._is_running and self._ws is not None

    async def start(self) -> bool:
        """Connect to Gemini Live WebSocket and send the initial setup message."""
        uri = f"wss://{GEMINI_LIVE_HOST}{GEMINI_LIVE_PATH}?key={self.api_key}"
        ssl_ctx = ssl.create_default_context()

        try:
            self._ws = await websockets.connect(
                uri,
                ssl=ssl_ctx,
                extra_headers={"Content-Type": "application/json"},
                ping_interval=20,
                ping_timeout=20,
            )
            self._is_running = True

            # 1. Send Setup message
            setup_payload = {
                "setup": {
                    "model": self.model,
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {
                                    "voiceName": self.voice
                                }
                            }
                        },
                    },
                    "systemInstruction": {
                        "parts": [{"text": SYSTEM_INSTRUCTION}]
                    },
                    "tools": GEMINI_TOOLS_DECLARATION,
                }
            }
            await self._ws.send(json.dumps(setup_payload))
            print(f"[GeminiLive] Connected to Gemini Live API with voice: {self.voice}")

            # 2. Start background receiver loop
            self._receive_task = asyncio.create_task(self._receiver_loop())
            return True
        except Exception as e:
            print(f"[GeminiLive] Connection failed: {e}")
            await self.stop()
            return False

    async def send_audio_chunk(self, base64_pcm_16k: str):
        """Send a chunk of 16kHz mono 16-bit linear PCM audio to Gemini."""
        if not self.is_active:
            return
        msg = {
            "realtimeInput": {
                "mediaChunks": [
                    {
                        "mimeType": "audio/pcm;rate=16000",
                        "data": base64_pcm_16k,
                    }
                ]
            }
        }
        try:
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            print(f"[GeminiLive] Error sending audio chunk: {e}")

    async def send_text_turn(self, text: str):
        """Send a typed text message to Gemini."""
        if not self.is_active:
            return
        msg = {
            "clientContent": {
                "turns": [
                    {
                        "role": "user",
                        "parts": [{"text": text}],
                    }
                ],
                "turnComplete": True,
            }
        }
        try:
            await self._ws.send(json.dumps(msg))
        except Exception as e:
            print(f"[GeminiLive] Error sending text: {e}")

    async def _receiver_loop(self):
        """Listen for audio chunks, text, tool calls, and interruptions from Gemini."""
        try:
            async for raw_msg in self._ws:
                try:
                    payload = json.loads(raw_msg)
                except Exception:
                    continue

                # 1. Handle tool calls from Gemini
                if "toolCall" in payload:
                    tool_call = payload["toolCall"]
                    function_calls = tool_call.get("functionCalls", [])
                    responses = []

                    for fc in function_calls:
                        call_id = fc.get("id")
                        name = fc.get("name")
                        args = fc.get("args", {})
                        print(f"[GeminiLive] Tool call: {name} (ID: {call_id})")

                        result_output = "Done"
                        if self.tool_executor:
                            try:
                                res = self.tool_executor(name, args)
                                if asyncio.iscoroutine(res):
                                    res = await res
                                result_output = str(res)
                            except Exception as ex:
                                result_output = f"Tool execution failed: {ex}"

                        responses.append({
                            "id": call_id,
                            "response": {"output": result_output},
                        })

                    # Send tool response back to Gemini
                    tool_resp_msg = {
                        "toolResponse": {
                            "functionResponses": responses
                        }
                    }
                    await self._ws.send(json.dumps(tool_resp_msg))
                    print(f"[GeminiLive] Sent tool response for {len(responses)} call(s)")
                    continue

                # 2. Handle model output content (Audio & Text)
                if "serverContent" in payload:
                    sc = payload["serverContent"]

                    if sc.get("interrupted"):
                        print("[GeminiLive] User interrupted assistant")
                        if self.on_interrupted:
                            res = self.on_interrupted()
                            if asyncio.iscoroutine(res):
                                await res

                    model_turn = sc.get("modelTurn", {})
                    parts = model_turn.get("parts", [])
                    for part in parts:
                        # Raw audio PCM bytes (24kHz)
                        inline_data = part.get("inlineData", {})
                        if inline_data and "data" in inline_data:
                            b64_audio = inline_data["data"]
                            if self.on_audio_out:
                                res = self.on_audio_out(b64_audio)
                                if asyncio.iscoroutine(res):
                                    await res

                        # Text tokens (if returned)
                        if "text" in part:
                            txt = part["text"]
                            if self.on_text_out:
                                res = self.on_text_out(txt)
                                if asyncio.iscoroutine(res):
                                    await res

                    if sc.get("turnComplete"):
                        if self.on_turn_complete:
                            res = self.on_turn_complete()
                            if asyncio.iscoroutine(res):
                                await res

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[GeminiLive] Session closed: {e}")
        except Exception as e:
            print(f"[GeminiLive] Receiver error: {e}")
        finally:
            self._is_running = False

    async def stop(self):
        """Gracefully disconnect the session."""
        self._is_running = False
        if self._receive_task:
            self._receive_task.cancel()
            self._receive_task = None
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        print("[GeminiLive] Session stopped.")

