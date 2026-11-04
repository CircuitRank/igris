import os
from PIL import Image, ImageDraw, ImageFont

def create_workflow_image(output_path="workflow_diagram.png"):
    # High resolution canvas
    W, H = 2100, 1200
    img = Image.new("RGB", (W, H), "#121212")
    draw = ImageDraw.Draw(img)

    # Fonts
    bold_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    reg_path = "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"
    mono_path = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"

    font_title = ImageFont.truetype(bold_path, 42)
    font_subtitle = ImageFont.truetype(reg_path, 20)
    font_col_header = ImageFont.truetype(bold_path, 22)
    font_card_title = ImageFont.truetype(bold_path, 19)
    font_card_sub = ImageFont.truetype(bold_path, 13)
    font_card_body = ImageFont.truetype(reg_path, 15)
    font_badge = ImageFont.truetype(bold_path, 13)
    font_mono = ImageFont.truetype(mono_path, 14)

    # 1. Background grid dots
    grid_spacing = 30
    for x in range(0, W, grid_spacing):
        for y in range(0, H, grid_spacing):
            draw.point((x, y), fill="#1c1c1c")

    # 2. Header Area
    margin_x = 70
    header_y = 50

    # Google 4-color dots accent
    dots = [
        ("#4285F4", margin_x),
        ("#EA4335", margin_x + 22),
        ("#FBBC05", margin_x + 44),
        ("#34A853", margin_x + 66)
    ]
    for color, dx in dots:
        draw.ellipse([dx, header_y + 16, dx + 12, header_y + 28], fill=color)

    draw.text((margin_x + 100, header_y), "IGRIS  WORKFLOW", font=font_title, fill="#FFFFFF")
    draw.text(
        (margin_x + 102, header_y + 50),
        "End-to-End System Architecture: Notion-Dark Desktop UI, Real-Time Google Voice Assistant & Dual AI Engines",
        font=font_subtitle,
        fill="#888888"
    )

    # Top border line
    draw.line([(margin_x, header_y + 90), (W - margin_x, header_y + 90)], fill="#262626", width=2)

    # 3. Columns Layout
    cols = [
        {"id": "input", "title": "1. USER INPUT", "color": "#4285F4", "x": 70, "w": 330},
        {"id": "client", "title": "2. CLIENT APP", "color": "#FBBC05", "x": 440, "w": 360},
        {"id": "backend", "title": "3. BACKEND ROUTER", "color": "#34A853", "x": 840, "w": 360},
        {"id": "brain", "title": "4. DUAL AI BRAIN", "color": "#A172F8", "x": 1240, "w": 400},
        {"id": "output", "title": "5. ACTIONS & OUTPUT", "color": "#EA4335", "x": 1680, "w": 350},
    ]

    top_content_y = 170

    # Draw Column Headers
    for col in cols:
        cx = col["x"]
        # Column pill
        draw.rectangle([cx, top_content_y, cx + col["w"], top_content_y + 36], fill="#1a1a1a", outline="#2b2b2b", width=1)
        # Color bar indicator
        draw.rectangle([cx, top_content_y, cx + 5, top_content_y + 36], fill=col["color"])
        draw.text((cx + 16, top_content_y + 8), col["title"], font=font_col_header, fill="#E0E0E0")

    def draw_card(x, y, w, h, title, badge_text, badge_color, lines, sub_badge=None):
        # Card background
        draw.rounded_rectangle([x, y, x + w, y + h], radius=10, fill="#1c1c1c", outline="#2d2d2d", width=1)
        
        # Header strip inside card
        draw.text((x + 16, y + 16), title, font=font_card_title, fill="#FFFFFF")
        
        # Badge
        bw = int(draw.textlength(badge_text, font=font_badge)) + 14
        bx = x + w - bw - 14
        draw.rounded_rectangle([bx, y + 14, bx + bw, y + 36], radius=5, fill=badge_color)
        draw.text((bx + 7, y + 18), badge_text, font=font_badge, fill="#FFFFFF")

        # Sub-badge if provided
        cur_y = y + 46
        if sub_badge:
            draw.text((x + 16, cur_y), sub_badge, font=font_card_sub, fill="#777777")
            cur_y += 24

        # Divider line
        draw.line([(x + 16, cur_y), (x + w - 16, cur_y)], fill="#262626", width=1)
        cur_y += 14

        # Content lines
        for line in lines:
            if line.startswith("• "):
                draw.text((x + 18, cur_y), "•", font=font_card_body, fill=badge_color)
                draw.text((x + 32, cur_y), line[2:], font=font_card_body, fill="#B8B8B8")
            elif line.startswith("  - "):
                draw.text((x + 36, cur_y), "–", font=font_card_body, fill="#666666")
                draw.text((x + 48, cur_y), line[4:], font=font_card_body, fill="#999999")
            elif line.startswith("> "):
                draw.rounded_rectangle([x + 16, cur_y - 2, x + w - 16, cur_y + 22], radius=4, fill="#141414", outline="#262626")
                draw.text((x + 24, cur_y + 2), line[2:], font=font_mono, fill="#4285F4")
            else:
                draw.text((x + 16, cur_y), line, font=font_card_body, fill="#B8B8B8")
            cur_y += 22

    # Draw Connecting Arrows
    def draw_arrow(x1, y1, x2, y2, color="#444444", label=""):
        draw.line([(x1, y1), (x2, y2)], fill=color, width=2)
        # Arrow head
        arrow_size = 6
        if x2 > x1:  # Left to right
            draw.polygon([(x2, y2), (x2 - arrow_size * 2, y2 - arrow_size), (x2 - arrow_size * 2, y2 + arrow_size)], fill=color)
        elif x2 == x1 and y2 > y1:  # Top to bottom
            draw.polygon([(x2, y2), (x2 - arrow_size, y2 - arrow_size * 2), (x2 + arrow_size, y2 - arrow_size * 2)], fill=color)
        if label:
            lx = (x1 + x2) // 2
            ly = (y1 + y2) // 2 - 12
            draw.text((lx - 20, ly), label, font=font_badge, fill=color)

    # ------------------ COLUMN 1: INPUT ------------------
    # Card 1.1: Voice Input
    draw_card(
        x=70, y=230, w=330, h=250,
        title="Voice Streaming",
        badge_text="REAL-TIME", badge_color="#1976D2",
        lines=[
            "• Microphone Capture",
            "  - Hands-Free VAD Loop",
            "  - Push-to-Talk (Space bar)",
            "• Web Audio Resampling",
            "  - 48kHz → 16kHz Linear PCM",
            "  - Signed 16-bit Little-Endian",
            "> audio/pcm;rate=16000",
            "• Instant Mid-Turn Barge-In"
        ],
        sub_badge="AUDIO CAPTURE ENGINE"
    )

    # Card 1.2: Text Input
    draw_card(
        x=70, y=510, w=330, h=250,
        title="Text & Commands",
        badge_text="NOTION UI", badge_color="#37474F",
        lines=[
            "• Minimalist Prompt Box",
            "  - Auto-resizing textarea",
            "  - Shift+Enter multi-line",
            "• Command Shortcuts",
            "  - Ctrl+\\ (Toggle sidebar)",
            "  - Ctrl+, (Open settings)",
            "  - Ctrl+Shift+O (New chat)",
            "> Esc stops voice / generation"
        ],
        sub_badge="COMPOSER & SHORTCUTS"
    )

    # Card 1.3: Email Prompts
    draw_card(
        x=70, y=790, w=330, h=250,
        title="Email Actions",
        badge_text="MAIL QUERY", badge_color="#00695C",
        lines=[
            "• Natural Language Prompts:",
            "  - 'Check my unread emails'",
            "  - 'Summarize message #1'",
            "  - 'Do I have mail from John?'",
            "• Table Interaction:",
            "  - Click row to open Side Peek",
            "  - One-click 'Summarize with AI'",
            "> Instant AI reply drafting"
        ],
        sub_badge="INBOX CONVERSATION"
    )

    # ------------------ COLUMN 2: CLIENT APP ------------------
    # Card 2.1: Electron & Notion UI
    draw_card(
        x=440, y=230, w=360, h=390,
        title="Electron Notion Client",
        badge_text="FRONTEND", badge_color="#E65100",
        lines=[
            "• Notion Dark Design System",
            "  - Canvas: #191919 (Pure Dark)",
            "  - Sidebar: #202020 (Collapsible)",
            "  - Surface: #252525 (Modals & Cards)",
            "• Pages & Navigation",
            "  - Igris AI Canvas (Chat & Voice)",
            "  - Inbox Database (All / Unread)",
            "  - Side Peek Drawer (Email Body)",
            "• Google 4-Color Wave Visualizer",
            "  - Blue, Red, Yellow, Green bars",
            "  - Responsive to speech energy",
            "• Jitter Buffer & Audio Player",
            "  - 24kHz PCM chunk queue",
            "  - Instant purge on barge-in"
        ],
        sub_badge="DESKTOP SHELL & DSP"
    )

    # Card 2.2: Settings & State
    draw_card(
        x=440, y=650, w=360, h=390,
        title="Settings & Preferences",
        badge_text="LOCAL STATE", badge_color="#455A64",
        lines=[
            "• Cloud AI Configuration",
            "  - Gemini API key management",
            "  - Google voice selector (5 voices)",
            "  - Live key test validation",
            "• Email Account Management",
            "  - Gmail, Outlook, iCloud, Yahoo",
            "  - App Password security",
            "  - Live IMAP connection test",
            "• Local Preferences (localStorage)",
            "  - Speech toggle, VAD threshold",
            "  - Sidebar state persistence",
            "> Single-instance desktop lock"
        ],
        sub_badge="CONFIGURATION MODAL"
    )

    # ------------------ COLUMN 3: BACKEND ROUTER ------------------
    # Card 3.1: FastAPI Server
    draw_card(
        x=840, y=230, w=360, h=470,
        title="FastAPI Orchestrator",
        badge_text="CORE :8000", badge_color="#2E7D32",
        lines=[
            "• High-Performance ASGI Engine",
            "  - Python 3.10+ & Uvicorn worker",
            "• Bidirectional Endpoints:",
            "> /ws/live  (Raw PCM Audio Stream)",
            "> /ws       (Text Events & Local Audio)",
            "> /api/ai   (Settings & Verification)",
            "> /api/email(IMAP Sync & Summaries)",
            "• Protocol Router & Relay",
            "  - Routes audio to Gemini Live WSS",
            "  - Bridges tool calls to local OS",
            "• Reentrant Thread Synchronization",
            "  - threading.Lock() on SQLite",
            "• Safety Command Sanitization"
        ],
        sub_badge="COMMUNICATION HUB"
    )

    # Card 3.2: SQLite Memory
    draw_card(
        x=840, y=730, w=360, h=310,
        title="Persistent Memory",
        badge_text="SQLITE DB", badge_color="#3E2723",
        lines=[
            "• Local igris_memory.db File",
            "• Tables:",
            "  - conversations (Session list)",
            "  - messages (Turn-by-turn history)",
            "  - memory_facts (User profile)",
            "  - settings (Keys & credentials)",
            "• Zero Cloud Telemetry",
            "• 100% On-Device Data Sovereignty"
        ],
        sub_badge="LOCAL STORAGE TIER"
    )

    # ------------------ COLUMN 4: DUAL AI BRAIN ------------------
    # Card 4.1: Cloud AI (Gemini 2.0 Live)
    draw_card(
        x=1240, y=230, w=400, h=470,
        title="Google Gemini 2.0 Live",
        badge_text="PRIMARY CLOUD", badge_color="#6A1B9A",
        lines=[
            "• Multimodal Live API (WebSocket)",
            "  - Direct speech-to-speech engine",
            "  - Sub-800ms latency (< 1 second)",
            "• Google DeepMind Neural Voices:",
            "  - Aoede (Warm & engaging - Default)",
            "  - Puck (Upbeat & energetic)",
            "  - Charon (Calm & thoughtful)",
            "  - Fenrir (Authoritative & direct)",
            "  - Kore (Soft & clear)",
            "• Bidirectional Streaming Format:",
            "  - In: 16kHz PCM mono base64",
            "  - Out: 24kHz PCM linear audio",
            "• Native In-Flight Tool Calling:",
            "  - toolCall & toolResponse frames"
        ],
        sub_badge="GOOGLE ASSISTANT ENGINE"
    )

    # Card 4.2: Edge Local Engine (Fallback)
    draw_card(
        x=1240, y=730, w=400, h=310,
        title="Local Engine (Offline)",
        badge_text="EDGE FALLBACK", badge_color="#C2185B",
        lines=[
            "• Activated when Offline / No Key",
            "• Faster-Whisper (STT)",
            "  - CTranslate2 quantized model",
            "• Ollama Local LLM",
            "  - Model: qwen2.5-coder:3b",
            "  - Local inference on port 11434",
            "• Edge-TTS / PyTTSx3 (Audio Synthesis)",
            "• DeepFilterNet (Noise Gating)"
        ],
        sub_badge="OFFLINE CONTINGENCY"
    )

    # ------------------ COLUMN 5: ACTIONS & OUTPUT ------------------
    # Card 5.1: System Control
    draw_card(
        x=1680, y=230, w=350, h=250,
        title="OS System Tools",
        badge_text="DESKTOP API", badge_color="#C62828",
        lines=[
            "• open_app(app_name)",
            "  - VS Code, Chrome, Spotify, etc.",
            "• execute_command(command)",
            "  - Shell with 15s timeout limit",
            "• media_control(action)",
            "  - Play, Pause, Next, Prev",
            "• analyze_screen(prompt)",
            "  - Fast MSS desktop frame capture"
        ],
        sub_badge="CROSS-PLATFORM AUTOMATION"
    )

    # Card 5.2: Email Engine
    draw_card(
        x=1680, y=510, w=350, h=250,
        title="Email Workspace",
        badge_text="IMAP4rev1", badge_color="#00838F",
        lines=[
            "• Direct SSL/TLS over Port 993",
            "• RFC 2047 MIME Header Decoding",
            "• HTML Stripping & Sanitization",
            "• Inbox Database Table Sync",
            "• Side Peek Email Inspector",
            "• One-Click AI Inbox Summaries"
        ],
        sub_badge="MAILBOX INTEGRATION"
    )

    # Card 5.3: Acoustic Output
    draw_card(
        x=1680, y=790, w=350, h=250,
        title="Audio Output",
        badge_text="24kHz SOUND", badge_color="#283593",
        lines=[
            "• Real-Time Neural Speech",
            "  - Google Assistant Voices",
            "• Dynamic Jitter Scheduling",
            "  - Time-offset Web Audio queue",
            "• Barge-In Acoustic Mute",
            "  - Flushes queue on speech",
            "> Zero audio overlapping"
        ],
        sub_badge="SPEECH PLAYBACK"
    )

    # ------------------ CONNECTING ARROWS ------------------
    # 1. Input -> Client
    draw_arrow(400, 350, 440, 350, color="#4285F4")
    draw_arrow(400, 630, 440, 630, color="#888888")
    draw_arrow(400, 850, 440, 750, color="#00695C")

    # 2. Client -> Backend
    draw_arrow(800, 380, 840, 380, color="#34A853", label="WS / REST")
    draw_arrow(800, 780, 840, 780, color="#34A853")

    # 3. Backend -> Brain
    draw_arrow(1200, 380, 1240, 380, color="#A172F8", label="Live Stream")
    draw_arrow(1200, 850, 1240, 850, color="#C2185B", label="Fallback")

    # 4. Brain -> Actions / Output
    draw_arrow(1640, 350, 1680, 350, color="#C62828", label="Tools")
    draw_arrow(1640, 600, 1680, 600, color="#00838F", label="IMAP")
    draw_arrow(1640, 880, 1680, 880, color="#283593", label="Audio")

    # Return feedback arrow from Audio to User (Acoustic loop)
    draw.arc([50, 950, 1950, 1180], start=30, end=150, fill="#333333", width=2)
    draw.text((1000, 1120), "Natural Conversational Feedback Loop (Sub-Second Turnaround)", font=font_subtitle, fill="#555555")

    # Save image
    img.save(output_path, "PNG", quality=95)
    print(f"Workflow diagram successfully saved to {output_path}")

if __name__ == "__main__":
    create_workflow_image("/home/voldemort/igris/workflow_diagram.png")

