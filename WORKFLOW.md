# Operational Workflow & System Execution Guide for Igris

This document details the operational execution flows, component data paths, message protocols, and lifecycle sequences across **Igris**.

![Igris System Workflow Diagram](workflow_diagram.png)

---

## 1. End-to-End System Topology

```mermaid
flowchart TD
    subgraph UserInterface["Electron Client Layer"]
        DOM["Notion UI (index.html)"]
        Renderer["Renderer Process (renderer.js)"]
        WebAudio["Web Audio API Context"]
        WaveVis["Google 4-Color Wave Visualizer"]
        SidePeek["Email Side Peek Drawer"]
    end

    subgraph IPCBridge["Desktop Bridge"]
        Preload["Preload API (preload.js)"]
        MainProcess["Main Process (main.js)"]
    end

    subgraph PythonBackend["FastAPI Backend Layer (main.py)"]
        Uvicorn["Uvicorn Server (:8000)"]
        WSText["WebSocket: /ws (Text & Offline Audio)"]
        WSLive["WebSocket: /ws/live (Gemini Live Stream)"]
        REST["REST API Endpoints"]
        ToolRouter["Tool Execution Hub"]
        SQLite[("SQLite: igris_memory.db")]
    end

    subgraph ExternalIntelligence["Intelligence Providers"]
        GeminiWSS["Google Gemini 2.0 Live (WSS)"]
        OllamaLocal["Local Ollama (:11434)"]
        WhisperLocal["Faster-Whisper (CTranslate2)"]
        IMAPServer["IMAP Mail Server (SSL/993)"]
    end

    DOM --> Renderer
    Renderer --> WebAudio
    Renderer --> WaveVis
    Renderer --> SidePeek
    Renderer --> Preload
    Preload --> MainProcess

    Renderer <-->|Raw 16k/24k PCM WS| WSLive
    Renderer <-->|JSON Events & WebM| WSText
    Renderer <-->|Fetch Requests| REST

    WSLive <-->|BidiGenerateContent| GeminiWSS
    WSText --> WhisperLocal
    WSText --> OllamaLocal
    ToolRouter <--> REST
    ToolRouter <--> SQLite
    ToolRouter <--> IMAPServer
```

---

## 2. Bootstrapping & Lifecycle Initialization Workflow

The system initializes via platform-specific bootstrap scripts (`start.sh` on Linux/macOS, `start.bat` on Windows).

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Script as Bootstrapper (start.sh / start.bat)
    participant Venv as Python Virtual Environment
    participant Backend as FastAPI Server (:8000)
    participant Electron as Electron Framework
    participant Renderer as Renderer UI (renderer.js)

    User->>Script: Run startup command
    Script->>Venv: Activate Python venv & verify dependencies
    Script->>Backend: Spawn uvicorn backend in background
    Script->>Backend: Health check probe (GET http://127.0.0.1:8000/)
    Backend-->>Script: 200 OK (Whisper & DB initialized)
    Script->>Electron: Launch Electron (npm start)
    Electron->>Renderer: Load index.html & execute preload.js
    Renderer->>Backend: GET /api/ai/settings (Sync AI state)
    Backend-->>Renderer: Return active provider, voice, API key presence
    Renderer->>Backend: GET /api/email/settings (Check email connection)
    Backend-->>Renderer: Return connection status & unread count
    Renderer->>Backend: Connect WebSocket (/ws)
    Backend-->>Renderer: Connection acknowledged
    Renderer->>User: Display active Notion workspace
```

### Step-by-Step Initialization Trace
1. **Host Environment Check**: Startup script verifies Python $\ge$ 3.10 and Node.js $\ge$ 18.
2. **Backend Instantiation**: Python virtual environment activated; `main.py` starts with SQLite connection initialized and table migrations executed (`conversations`, `messages`, `memory_facts`, `settings`).
3. **Model Warmup**: If local offline mode is active, Faster-Whisper loads acoustic weights into CPU/CUDA memory.
4. **Electron Launch**: Main window opens at $1200\times800$ resolution with a custom dark frame (`#191919`).
5. **State Synchronization**:
   - `loadAiSettings()` queries `/api/ai/settings`. Sets `aiState.hasKey` and configures Gemini voice selection.
   - `loadEmailSettings()` queries `/api/email/settings`. Updates sidebar unread count.
   - `connectWebSocket()` establishes the base `/ws` connection.

---

## 3. Real-Time Google Voice Assistant Workflow (Cloud Live Mode)

When configured with a Google Gemini API key, Igris provides sub-second speech-to-speech with Google DeepMind neural voices and native barge-in.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Mic as Client Microphone
    participant Renderer as renderer.js (Web Audio)
    participant LiveWS as Backend (/ws/live)
    participant Gemini as Gemini 2.0 Live API
    participant Speaker as Audio Output

    User->>Renderer: Click Mic / Hold Spacebar
    Renderer->>Renderer: Open Voice Overlay (4-color wave listening state)
    Renderer->>LiveWS: Open WebSocket /ws/live
    LiveWS->>Gemini: Establish WSS connection & send setup handshake
    Gemini-->>LiveWS: Setup complete confirmation

    loop Bidirectional Streaming Loop
        Mic->>Renderer: Raw PCM (48kHz Float32)
        Renderer->>Renderer: Downsample to 16kHz Int16 linear PCM
        Renderer->>LiveWS: Send {"realtime_input": {"audio": base64}}
        LiveWS->>Gemini: Forward audio chunk

        Gemini-->>LiveWS: Stream 24kHz linear PCM chunks
        LiveWS-->>Renderer: Stream audio frames
        Renderer->>Speaker: Schedule onto AudioContext buffer queue
        Renderer->>Renderer: Animate Google wave (speaking state)
    end

    opt User Interrupts Assistant (Barge-In)
        User->>Mic: Speaks while assistant is speaking
        Renderer->>Renderer: VAD detects voice energy > threshold
        Renderer->>Speaker: Stop active audio sources & clear queue
        Renderer->>LiveWS: Transmit turn cancellation signal
        LiveWS->>Gemini: Flush current model turn
        Renderer->>Renderer: Switch Google wave immediately to listening
    end
```

### Audio Chunk Conversion & Scheduling Detail
1. **Capture**: `navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } })`.
2. **Resampling Node**: `ScriptProcessorNode` (buffer size: 4096) accumulates samples, applies downsampling interpolation to 16,000 Hz, and packs into 16-bit linear PCM format.
3. **Dispatch**: Encoded to base64 and pushed over `/ws/live` every 100ms.
4. **Playback Queue**:
   ```javascript
   function playPcmChunk(int16Data) {
       const float32 = new Float32Array(int16Data.length);
       for (let i = 0; i < int16Data.length; i++) {
           float32[i] = int16Data[i] / 32768.0;
       }
       const audioBuffer = liveAudioCtx.createBuffer(1, float32.length, 24000);
       audioBuffer.getChannelData(0).set(float32);
       const source = liveAudioCtx.createBufferSource();
       source.buffer = audioBuffer;
       source.connect(liveAudioCtx.destination);
       const startTime = Math.max(liveAudioCtx.currentTime, pcmScheduledTime);
       source.start(startTime);
       pcmScheduledTime = startTime + audioBuffer.duration;
   }
   ```

---

## 4. Local Voice Assistant Workflow (Offline Fallback Mode)

When operating offline or without an API key, Igris automatically falls back to the local inference pipeline.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Mic as Client Microphone (VAD)
    participant Renderer as renderer.js
    participant WS as Backend (/ws)
    participant Whisper as Faster-Whisper
    participant Ollama as Ollama (qwen2.5-coder:3b)
    participant TTS as Edge-TTS / PyTTSx3
    participant Speaker as Audio Output

    User->>Mic: Speaks prompt ("What time is it?")
    Mic->>Renderer: Capture audio chunks (WebM format)
    Renderer->>Renderer: VAD detects 1.8s silence
    Renderer->>WS: Send {"type": "voice_input", "data": base64_webm}
    WS->>Whisper: Transcribe audio buffer
    Whisper-->>WS: Return text: "What time is it?"
    WS-->>Renderer: Send {"type": "transcript", "text": "What time is it?"}
    WS->>Ollama: Generate completion with memory facts
    Ollama-->>WS: Stream response tokens
    WS->>TTS: Convert text sentence to speech
    TTS-->>WS: Output MP3/WAV audio bytes
    WS-->>Renderer: Send {"type": "voice_chunk", "audio": base64_audio}
    Renderer->>Speaker: Play synthesized audio chunk
```

---

## 5. Text Chat & Natural Language Tool Execution Workflow

When the user interacts via text or when an incoming voice prompt requires external system interaction, the tool execution loop runs.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant UI as Notion Chat View
    participant Backend as FastAPI Server
    participant LLM as Gemini / Ollama
    participant Tools as Tool Execution Hub (main.py)
    participant Host as Operating System / Apps

    User->>UI: Type: "Open VS Code and check my unread emails"
    UI->>Backend: Dispatch prompt via WebSocket
    Backend->>LLM: Ingest prompt with tool declarations:
    Note over LLM: Tools: open_app, execute_command,<br/>media_control, check_unread_emails...
    LLM-->>Backend: Emit tool_call: open_app(app_name="vscode")
    Backend->>Tools: execute_tool("open_app", {"app_name": "vscode"})
    Tools->>Host: Execute OS launch command (e.g. `code`)
    Host-->>Tools: Success
    Tools-->>Backend: Tool result: {"status": "success", "message": "VS Code launched"}
    Backend->>LLM: Emit tool_response: result data
    LLM-->>Backend: Emit tool_call: check_unread_emails(limit=5)
    Backend->>Tools: execute_tool("check_unread_emails", {"limit": 5})
    Tools->>Host: IMAP query over SSL:993
    Host-->>Tools: 2 unread emails returned
    Tools-->>Backend: Tool result: [{"from": "Alice", "subject": "Design Review"}]
    Backend->>LLM: Emit tool_response: email summary data
    LLM-->>Backend: Stream natural language summary response
    Backend-->>UI: Stream markdown tokens to chat canvas
    UI->>User: Display response and tool execution pills
```

### Available System Tools
- `open_app(app_name)`: Launches applications (`vscode`, `chrome`, `spotify`, `settings`, `terminal`, etc.) using platform-specific commands.
- `execute_command(command)`: Executes shell commands with a 15-second safety timeout.
- `media_control(action)`: Controls system media playback (`play`, `pause`, `next`, `prev`).
- `web_search(query)`: Executes DuckDuckGo searches and returns synthesized snippets.
- `analyze_screen(prompt)`: Captures desktop displays via `mss` and submits screenshots to the vision pipeline.
- `check_unread_emails(limit)`: Retrieves unread emails from the connected IMAP account.
- `read_email_content(uid)`: Fetches and parses full headers and body for a specific email.
- `summarize_inbox()`: Compiles an AI executive summary of recent inbox correspondence.

---

## 6. Integrated Email Workspace Workflow

Igris provides a Notion-style email database table with an interactive side peek drawer and AI-assisted summaries.

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant InboxView as Inbox Database View (index.html)
    participant Renderer as renderer.js
    participant REST as Backend REST API
    participant EmailSvc as email_service.py
    participant IMAP as Mail Provider (IMAP SSL:993)
    participant LLM as Gemini / Ollama

    User->>InboxView: Click "Inbox" in sidebar
    InboxView->>Renderer: Trigger loadInbox()
    Renderer->>REST: GET /api/email/messages?limit=25&unread_only=false
    REST->>EmailSvc: fetch_inbox_messages()
    EmailSvc->>IMAP: IMAP search & fetch headers
    IMAP-->>EmailSvc: Return RFC 822 / 2047 raw headers
    EmailSvc->>EmailSvc: Decode MIME subjects & strip tracking tags
    EmailSvc-->>REST: Normalized message list
    REST-->>Renderer: JSON message payload
    Renderer->>InboxView: Render Notion database rows & badges

    opt User Inspects Email (Side Peek)
        User->>InboxView: Click email row
        InboxView->>Renderer: Trigger openPeek(uid)
        Renderer->>REST: GET /api/email/messages/{uid}
        REST->>EmailSvc: fetch_message_by_uid(uid)
        EmailSvc->>IMAP: Fetch raw RFC 822 body
        EmailSvc-->>REST: Full body & attachment metadata
        REST-->>Renderer: Message details
        Renderer->>InboxView: Slide open side peek drawer
    end

    opt User Requests AI Summary
        User->>InboxView: Click "Summarize Inbox"
        InboxView->>Renderer: Trigger summarizeInbox()
        Renderer->>REST: POST /api/email/summarize
        REST->>EmailSvc: Fetch unread messages
        EmailSvc-->>REST: List of message payloads
        REST->>LLM: Generate executive bulleted digest
        LLM-->>REST: Markdown summary
        REST-->>Renderer: Return summary text
        Renderer->>InboxView: Display formatted summary callout
    end
```

---

## 7. Settings, Configuration & Error Recovery Workflows

Igris isolates configuration into a tabbed modal accessible via `Ctrl + ,` or the sidebar button.

```mermaid
flowchart TD
    OpenSettings["User Opens Settings (Ctrl + ,)"] --> SelectTab{"Select Tab"}

    SelectTab -->|Cloud AI| AITab["Cloud AI Settings"]
    AITab --> InputKey["Input Google AI Studio Key"]
    InputKey --> SelectVoice["Select Voice (Aoede, Puck, Charon, Fenrir, Kore)"]
    SelectVoice --> TestAI["Click 'Test API Key'"]
    TestAI --> ValidateAI["POST /api/ai/test"]
    ValidateAI -->|Success| SaveAI["POST /api/ai/settings"]
    ValidateAI -->|Invalid Key| ErrorAI["Display Inline Warning"]

    SelectTab -->|Email| EmailTab["Email Settings"]
    EmailTab --> SelectProvider["Select Provider (Gmail, Outlook, iCloud, Yahoo, Custom)"]
    SelectProvider --> EnterCreds["Enter Email & 16-Char App Password"]
    EnterCreds --> TestIMAP["Click 'Test Connection'"]
    TestIMAP --> ValidateIMAP["POST /api/email/test"]
    ValidateIMAP -->|Success| SaveIMAP["POST /api/email/settings"]
    ValidateIMAP -->|Refused / Auth Fail| ErrorIMAP["Display Help Link & Error"]

    SelectTab -->|Voice & Audio| VoiceTab["Toggle Speak Responses / Interaction Mode"]
    SelectTab -->|Data| DataTab["Clear Chat History & SQLite Memory"]
```

### Error Recovery Pathways
1. **Network Disconnection in Live Voice Mode**:
   - If `/ws/live` disconnects, the frontend automatically falls back to local voice processing without crashing the session.
   - An alert toast informs the user: *"Live voice session closed. Switched to offline mode."*
2. **WebSocket Keep-Alive**:
   - Base `/ws` connection runs an automatic exponential backoff reconnection loop ($1\text{s}, 2\text{s}, 4\text{s}, \dots, \max 16\text{s}$) when dropped.
3. **Microphone Permission Denied**:
   - Catches browser `NotAllowedError` or `NotFoundError`. Closes voice overlay gracefully and presents an actionable recovery toast.
4. **IMAP Authentication Timeout**:
   - Network timeouts to IMAP hosts are caught within 10 seconds, preventing blocking of the async FastAPI event loop.

