// ============================================================
// IGRIS — Renderer (Notion-style workspace)
// IPC is exposed via preload.js as window.electronAPI
// ============================================================

const API_BASE = 'http://127.0.0.1:8000';
const WS_URL = 'ws://127.0.0.1:8000/ws/chat';

const $ = (id) => document.getElementById(id);

// ---------- DOM ----------
const chatContainer = $('chat-container');
const chatScroll = $('chat-scroll');
const userInput = $('user-input');
const sendBtn = $('send-btn');
const stopBtn = $('stop-btn');
const speakToggle = $('speak-toggle');
const miniModeBtn = $('mini-mode-btn');
const statusDot = $('status-dot');
const statusText = $('status-text');
const pingMetric = $('ping-metric');
const crumbIcon = $('crumb-icon');
const crumbTitle = $('crumb-title');
const inboxBadge = $('inbox-badge');

// Voice overlay
const voiceOverlay = $('voice-overlay');
const voiceOrb = $('voice-orb');
const voiceStateLabel = $('voice-state-label');
const voiceTranscript = $('voice-transcript');
const voiceResponse = $('voice-response');
const voiceBtn = $('voice-btn');
const voiceCloseBtn = $('voice-close-btn');
const voiceModeToggle = $('voice-mode-toggle');
const voiceInterruptBtn = $('voice-interrupt-btn');
const modeLabel = $('mode-label');

// Cloud AI State
const aiState = {
    provider: 'gemini',
    hasKey: false,
    apiKey: '',
    voice: 'Aoede',
    model: 'gemini-2.0-flash',
    loaded: false,
};

async function loadAiSettings() {
    try {
        const s = await api('/api/ai/settings');
        aiState.provider = s.provider || 'gemini';
        aiState.hasKey = s.has_key || false;
        aiState.voice = s.voice || 'Aoede';
        aiState.model = s.model || 'gemini-2.0-flash';
        aiState.loaded = true;

        if ($('ai-provider')) $('ai-provider').value = aiState.provider;
        if ($('gemini-voice')) $('gemini-voice').value = aiState.voice;
        if ($('gemini-api-key')) {
            $('gemini-api-key').value = '';
            $('gemini-api-key').placeholder = s.has_key ? '•••••••••••• (saved)' : 'AIzaSy...';
        }
    } catch (e) {
        console.error('Failed to load AI settings:', e);
    }
}

// ============================================================
// Preferences (persisted locally)
// ============================================================
const prefs = {
    get speak() { return localStorage.getItem('igris.speak') === '1'; },
    set speak(v) { localStorage.setItem('igris.speak', v ? '1' : '0'); },
    get voiceMode() { return localStorage.getItem('igris.voiceMode') || 'hands-free'; },
    set voiceMode(v) { localStorage.setItem('igris.voiceMode', v); },
    get sidebarCollapsed() { return localStorage.getItem('igris.sidebarCollapsed') === '1'; },
    set sidebarCollapsed(v) { localStorage.setItem('igris.sidebarCollapsed', v ? '1' : '0'); },
};

// ============================================================
// Utilities
// ============================================================
function escapeHtml(str) {
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function api(path, options = {}) {
    const res = await fetch(API_BASE + path, {
        headers: { 'Content-Type': 'application/json' },
        ...options,
    });
    return res.json();
}

function toast(message, kind = '') {
    const container = $('toast-container');
    const el = document.createElement('div');
    el.className = `toast ${kind}`;
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
        el.classList.add('leaving');
        setTimeout(() => el.remove(), 220);
    }, 3600);
}

function openExternal(url) {
    if (window.electronAPI && window.electronAPI.openExternal) {
        window.electronAPI.openExternal(url);
    }
}

async function copyText(text, btn) {
    try {
        await navigator.clipboard.writeText(text);
        if (btn) {
            const prev = btn.innerHTML;
            btn.textContent = 'Copied';
            setTimeout(() => { btn.innerHTML = prev; }, 1200);
        } else {
            toast('Copied to clipboard', 'ok');
        }
    } catch (e) {
        toast('Could not copy to clipboard', 'err');
    }
}

// ============================================================
// Minimal, safe Markdown renderer (input is always HTML-escaped first)
// ============================================================
function renderInline(escaped) {
    const codes = [];
    let text = escaped.replace(/`([^`\n]+)`/g, (m, c) => {
        codes.push(c);
        return `\u0000${codes.length - 1}\u0000`;
    });
    text = text.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    text = text.replace(/__([^_\n]+)__/g, '<strong>$1</strong>');
    text = text.replace(/(^|[^*\w])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
    text = text.replace(/\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a data-href="$2">$1</a>');
    text = text.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a data-href="$2">$2</a>');
    text = text.replace(/\u0000(\d+)\u0000/g, (m, i) => `<code>${codes[Number(i)]}</code>`);
    return text;
}

function renderMarkdown(src) {
    const lines = String(src || '').replace(/\r\n/g, '\n').split('\n');
    let html = '';
    let para = [];
    let listType = null;

    const flushPara = () => {
        if (para.length) {
            html += `<p>${para.map((l) => renderInline(escapeHtml(l))).join('<br>')}</p>`;
            para = [];
        }
    };
    const closeList = () => {
        if (listType) {
            html += `</${listType}>`;
            listType = null;
        }
    };

    let i = 0;
    while (i < lines.length) {
        const line = lines[i];

        const fence = line.match(/^\s*```\s*([\w+-]*)/);
        if (fence) {
            flushPara(); closeList();
            const lang = fence[1] || 'code';
            const buf = [];
            i++;
            while (i < lines.length && !/^\s*```/.test(lines[i])) { buf.push(lines[i]); i++; }
            i++;
            html += `<div class="code-block"><div class="code-header"><span>${escapeHtml(lang)}</span><button class="code-copy">Copy</button></div><pre><code>${escapeHtml(buf.join('\n'))}</code></pre></div>`;
            continue;
        }

        const heading = line.match(/^(#{1,3})\s+(.*)$/);
        if (heading) {
            flushPara(); closeList();
            const lvl = heading[1].length + 1;
            html += `<h${lvl}>${renderInline(escapeHtml(heading[2]))}</h${lvl}>`;
            i++; continue;
        }

        const ul = line.match(/^\s*[-*•]\s+(.*)$/);
        const ol = line.match(/^\s*\d+[.)]\s+(.*)$/);
        if (ul || ol) {
            flushPara();
            const type = ul ? 'ul' : 'ol';
            if (listType !== type) { closeList(); html += `<${type}>`; listType = type; }
            html += `<li>${renderInline(escapeHtml((ul || ol)[1]))}</li>`;
            i++; continue;
        }

        if (/^\s*>\s?/.test(line)) {
            flushPara(); closeList();
            html += `<blockquote>${renderInline(escapeHtml(line.replace(/^\s*>\s?/, '')))}</blockquote>`;
            i++; continue;
        }

        if (/^\s*(---|\*\*\*)\s*$/.test(line)) {
            flushPara(); closeList();
            html += '<hr>';
            i++; continue;
        }

        if (!line.trim()) {
            flushPara(); closeList();
            i++; continue;
        }

        closeList();
        para.push(line);
        i++;
    }
    flushPara(); closeList();
    return html;
}

// Delegated handlers for links & code copy buttons inside rendered markdown
document.addEventListener('click', (e) => {
    const link = e.target.closest('a[data-href]');
    if (link) {
        e.preventDefault();
        openExternal(link.getAttribute('data-href'));
        return;
    }
    const copyBtn = e.target.closest('.code-copy');
    if (copyBtn) {
        const code = copyBtn.closest('.code-block').querySelector('code');
        copyText(code.textContent, copyBtn);
    }
});

// ============================================================
// Navigation, sidebar & layout
// ============================================================
let currentView = 'chat';
const VIEW_META = {
    chat: { icon: '✦', title: 'Igris AI' },
    inbox: { icon: '📬', title: 'Inbox' },
};

function switchView(view) {
    if (!VIEW_META[view]) return;
    currentView = view;
    document.querySelectorAll('.view').forEach((v) => v.classList.toggle('active', v.id === `view-${view}`));
    document.querySelectorAll('.nav-item[data-view]').forEach((n) => n.classList.toggle('active', n.dataset.view === view));
    crumbIcon.textContent = VIEW_META[view].icon;
    crumbTitle.textContent = VIEW_META[view].title;
    if (view === 'inbox' && !inboxState.loadedOnce) loadInbox();
    if (view === 'chat') setTimeout(() => userInput.focus(), 0);
}

function setSidebarCollapsed(collapsed) {
    document.body.classList.toggle('sidebar-collapsed', collapsed);
    $('open-sidebar-btn').classList.toggle('hidden', !collapsed);
    prefs.sidebarCollapsed = collapsed;
}

$('collapse-sidebar-btn').addEventListener('click', () => setSidebarCollapsed(true));
$('open-sidebar-btn').addEventListener('click', () => setSidebarCollapsed(false));

document.querySelectorAll('.nav-item[data-view]').forEach((btn) => {
    btn.addEventListener('click', () => switchView(btn.dataset.view));
});
document.querySelectorAll('[data-action="new-chat"]').forEach((btn) => btn.addEventListener('click', newChat));
document.querySelectorAll('[data-action="settings"]').forEach((btn) => btn.addEventListener('click', () => openSettings()));
document.querySelectorAll('[data-prompt]').forEach((btn) => {
    btn.addEventListener('click', () => {
        switchView('chat');
        sendMessage(btn.dataset.prompt);
    });
});

// Compact floating mode
miniModeBtn.addEventListener('click', () => {
    const isMini = document.body.classList.toggle('mini-mode');
    miniModeBtn.classList.toggle('active', isMini);
    miniModeBtn.title = isMini ? 'Exit compact mode' : 'Compact floating mode';
    if (window.electronAPI) window.electronAPI.toggleMiniMode(isMini);
    scrollChatToBottom(true);
});

// Speak toggle
function applySpeakPref() {
    speakToggle.classList.toggle('active', prefs.speak);
    speakToggle.title = prefs.speak ? 'Speaking typed responses (click to mute)' : 'Speak typed responses aloud';
    $('setting-speak').checked = prefs.speak;
}
speakToggle.addEventListener('click', () => {
    prefs.speak = !prefs.speak;
    applySpeakPref();
    if (!prefs.speak) interruptPlayback();
    toast(prefs.speak ? 'Responses will be spoken aloud' : 'Spoken responses muted');
});

// ============================================================
// Connection status
// ============================================================
function setConnection(state, label) {
    statusDot.className = `status-dot ${state}`;
    statusText.textContent = label;
    if (state !== 'online' && state !== 'busy') pingMetric.textContent = '';
}

// ============================================================
// Chat
// ============================================================
let ws = null;
let pingInterval = null;
let lastPingSent = 0;
let historyHydrated = false;
let isGenerating = false;

let currentAiMsg = null;      // { el, contentEl, raw }
let thinkingEl = null;
let renderQueued = false;

function scrollChatToBottom(force = false) {
    const nearBottom = chatScroll.scrollHeight - chatScroll.scrollTop - chatScroll.clientHeight < 160;
    if (force || nearBottom) chatScroll.scrollTop = chatScroll.scrollHeight;
}

function updateHasMessages() {
    document.body.classList.toggle('has-messages', chatContainer.children.length > 0);
}

function setGenerating(active) {
    isGenerating = active;
    stopBtn.classList.toggle('hidden', !active);
    sendBtn.classList.toggle('hidden', active);
    if (ws && ws.readyState === WebSocket.OPEN) {
        setConnection(active ? 'busy' : 'online', active ? 'Working…' : 'Connected');
    }
}

function addUserMessage(text, isVoice = false) {
    const row = document.createElement('div');
    row.className = 'msg msg-user';
    const wrap = document.createElement('div');
    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble';
    bubble.textContent = text;
    wrap.appendChild(bubble);
    if (isVoice) {
        const tag = document.createElement('span');
        tag.className = 'msg-voice-tag';
        tag.textContent = '🎙 Voice';
        wrap.appendChild(tag);
    }
    row.appendChild(wrap);
    chatContainer.appendChild(row);
    updateHasMessages();
    scrollChatToBottom(true);
}

function createAiMessage(initialRaw = '') {
    const row = document.createElement('div');
    row.className = 'msg msg-ai';
    row.innerHTML = `
        <div class="msg-avatar">✦</div>
        <div class="msg-body">
            <div class="msg-name">Igris</div>
            <div class="msg-content md"></div>
            <div class="msg-actions">
                <button class="icon-btn msg-copy" title="Copy">
                    <svg viewBox="0 0 16 16" width="14" height="14"><rect x="5" y="5" width="8.5" height="8.5" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M11 5V3.5c0-.8-.7-1.5-1.5-1.5h-6C2.7 2 2 2.7 2 3.5v6c0 .8.7 1.5 1.5 1.5H5" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>
                </button>
            </div>
        </div>`;
    const msg = { el: row, contentEl: row.querySelector('.msg-content'), raw: initialRaw };
    row.querySelector('.msg-copy').addEventListener('click', () => copyText(msg.raw));
    msg.contentEl.innerHTML = renderMarkdown(initialRaw);
    chatContainer.appendChild(row);
    updateHasMessages();
    return msg;
}

function showThinking(label = 'Thinking…') {
    if (!thinkingEl) {
        thinkingEl = document.createElement('div');
        thinkingEl.className = 'msg msg-ai';
        thinkingEl.innerHTML = `<div class="msg-avatar">✦</div><div class="msg-body"><span class="thinking-text"></span></div>`;
        chatContainer.appendChild(thinkingEl);
        updateHasMessages();
    }
    thinkingEl.querySelector('.thinking-text').textContent = label;
    // Keep indicator as the last element
    chatContainer.appendChild(thinkingEl);
    scrollChatToBottom();
}

function hideThinking() {
    if (thinkingEl) {
        thinkingEl.remove();
        thinkingEl = null;
    }
}

function addSystemNotice(text, isError = false) {
    const row = document.createElement('div');
    row.className = `msg msg-system${isError ? ' error' : ''}`;
    const span = document.createElement('span');
    span.className = 'msg-notice';
    span.textContent = text;
    row.appendChild(span);
    chatContainer.appendChild(row);
    updateHasMessages();
    scrollChatToBottom();
}

function queueRender() {
    if (renderQueued || !currentAiMsg) return;
    renderQueued = true;
    requestAnimationFrame(() => {
        renderQueued = false;
        if (!currentAiMsg) return;
        currentAiMsg.contentEl.innerHTML = renderMarkdown(currentAiMsg.raw);
        currentAiMsg.contentEl.classList.add('cursor-blink');
        scrollChatToBottom();
    });
}

function finalizeAiMessage() {
    if (currentAiMsg) {
        currentAiMsg.contentEl.innerHTML = renderMarkdown(currentAiMsg.raw);
        currentAiMsg.contentEl.classList.remove('cursor-blink');
        if (!currentAiMsg.raw.trim()) currentAiMsg.el.remove();
        currentAiMsg = null;
    }
}

function sendMessage(textOverride) {
    const text = (typeof textOverride === 'string' ? textOverride : userInput.value).trim();
    if (!text) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        toast('Not connected to the Igris backend yet', 'err');
        return;
    }
    if (isGenerating) {
        finalizeAiMessage();
        hideThinking();
    }
    addUserMessage(text);
    ws.send(JSON.stringify({ type: 'chat', text, tts: prefs.speak }));
    if (typeof textOverride !== 'string') {
        userInput.value = '';
        autoResize();
    }
    updateSendState();
    setGenerating(true);
    showThinking();
}

function stopGenerating() {
    interruptPlayback();
    sendInterrupt();
}

function newChat() {
    switchView('chat');
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'clear_history' }));
    } else {
        api('/api/history', { method: 'DELETE' }).catch(() => {});
        clearChatUI();
    }
}

function clearChatUI() {
    interruptPlayback();
    currentAiMsg = null;
    hideThinking();
    chatContainer.innerHTML = '';
    updateHasMessages();
    setGenerating(false);
    userInput.focus();
}

async function hydrateHistory() {
    if (historyHydrated) return;
    historyHydrated = true;
    try {
        const data = await api('/api/history?limit=30');
        if (chatContainer.children.length > 0) return;
        (data.messages || []).forEach((m) => {
            if (!m.content || !m.content.trim()) return;
            if (m.role === 'user') {
                if (m.content.startsWith('[SYSTEM NOTIFICATION')) return;
                addUserMessage(m.content);
            } else if (m.role === 'assistant') {
                createAiMessage(m.content);
            }
        });
        scrollChatToBottom(true);
    } catch (e) {
        historyHydrated = false;
    }
}

// Composer
function autoResize() {
    userInput.style.height = 'auto';
    userInput.style.height = Math.min(userInput.scrollHeight, 200) + 'px';
}
function updateSendState() {
    sendBtn.disabled = !userInput.value.trim();
}
userInput.addEventListener('input', () => { autoResize(); updateSendState(); });
userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        sendMessage();
    }
});
sendBtn.addEventListener('click', () => sendMessage());
stopBtn.addEventListener('click', stopGenerating);

// ============================================================
// WebSocket
// ============================================================
function connectWebSocket() {
    setConnection('', 'Connecting…');
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        setConnection('online', 'Connected');
        hydrateHistory();
        refreshInboxBadge();
        clearInterval(pingInterval);
        pingInterval = setInterval(() => {
            if (ws && ws.readyState === WebSocket.OPEN) {
                lastPingSent = performance.now();
                ws.send(JSON.stringify({ type: 'ping' }));
            }
        }, 5000);
    };

    ws.onmessage = (event) => {
        let data;
        try {
            data = JSON.parse(event.data);
        } catch (e) {
            return;
        }
        handleServerMessage(data);
    };

    ws.onclose = () => {
        clearInterval(pingInterval);
        pingInterval = null;
        setConnection('offline', 'Offline — reconnecting…');
        if (isGenerating) {
            finalizeAiMessage();
            hideThinking();
            setGenerating(false);
        }
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (err) => console.error('WebSocket error:', err);
}

function handleServerMessage(data) {
    switch (data.type) {
        case 'pong': {
            const latency = Math.round(performance.now() - lastPingSent);
            pingMetric.textContent = `${latency} ms`;
            break;
        }
        case 'status':
            if (isGenerating) {
                const label = data.content && data.content !== 'Ready' ? data.content : 'Thinking…';
                showThinking(label);
            }
            break;
        case 'stream_start':
            hideThinking();
            finalizeAiMessage();
            currentAiMsg = createAiMessage('');
            currentAiMsg.contentEl.classList.add('cursor-blink');
            scrollChatToBottom();
            break;
        case 'stream_chunk':
            if (!currentAiMsg) {
                hideThinking();
                currentAiMsg = createAiMessage('');
            }
            currentAiMsg.raw += data.content || '';
            queueRender();
            if (voiceState !== 'INACTIVE') voiceResponse.textContent += data.content || '';
            break;
        case 'stream_end':
            hideThinking();
            finalizeAiMessage();
            setGenerating(false);
            break;
        case 'transcription':
            voiceTranscript.textContent = `“${data.text}”`;
            voiceResponse.textContent = '';
            addUserMessage(data.text, true);
            setGenerating(true);
            showThinking();
            break;
        case 'voice_empty':
            if (voiceState === 'PROCESSING') resumeListening();
            break;
        case 'voice_error':
            toast(data.content || 'Audio processing failed', 'err');
            if (voiceState !== 'INACTIVE') {
                voiceStateLabel.textContent = 'Something went wrong — try again';
                setTimeout(resumeListening, 1500);
            }
            break;
        case 'speaking_start':
            if (voiceState !== 'INACTIVE') setVoiceState('SPEAKING');
            break;
        case 'speaking_end':
            // Transition back to LISTENING happens when playNextAudio() drains the queue
            break;
        case 'audio':
            audioQueue.push(data.data);
            if (!isPlayingAudio) playNextAudio();
            break;
        case 'interrupted':
            hideThinking();
            finalizeAiMessage();
            setGenerating(false);
            if (voiceState !== 'INACTIVE') resumeListening();
            break;
        case 'open_sandbox_browser':
            if (window.electronAPI) window.electronAPI.openSandboxBrowser(data.url);
            break;
        case 'navigate':
            if (data.view) switchView(data.view);
            break;
        case 'email_checked':
            if (data.configured) setInboxBadge(data.unread_count || 0);
            break;
        case 'history_cleared':
            clearChatUI();
            toast('Started a new chat');
            break;
        case 'system_notice':
            toast(data.content || 'Notice');
            break;
        default:
            break;
    }
}

// ============================================================
// Audio playback (TTS) + orb reaction
// ============================================================
let audioQueue = [];
let isPlayingAudio = false;
let currentAudio = null;
let audioCtx = null;
let analyser = null;
let currentSource = null;

function initVisualizer(audioElement) {
    if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        analyser.connect(audioCtx.destination);
    }
    try {
        if (currentSource) {
            currentSource.disconnect();
            currentSource = null;
        }
        currentSource = audioCtx.createMediaElementSource(audioElement);
        currentSource.connect(analyser);
    } catch (e) {
        // Source might already be created for this element
    }
}

function animateVoiceOrb() {
    if (!isPlayingAudio || !analyser) {
        voiceOrb.style.transform = 'scale(1)';
        return;
    }
    requestAnimationFrame(animateVoiceOrb);
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
    const average = sum / dataArray.length;
    voiceOrb.style.transform = `scale(${1 + average / 300})`;
}

function playNextAudio() {
    if (audioQueue.length === 0) {
        isPlayingAudio = false;
        voiceOrb.style.transform = 'scale(1)';
        if (voiceState === 'SPEAKING') resumeListening();
        return;
    }

    isPlayingAudio = true;
    const base64Audio = audioQueue.shift();
    currentAudio = new Audio('data:audio/mp3;base64,' + base64Audio);

    currentAudio.onplay = () => {
        initVisualizer(currentAudio);
        if (voiceState !== 'INACTIVE') {
            animateVoiceOrb();
            startInterruptDetection();
        }
    };
    currentAudio.onended = () => playNextAudio();
    currentAudio.onerror = (e) => {
        console.error('Audio playback error', e);
        playNextAudio();
    };
    currentAudio.play().catch((e) => {
        console.error('Audio play failed', e);
        playNextAudio();
    });
}

function interruptPlayback() {
    audioQueue = [];
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        currentAudio = null;
    }
    isPlayingAudio = false;
    stopInterruptDetection();
    stopAndClearPcmPlayback();
    voiceOrb.style.transform = 'scale(1)';
    resetGoogleWave();
}

function sendInterrupt() {
    if (isGeminiLiveMode && liveWs && liveWs.readyState === WebSocket.OPEN) {
        liveWs.send(JSON.stringify({ type: 'interrupt' }));
    } else if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'interrupt' }));
    }
}

// ============================================================
// Google Assistant 4-Color Wave Visualizer
// ============================================================
const gBars = document.querySelectorAll('.g-bar');

function animateGoogleWave(energy) {
    if (!gBars || gBars.length < 4) return;
    const base = Math.min(28, Math.max(6, energy * 1.6));
    gBars[0].style.height = `${base * 0.9}px`;
    gBars[1].style.height = `${base * 1.3}px`;
    gBars[2].style.height = `${base * 1.1}px`;
    gBars[3].style.height = `${base * 0.8}px`;
}

function resetGoogleWave() {
    if (!gBars) return;
    gBars.forEach((b) => { b.style.height = '6px'; });
}

// ============================================================
// Google Gemini Live Audio Pipeline (Real-Time Full-Duplex <800ms)
// ============================================================
let liveWs = null;
let isGeminiLiveMode = false;
let pcmAudioCtx = null;
let scheduledPcmTime = 0;
let activePcmSources = [];
let micRecordProcessor = null;
let liveMicStream = null;

function initPcmPlayer() {
    if (!pcmAudioCtx) {
        pcmAudioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 24000 });
    }
    if (pcmAudioCtx.state === 'suspended') {
        pcmAudioCtx.resume();
    }
}

function stopAndClearPcmPlayback() {
    activePcmSources.forEach((s) => {
        try { s.stop(); s.disconnect(); } catch (e) {}
    });
    activePcmSources = [];
    if (pcmAudioCtx) {
        scheduledPcmTime = pcmAudioCtx.currentTime;
    }
    resetGoogleWave();
}

function playPcmChunk(base64Pcm) {
    initPcmPlayer();
    try {
        const binaryStr = atob(base64Pcm);
        const len = binaryStr.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binaryStr.charCodeAt(i);
        }
        const int16 = new Int16Array(bytes.buffer);
        const numSamples = int16.length;

        const audioBuffer = pcmAudioCtx.createBuffer(1, numSamples, 24000);
        const channelData = audioBuffer.getChannelData(0);
        let sum = 0;
        for (let i = 0; i < numSamples; i++) {
            const val = int16[i] / 32768.0;
            channelData[i] = val;
            sum += Math.abs(val);
        }

        const avgEnergy = sum / numSamples;
        animateGoogleWave(avgEnergy * 80);
        voiceOrb.style.transform = `scale(${1 + avgEnergy * 0.4})`;

        const source = pcmAudioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(pcmAudioCtx.destination);

        const now = pcmAudioCtx.currentTime;
        if (scheduledPcmTime < now) {
            scheduledPcmTime = now;
        }
        source.start(scheduledPcmTime);
        scheduledPcmTime += audioBuffer.duration;

        activePcmSources.push(source);
        source.onended = () => {
            const idx = activePcmSources.indexOf(source);
            if (idx > -1) activePcmSources.splice(idx, 1);
            if (activePcmSources.length === 0) {
                resetGoogleWave();
                voiceOrb.style.transform = 'scale(1)';
                if (voiceState === 'SPEAKING') {
                    setVoiceState('LISTENING');
                }
            }
        };
    } catch (e) {
        console.error('PCM play error:', e);
    }
}

async function startLiveMicCapture() {
    try {
        liveMicStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                sampleRate: 16000,
                channelCount: 1,
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
            },
        });

        const micCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        const source = micCtx.createMediaStreamSource(liveMicStream);
        const processor = micCtx.createScriptProcessor(2048, 1, 1);

        processor.onaudioprocess = (e) => {
            if (!liveWs || liveWs.readyState !== WebSocket.OPEN) return;
            const inputData = e.inputBuffer.getChannelData(0);

            let sum = 0;
            const int16 = new Int16Array(inputData.length);
            for (let i = 0; i < inputData.length; i++) {
                const s = Math.max(-1, Math.min(1, inputData[i]));
                int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
                sum += Math.abs(s);
            }
            const avg = sum / inputData.length;

            if (voiceState === 'LISTENING') {
                animateGoogleWave(avg * 100);
                voiceOrb.style.transform = `scale(${1 + avg * 0.5})`;
            }

            const uint8 = new Uint8Array(int16.buffer);
            let binary = '';
            for (let i = 0; i < uint8.byteLength; i++) {
                binary += String.fromCharCode(uint8[i]);
            }
            const base64Chunk = btoa(binary);

            liveWs.send(JSON.stringify({
                type: 'audio_chunk',
                data: base64Chunk,
            }));
        };

        source.connect(processor);
        processor.connect(micCtx.destination);
        micRecordProcessor = { ctx: micCtx, processor, source };
    } catch (err) {
        console.error('Live mic capture failed:', err);
        toast('Microphone access denied', 'err');
        exitVoiceMode();
    }
}

function stopLiveMicCapture() {
    if (micRecordProcessor) {
        try {
            micRecordProcessor.processor.disconnect();
            micRecordProcessor.source.disconnect();
            micRecordProcessor.ctx.close();
        } catch (e) {}
        micRecordProcessor = null;
    }
    if (liveMicStream) {
        liveMicStream.getTracks().forEach((t) => t.stop());
        liveMicStream = null;
    }
}

function formatToolAction(name, args) {
    if (name === 'check_emails') return 'Checking your inbox…';
    if (name === 'read_email') return 'Reading email…';
    if (name === 'smart_open') return `Opening ${args.target || 'app'}…`;
    if (name === 'play_music') return `Playing ${args.query || 'music'}…`;
    if (name === 'execute_command') return `Running: ${args.command || 'terminal'}…`;
    if (name === 'web_search') return `Searching: ${args.query || 'web'}…`;
    return `Running ${name}…`;
}

function connectGeminiLive() {
    const LIVE_WS_URL = 'ws://127.0.0.1:8000/ws/live';
    $('voice-engine-text').textContent = 'Connecting Gemini…';
    $('voice-engine-badge').classList.remove('hidden');
    $('voice-state-label').textContent = 'Connecting Google Assistant…';

    liveWs = new WebSocket(LIVE_WS_URL);

    liveWs.onopen = () => {
        console.log('[GeminiLive] Connected to bridge');
    };

    liveWs.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === 'session_ready') {
                isGeminiLiveMode = true;
                $('voice-engine-text').textContent = `Google Assistant · ${data.voice}`;
                $('voice-engine-badge').classList.remove('hidden');
                setVoiceState('LISTENING');
                startLiveMicCapture();
            } else if (data.type === 'audio') {
                setVoiceState('SPEAKING');
                $('voice-action-pill').classList.add('hidden');
                playPcmChunk(data.data);
            } else if (data.type === 'text_chunk') {
                voiceResponse.textContent += data.text;
            } else if (data.type === 'interrupted') {
                console.log('[GeminiLive] Interrupted by user speech');
                stopAndClearPcmPlayback();
                setVoiceState('LISTENING');
            } else if (data.type === 'tool_executing') {
                $('voice-action-pill').classList.remove('hidden');
                $('voice-action-text').textContent = formatToolAction(data.name, data.args || {});
            } else if (data.type === 'turn_complete') {
                $('voice-action-pill').classList.add('hidden');
            } else if (data.type === 'error') {
                toast(data.message, 'err');
                if (data.code === 'NO_API_KEY') {
                    fallbackToOfflineVoice();
                } else {
                    exitVoiceMode();
                }
            }
        } catch (e) {
            console.error('Live WS error:', e);
        }
    };

    liveWs.onclose = () => {
        if (isGeminiLiveMode) {
            stopLiveMicCapture();
            stopAndClearPcmPlayback();
            isGeminiLiveMode = false;
        }
    };

    liveWs.onerror = (err) => {
        console.error('Gemini Live WS connection failed:', err);
        fallbackToOfflineVoice();
    };
}

// ============================================================
// Voice mode — state machine: INACTIVE | LISTENING | PROCESSING | SPEAKING
// ============================================================
let voiceState = 'INACTIVE';
let voiceInteractionMode = prefs.voiceMode;

let micStream = null;
let vadAudioCtx = null;
let vadAnalyser = null;
let mediaRecorder = null;
let audioChunks = [];
let isSpeaking = false;
let silenceTimer = null;
let vadCheckRunning = false;
let recordingStartTime = 0;
let vadAnimationFrameId = null;
let pttActive = false;

function setVoiceState(newState) {
    voiceState = newState;
    voiceOrb.classList.remove('idle', 'listening', 'processing', 'speaking');
    voiceStateLabel.classList.remove('listening', 'processing', 'speaking');
    voiceOverlay.classList.remove('listening', 'processing', 'speaking');

    if (newState !== 'INACTIVE') {
        voiceOverlay.classList.add(newState.toLowerCase());
    }

    switch (newState) {
        case 'INACTIVE':
            voiceOrb.classList.add('idle');
            voiceStateLabel.textContent = 'Tap to start speaking';
            resetGoogleWave();
            break;
        case 'LISTENING':
            voiceOrb.classList.add('listening');
            voiceStateLabel.classList.add('listening');
            voiceStateLabel.textContent = voiceInteractionMode === 'hands-free' ? 'Listening…' : 'Hold Space to speak';
            break;
        case 'PROCESSING':
            voiceOrb.classList.add('processing');
            voiceStateLabel.classList.add('processing');
            voiceStateLabel.textContent = 'Thinking…';
            break;
        case 'SPEAKING':
            voiceOrb.classList.add('speaking');
            voiceStateLabel.classList.add('speaking');
            voiceStateLabel.textContent = 'Speaking…';
            break;
    }
}

function resumeListening() {
    if (voiceState === 'INACTIVE') return;
    setVoiceState('LISTENING');
    if (!isGeminiLiveMode && voiceInteractionMode === 'hands-free') {
        isSpeaking = false;
        vadCheckRunning = true;
        runVADLoop();
    }
}

function applyVoiceModeLabel() {
    modeLabel.textContent = voiceInteractionMode === 'hands-free' ? 'Hands-free' : 'Push-to-talk';
    voiceModeToggle.classList.toggle('active', voiceInteractionMode === 'push-to-talk');
    $('setting-voice-mode').value = voiceInteractionMode;
}

function enterVoiceMode() {
    voiceOverlay.classList.remove('hidden');
    voiceTranscript.textContent = '';
    voiceResponse.textContent = '';
    $('voice-action-pill').classList.add('hidden');
    if (window.electronAPI) window.electronAPI.setVoiceModeActive(true);

    if (aiState.hasKey && aiState.provider === 'gemini') {
        connectGeminiLive();
    } else {
        fallbackToOfflineVoice();
    }
}

function fallbackToOfflineVoice() {
    isGeminiLiveMode = false;
    $('voice-engine-text').textContent = 'Offline (Ollama)';
    $('voice-engine-badge').classList.remove('hidden');
    setVoiceState('LISTENING');
    startMicAndVAD();
    if (!aiState.hasKey) {
        toast('Using offline voice. Add a free Google Gemini key in Settings for real-time speech!', 'info');
    }
}

function exitVoiceMode() {
    voiceOverlay.classList.add('hidden');
    voiceOverlay.classList.remove('speaking', 'listening', 'processing');
    setVoiceState('INACTIVE');
    if (window.electronAPI) window.electronAPI.setVoiceModeActive(false);

    if (isGeminiLiveMode) {
        stopLiveMicCapture();
        stopAndClearPcmPlayback();
        if (liveWs) {
            try { liveWs.close(); } catch (e) {}
            liveWs = null;
        }
        isGeminiLiveMode = false;
    } else {
        stopMicAndVAD();
        interruptPlayback();
    }
    resetGoogleWave();
}

voiceBtn.addEventListener('click', () => enterVoiceMode());
voiceCloseBtn.addEventListener('click', () => exitVoiceMode());

async function startMicAndVAD() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
                sampleRate: 48000,
                channelCount: 1,
            },
        });

        vadAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const vadSource = vadAudioCtx.createMediaStreamSource(micStream);
        vadAnalyser = vadAudioCtx.createAnalyser();
        vadAnalyser.fftSize = 512;
        vadAnalyser.smoothingTimeConstant = 0.1;
        vadSource.connect(vadAnalyser);

        vadCheckRunning = true;
        if (voiceInteractionMode === 'hands-free') runVADLoop();
    } catch (err) {
        console.error('Microphone access failed:', err);
        exitVoiceMode();
        toast('Microphone access denied or unavailable', 'err');
    }
}

function stopMicAndVAD() {
    vadCheckRunning = false;
    isSpeaking = false;
    clearTimeout(silenceTimer);
    stopRecording();
    if (micStream) {
        micStream.getTracks().forEach((track) => track.stop());
        micStream = null;
    }
    if (vadAudioCtx) {
        vadAudioCtx.close();
        vadAudioCtx = null;
    }
    vadAnalyser = null;
}

function runVADLoop() {
    if (!vadCheckRunning || !vadAnalyser) return;
    if (vadAnimationFrameId) cancelAnimationFrame(vadAnimationFrameId);
    vadAnimationFrameId = requestAnimationFrame(runVADLoop);

    // Don't start recording if AI is speaking or thinking
    if (voiceState === 'SPEAKING' || voiceState === 'PROCESSING') return;

    const bufferLength = vadAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    vadAnalyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 0; i < bufferLength; i++) sum += dataArray[i];
    const average = sum / bufferLength;

    if (voiceState === 'LISTENING' && isSpeaking) {
        voiceOrb.style.transform = `scale(${1 + average / 200})`;
    }

    const threshold = 20;
    if (average > threshold) {
        if (!isSpeaking) {
            isSpeaking = true;
            startRecording();
        }
        clearTimeout(silenceTimer);
        silenceTimer = setTimeout(() => {
            if (isSpeaking) {
                isSpeaking = false;
                finishRecordingAndSend();
            }
        }, 1800); // 1.8 seconds of silence ends the turn
    }
}

function startRecording() {
    if (!micStream) return;
    audioChunks = [];
    recordingStartTime = Date.now();
    try {
        mediaRecorder = new MediaRecorder(micStream, { mimeType: 'audio/webm' });
    } catch (e) {
        mediaRecorder = new MediaRecorder(micStream);
    }
    mediaRecorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunks.push(event.data);
    };
    mediaRecorder.start();
    setVoiceState('LISTENING');
}

function stopRecording() {
    if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
}

function finishRecordingAndSend() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;

    mediaRecorder.onstop = () => {
        const recordingDuration = Date.now() - recordingStartTime;
        // Reject recordings shorter than 700ms — likely noise, not speech
        if (audioChunks.length === 0 || recordingDuration < 700) {
            resumeListening();
            return;
        }

        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const reader = new FileReader();
        reader.readAsDataURL(audioBlob);
        reader.onloadend = () => {
            const base64data = reader.result.split(',')[1];
            if (ws && ws.readyState === WebSocket.OPEN) {
                if (isPlayingAudio || voiceState === 'SPEAKING') {
                    interruptPlayback();
                    sendInterrupt();
                }
                ws.send(JSON.stringify({ type: 'voice_input', data: base64data }));
                setVoiceState('PROCESSING');
                voiceOrb.style.transform = 'scale(1)';
            } else {
                toast('Not connected to the Igris backend', 'err');
                resumeListening();
            }
        };
    };
    mediaRecorder.stop();
}

// Push-to-talk
document.addEventListener('keydown', (e) => {
    if (voiceState === 'INACTIVE' || voiceInteractionMode !== 'push-to-talk') return;
    if (e.code === 'Space' && !e.repeat && !pttActive) {
        e.preventDefault();
        pttActive = true;
        if (voiceState === 'SPEAKING') {
            interruptPlayback();
            sendInterrupt();
        }
        startRecording();
    }
});
document.addEventListener('keyup', (e) => {
    if (voiceState === 'INACTIVE' || voiceInteractionMode !== 'push-to-talk') return;
    if (e.code === 'Space' && pttActive) {
        e.preventDefault();
        pttActive = false;
        finishRecordingAndSend();
    }
});

voiceInterruptBtn.addEventListener('click', () => {
    if (voiceState === 'SPEAKING' || voiceState === 'PROCESSING') {
        interruptPlayback();
        sendInterrupt();
        setVoiceState('LISTENING');
    }
});

// Hands-free barge-in: speak while AI is talking
let interruptAnimationFrameId = null;
let interruptSpeechStartTime = 0;
let interruptDetectionActive = false;

function startInterruptDetection() {
    if (interruptDetectionActive) return;
    interruptDetectionActive = true;
    interruptSpeechStartTime = 0;
    checkInterruptWhileSpeaking();
}

function stopInterruptDetection() {
    interruptDetectionActive = false;
    interruptSpeechStartTime = 0;
    if (interruptAnimationFrameId) {
        cancelAnimationFrame(interruptAnimationFrameId);
        interruptAnimationFrameId = null;
    }
}

function checkInterruptWhileSpeaking() {
    if (!interruptDetectionActive) return;
    if (!vadAnalyser || voiceInteractionMode !== 'hands-free') { interruptDetectionActive = false; return; }

    interruptAnimationFrameId = requestAnimationFrame(checkInterruptWhileSpeaking);
    if (voiceState !== 'SPEAKING') return;

    const bufferLength = vadAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    vadAnalyser.getByteFrequencyData(dataArray);
    let sum = 0;
    for (let i = 0; i < bufferLength; i++) sum += dataArray[i];
    const average = sum / bufferLength;

    // Higher threshold than normal VAD to cut through speaker bleed-through.
    const interruptThreshold = 50;
    if (average > interruptThreshold) {
        if (interruptSpeechStartTime === 0) interruptSpeechStartTime = Date.now();
    } else {
        interruptSpeechStartTime = 0;
    }

    // Require ~250ms of sustained speech to trigger an interrupt.
    if (interruptSpeechStartTime > 0 && Date.now() - interruptSpeechStartTime >= 250) {
        interruptSpeechStartTime = 0;
        stopInterruptDetection();
        interruptPlayback();
        sendInterrupt();
        setVoiceState('LISTENING');
        isSpeaking = true;
        startRecording();
        vadCheckRunning = true;
        runVADLoop();
    }
}

function setVoiceInteractionMode(mode) {
    voiceInteractionMode = mode;
    prefs.voiceMode = mode;
    applyVoiceModeLabel();
    if (mode === 'push-to-talk') {
        vadCheckRunning = false;
    } else {
        vadCheckRunning = true;
        if (voiceState === 'LISTENING') runVADLoop();
    }
    if (voiceState === 'LISTENING') setVoiceState('LISTENING');
}

voiceModeToggle.addEventListener('click', () => {
    setVoiceInteractionMode(voiceInteractionMode === 'hands-free' ? 'push-to-talk' : 'hands-free');
});

// ============================================================
// Inbox (IMAP)
// ============================================================
const inboxState = {
    filter: 'all',
    search: '',
    messages: [],
    loadedOnce: false,
    loading: false,
    configured: null,
    selectedUid: null,
    unread: 0,
    requestId: 0,
};

const inboxList = $('inbox-list');
const inboxTable = $('inbox-table');
const inboxEmpty = $('inbox-empty');
const inboxAccount = $('inbox-account');
const emailPeek = $('email-peek');
const peekBody = $('peek-body');

const AVATAR_COLORS = ['#9a6b4f', '#c77d48', '#c29343', '#4f9768', '#447acb', '#865db6', '#ba4a78', '#be524b', '#787774'];
function avatarColor(seed) {
    let h = 0;
    for (let i = 0; i < seed.length; i++) h = (h * 31 + seed.charCodeAt(i)) >>> 0;
    return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function formatEmailDate(iso, fallback) {
    if (!iso) return fallback || '';
    const d = new Date(iso);
    if (isNaN(d.getTime())) return fallback || '';
    const now = new Date();
    if (d.toDateString() === now.toDateString()) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    const yesterday = new Date(now);
    yesterday.setDate(now.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    if (d.getFullYear() === now.getFullYear()) {
        return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' });
}

function setInboxBadge(count) {
    inboxState.unread = count;
    inboxBadge.textContent = count > 99 ? '99+' : String(count);
    inboxBadge.classList.toggle('hidden', !count);
}

async function refreshInboxBadge() {
    try {
        const settings = await api('/api/email/settings');
        inboxState.configured = settings.configured;
        if (!settings.configured) {
            setInboxBadge(0);
            return;
        }
        const res = await api('/api/email/messages?unread_only=true&limit=1');
        if (res.ok) setInboxBadge(res.unread_count || 0);
    } catch (e) {
        /* backend not ready yet */
    }
}

function renderInboxSkeleton() {
    inboxTable.classList.remove('hidden');
    inboxEmpty.classList.add('hidden');
    inboxList.innerHTML = Array.from({ length: 7 }).map(() => `
        <div class="db-row skeleton-row">
            <div class="col-from"><div class="sk" style="width:70%"></div></div>
            <div class="col-subject"><div class="sk" style="width:${50 + Math.random() * 40}%"></div></div>
            <div class="col-date"><div class="sk" style="width:60%"></div></div>
        </div>`).join('');
}

function renderInboxEmpty({ icon, title, text, actionLabel, action }) {
    inboxTable.classList.add('hidden');
    inboxEmpty.classList.remove('hidden');
    inboxEmpty.innerHTML = `
        <div class="empty-icon">${icon}</div>
        <h3></h3>
        <p></p>
        ${actionLabel ? '<button class="btn btn-primary" id="inbox-empty-action"></button>' : ''}`;
    inboxEmpty.querySelector('h3').textContent = title;
    inboxEmpty.querySelector('p').textContent = text;
    if (actionLabel) {
        const btn = $('inbox-empty-action');
        btn.textContent = actionLabel;
        btn.addEventListener('click', action);
    }
}

function renderInboxRows() {
    const msgs = inboxState.messages;
    if (!msgs.length) {
        renderInboxEmpty({
            icon: inboxState.filter === 'unread' ? '✨' : '📭',
            title: inboxState.search ? 'No matching emails' : (inboxState.filter === 'unread' ? 'All caught up' : 'Inbox is empty'),
            text: inboxState.search ? 'Try a different search term.' : (inboxState.filter === 'unread' ? 'You have no unread email.' : 'Nothing here yet.'),
        });
        return;
    }
    inboxTable.classList.remove('hidden');
    inboxEmpty.classList.add('hidden');
    inboxList.innerHTML = '';

    msgs.forEach((m) => {
        const row = document.createElement('div');
        row.className = `db-row${m.unread ? ' unread' : ''}${m.uid === inboxState.selectedUid ? ' selected' : ''}`;
        row.dataset.uid = m.uid;
        const name = m.from_name || m.from_email || 'Unknown';
        row.innerHTML = `
            <div class="col-from">
                ${m.unread ? '<span class="unread-dot"></span>' : ''}
                <span class="sender-avatar"></span>
                <span class="sender-name"></span>
            </div>
            <div class="col-subject">
                <div class="subject-line"></div>
                <div class="snippet-line"></div>
            </div>
            <div class="col-date"></div>`;
        const avatar = row.querySelector('.sender-avatar');
        avatar.textContent = name.trim().charAt(0).toUpperCase() || '?';
        avatar.style.background = avatarColor(m.from_email || name);
        row.querySelector('.sender-name').textContent = name;
        row.querySelector('.sender-name').title = m.from_email || '';
        row.querySelector('.subject-line').textContent = m.subject;
        row.querySelector('.snippet-line').textContent = m.snippet || '';
        row.querySelector('.col-date').textContent = formatEmailDate(m.date_iso, m.date);
        row.addEventListener('click', () => openEmail(m.uid));
        inboxList.appendChild(row);
    });
}

async function loadInbox() {
    const reqId = ++inboxState.requestId;
    inboxState.loading = true;
    inboxState.loadedOnce = true;
    renderInboxSkeleton();

    try {
        const params = new URLSearchParams({
            unread_only: inboxState.filter === 'unread' ? 'true' : 'false',
            limit: '40',
            search: inboxState.search,
        });
        const res = await api(`/api/email/messages?${params}`);
        if (reqId !== inboxState.requestId) return;

        inboxState.configured = res.configured;
        if (!res.configured) {
            inboxAccount.textContent = 'Connect your email so Igris can check it for you.';
            setInboxBadge(0);
            renderInboxEmpty({
                icon: '✉️',
                title: 'Connect your email',
                text: 'Add your mailbox using an IMAP app password. Igris will show your inbox here and can check, read and summarize your email when you ask.',
                actionLabel: 'Connect email',
                action: () => openSettings('email'),
            });
            return;
        }

        inboxAccount.textContent = res.email_address
            ? `${res.email_address} · ${res.unread_count || 0} unread`
            : 'Your email, summarized by Igris.';
        setInboxBadge(res.unread_count || 0);

        if (!res.ok) {
            renderInboxEmpty({
                icon: '⚠️',
                title: 'Couldn’t load your inbox',
                text: res.error || 'Unknown error.',
                actionLabel: 'Try again',
                action: loadInbox,
            });
            return;
        }
        inboxState.messages = res.messages || [];
        renderInboxRows();
    } catch (e) {
        if (reqId !== inboxState.requestId) return;
        renderInboxEmpty({
            icon: '🔌',
            title: 'Backend unavailable',
            text: 'Igris couldn’t reach its local backend. Make sure it is running, then try again.',
            actionLabel: 'Retry',
            action: loadInbox,
        });
    } finally {
        if (reqId === inboxState.requestId) inboxState.loading = false;
    }
}

document.querySelectorAll('.db-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.db-tab').forEach((t) => t.classList.toggle('active', t === tab));
        inboxState.filter = tab.dataset.filter;
        loadInbox();
    });
});

let searchDebounce = null;
$('inbox-search').addEventListener('input', (e) => {
    clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
        inboxState.search = e.target.value.trim();
        loadInbox();
    }, 450);
});
$('inbox-refresh').addEventListener('click', loadInbox);

// AI briefing for the whole inbox
$('inbox-summarize').addEventListener('click', async () => {
    if (inboxState.configured === false) {
        openSettings('email');
        return;
    }
    const btn = $('inbox-summarize');
    const callout = $('inbox-summary');
    const content = $('inbox-summary-content');
    btn.disabled = true;
    callout.classList.remove('hidden');
    content.innerHTML = '<span class="thinking-text">Reading your inbox…</span>';
    try {
        const res = await api('/api/email/summarize', {
            method: 'POST',
            body: JSON.stringify({ unread_only: inboxState.filter === 'unread', limit: 8 }),
        });
        content.innerHTML = res.ok ? renderMarkdown(res.summary) : `<p>${escapeHtml(res.error || 'Summary failed.')}</p>`;
    } catch (e) {
        content.innerHTML = '<p>Could not reach the Igris backend.</p>';
    } finally {
        btn.disabled = false;
    }
});
$('inbox-summary-close').addEventListener('click', () => $('inbox-summary').classList.add('hidden'));

// ---------- Side peek ----------
function closePeek() {
    emailPeek.classList.add('hidden');
    inboxState.selectedUid = null;
    document.querySelectorAll('.db-row.selected').forEach((r) => r.classList.remove('selected'));
}
$('peek-close').addEventListener('click', closePeek);

async function openEmail(uid) {
    inboxState.selectedUid = uid;
    document.querySelectorAll('.db-row').forEach((r) => r.classList.toggle('selected', r.dataset.uid === uid));
    emailPeek.classList.remove('hidden');
    peekBody.innerHTML = '<div class="peek-title"><span class="thinking-text">Loading email…</span></div>';

    try {
        const res = await api(`/api/email/messages/${encodeURIComponent(uid)}?mark_read=true`);
        if (inboxState.selectedUid !== uid) return;
        if (!res.ok) {
            peekBody.innerHTML = '';
            const err = document.createElement('div');
            err.className = 'empty-state';
            err.innerHTML = '<div class="empty-icon">⚠️</div><h3>Couldn’t open this email</h3><p></p>';
            err.querySelector('p').textContent = res.error || 'Unknown error.';
            peekBody.appendChild(err);
            return;
        }
        renderEmailPeek(res.email);

        // Reflect read state locally
        const local = inboxState.messages.find((m) => m.uid === uid);
        if (local && local.unread) {
            local.unread = false;
            setInboxBadge(Math.max(0, inboxState.unread - 1));
            const row = inboxList.querySelector(`.db-row[data-uid="${CSS.escape(uid)}"]`);
            if (row) {
                row.classList.remove('unread');
                const dot = row.querySelector('.unread-dot');
                if (dot) dot.remove();
            }
        }
    } catch (e) {
        peekBody.innerHTML = '<div class="empty-state"><h3>Backend unavailable</h3></div>';
    }
}

function renderEmailPeek(em) {
    peekBody.innerHTML = `
        <div class="peek-title"></div>
        <div class="props">
            <div class="prop"><div class="prop-key">◉ From</div><div class="prop-val" data-k="from"></div></div>
            <div class="prop"><div class="prop-key">→ To</div><div class="prop-val" data-k="to"></div></div>
            <div class="prop"><div class="prop-key">◷ Received</div><div class="prop-val" data-k="date"></div></div>
            <div class="prop hidden" data-k="att-row"><div class="prop-key">📎 Files</div><div class="prop-val" data-k="att"></div></div>
        </div>
        <div class="callout hidden" id="peek-summary">
            <div class="callout-icon">✦</div>
            <div class="callout-body"><div class="callout-title">AI summary</div><div class="md" id="peek-summary-content"></div></div>
        </div>
        <div class="email-body"></div>`;

    peekBody.querySelector('.peek-title').textContent = em.subject;
    const fromEl = peekBody.querySelector('[data-k="from"]');
    fromEl.textContent = em.from_name;
    if (em.from_email && em.from_email !== em.from_name) {
        const addr = document.createElement('span');
        addr.className = 'muted';
        addr.textContent = `  <${em.from_email}>`;
        fromEl.appendChild(addr);
    }
    peekBody.querySelector('[data-k="to"]').textContent = em.to || '—';
    peekBody.querySelector('[data-k="date"]').textContent = em.date_iso
        ? new Date(em.date_iso).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
        : em.date;

    if (em.attachments && em.attachments.length) {
        peekBody.querySelector('[data-k="att-row"]').classList.remove('hidden');
        const attEl = peekBody.querySelector('[data-k="att"]');
        em.attachments.forEach((a) => {
            const chip = document.createElement('span');
            chip.className = 'attachment-chip';
            chip.textContent = a.filename;
            attEl.appendChild(chip);
        });
    }
    peekBody.querySelector('.email-body').textContent = em.body;
    peekBody.scrollTop = 0;
}

$('peek-summarize').addEventListener('click', async () => {
    const uid = inboxState.selectedUid;
    if (!uid) return;
    const callout = $('peek-summary');
    const content = $('peek-summary-content');
    if (!callout) return;
    callout.classList.remove('hidden');
    content.innerHTML = '<span class="thinking-text">Summarizing…</span>';
    try {
        const res = await api('/api/email/summarize', { method: 'POST', body: JSON.stringify({ uid }) });
        if (inboxState.selectedUid !== uid) return;
        content.innerHTML = res.ok ? renderMarkdown(res.summary) : `<p>${escapeHtml(res.error || 'Summary failed.')}</p>`;
    } catch (e) {
        content.innerHTML = '<p>Could not reach the Igris backend.</p>';
    }
});

$('peek-ask').addEventListener('click', () => {
    const uid = inboxState.selectedUid;
    if (!uid) return;
    const local = inboxState.messages.find((m) => m.uid === uid);
    const subject = local ? local.subject : '';
    switchView('chat');
    userInput.value = `Read email UID ${uid}${subject ? ` ("${subject}")` : ''} and suggest a short reply.`;
    autoResize();
    updateSendState();
    userInput.focus();
});

// ============================================================
// Settings modal
// ============================================================
const settingsModal = $('settings-modal');
const emailForm = $('email-form');
const emailProvider = $('email-provider');
const emailAddress = $('email-address');
const emailPassword = $('email-password');
const emailHost = $('email-host');
const emailPort = $('email-port');
const emailStatus = $('email-form-status');

const aiForm = $('ai-form');
const aiProvider = $('ai-provider');
const geminiApiKey = $('gemini-api-key');
const geminiVoice = $('gemini-voice');
const aiStatus = $('ai-form-status');
const aiTestBtn = $('ai-test-btn');
const aiSaveBtn = $('ai-save-btn');

function setAiStatus(text, kind) {
    if (!text) {
        aiStatus.classList.add('hidden');
        return;
    }
    aiStatus.className = `form-status ${kind}`;
    aiStatus.textContent = text;
}

if (aiProvider) {
    aiProvider.addEventListener('change', () => {
        const isGemini = aiProvider.value === 'gemini';
        if ($('gemini-key-field')) $('gemini-key-field').classList.toggle('hidden', !isGemini);
        if ($('gemini-voice-field')) $('gemini-voice-field').classList.toggle('hidden', !isGemini);
    });
}

if (aiTestBtn) {
    aiTestBtn.addEventListener('click', async () => {
        aiTestBtn.disabled = true;
        setAiStatus('Validating Google Gemini API key…', 'info');
        try {
            const res = await api('/api/ai/test', {
                method: 'POST',
                body: JSON.stringify({ api_key: geminiApiKey ? geminiApiKey.value.trim() : '' }),
            });
            setAiStatus(res.message || (res.ok ? '✓ Google Gemini API key is valid!' : 'Validation failed.'), res.ok ? 'ok' : 'err');
        } catch (e) {
            setAiStatus('Could not reach the Igris backend.', 'err');
        } finally {
            aiTestBtn.disabled = false;
        }
    });
}

if (aiForm) {
    aiForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        if (aiSaveBtn) aiSaveBtn.disabled = true;
        setAiStatus('Saving Cloud AI configuration…', 'info');
        try {
            const keyVal = geminiApiKey ? geminiApiKey.value.trim() : '';
            const payload = {
                provider: aiProvider ? aiProvider.value : 'gemini',
                voice: geminiVoice ? geminiVoice.value : 'Aoede',
                model: 'gemini-2.0-flash',
            };
            if (keyVal) payload.api_key = keyVal;
            const res = await api('/api/ai/settings', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            if (res.ok) {
                setAiStatus(res.message || 'AI settings saved.', 'ok');
                aiState.provider = res.settings.provider;
                aiState.hasKey = res.settings.has_key;
                aiState.voice = res.settings.voice;
                aiState.model = res.settings.model;
                if (geminiApiKey) {
                    geminiApiKey.value = '';
                    geminiApiKey.placeholder = res.settings.has_key ? '•••••••••••• (saved)' : 'AIzaSy...';
                }
                toast('Cloud AI configured', 'ok');
            } else {
                setAiStatus(res.message || 'Failed to save settings.', 'err');
            }
        } catch (e) {
            setAiStatus('Could not reach the Igris backend.', 'err');
        } finally {
            if (aiSaveBtn) aiSaveBtn.disabled = false;
        }
    });
}

const PROVIDER_HELP = {
    gmail: 'Gmail needs 2-Step Verification turned on and a 16-character <a data-href="https://myaccount.google.com/apppasswords">App password</a>. Your normal Google password won’t work.',
    outlook: 'Use an app password from your <a data-href="https://account.microsoft.com/security">Microsoft account security</a> page. Note: many Outlook.com and Microsoft 365 accounts now block password-based IMAP sign-in.',
    icloud: 'Generate an app-specific password at <a data-href="https://appleid.apple.com">appleid.apple.com</a> → Sign-In and Security.',
    yahoo: 'Generate an app password in <a data-href="https://login.yahoo.com/account/security">Yahoo Account Security</a>.',
    custom: 'Enter your provider’s IMAP server details. SSL/TLS on port 993 is used.',
};

function switchSettingsTab(tab) {
    document.querySelectorAll('.modal-nav-item').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab));
    document.querySelectorAll('.settings-tab').forEach((p) => p.classList.toggle('active', p.dataset.tabPanel === tab));
}
document.querySelectorAll('.modal-nav-item').forEach((b) => b.addEventListener('click', () => switchSettingsTab(b.dataset.tab)));

function setEmailStatus(text, kind) {
    if (!text) {
        emailStatus.classList.add('hidden');
        return;
    }
    emailStatus.className = `form-status ${kind}`;
    emailStatus.textContent = text;
}

function updateProviderUI() {
    const p = emailProvider.value;
    $('email-custom-fields').classList.toggle('hidden', p !== 'custom');
    $('email-provider-help').innerHTML = PROVIDER_HELP[p] || '';
}
emailProvider.addEventListener('change', updateProviderUI);

function renderConnectedCard(settings) {
    const card = $('email-connected-card');
    if (settings && settings.configured) {
        card.classList.remove('hidden');
        $('email-connected-avatar').textContent = (settings.email_address || '@').charAt(0).toUpperCase();
        $('email-connected-address').textContent = settings.email_address;
        $('email-connected-meta').textContent = `Connected via IMAP · ${settings.imap_host}`;
        $('email-save').textContent = 'Update';
    } else {
        card.classList.add('hidden');
        $('email-save').textContent = 'Connect';
    }
}

async function loadEmailSettings() {
    setEmailStatus('', '');
    try {
        const s = await api('/api/email/settings');
        emailProvider.value = s.provider || 'gmail';
        emailAddress.value = s.email_address || '';
        emailPassword.value = '';
        emailPassword.placeholder = s.has_password ? '•••••••••••• (saved)' : 'xxxx xxxx xxxx xxxx';
        if (s.provider === 'custom') {
            emailHost.value = s.imap_host || '';
            emailPort.value = s.imap_port || 993;
        }
        renderConnectedCard(s);
    } catch (e) {
        setEmailStatus('Could not reach the Igris backend.', 'err');
    }
    updateProviderUI();
}

function emailPayload() {
    return {
        provider: emailProvider.value,
        email_address: emailAddress.value.trim(),
        app_password: emailPassword.value,
        imap_host: emailProvider.value === 'custom' ? emailHost.value.trim() : '',
        imap_port: Number(emailPort.value) || 993,
    };
}

$('email-test').addEventListener('click', async () => {
    const btn = $('email-test');
    btn.disabled = true;
    setEmailStatus('Testing connection…', 'info');
    try {
        const res = await api('/api/email/test', { method: 'POST', body: JSON.stringify(emailPayload()) });
        setEmailStatus(res.message || (res.ok ? 'Connection successful.' : 'Connection failed.'), res.ok ? 'ok' : 'err');
    } catch (e) {
        setEmailStatus('Could not reach the Igris backend.', 'err');
    } finally {
        btn.disabled = false;
    }
});

emailForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = $('email-save');
    btn.disabled = true;
    setEmailStatus('Connecting to your mailbox…', 'info');
    try {
        const res = await api('/api/email/settings', { method: 'POST', body: JSON.stringify(emailPayload()) });
        if (res.ok) {
            setEmailStatus(res.message || 'Email connected.', 'ok');
            emailPassword.value = '';
            emailPassword.placeholder = '•••••••••••• (saved)';
            renderConnectedCard(res.settings);
            inboxState.configured = true;
            setInboxBadge(res.unread_count || 0);
            toast('Email connected', 'ok');
            if (currentView === 'inbox' || inboxState.loadedOnce) loadInbox();
        } else {
            setEmailStatus(res.message || 'Could not connect.', 'err');
        }
    } catch (err) {
        setEmailStatus('Could not reach the Igris backend.', 'err');
    } finally {
        btn.disabled = false;
    }
});

$('email-disconnect').addEventListener('click', async () => {
    if (!confirm('Disconnect this email account from Igris? Saved credentials will be removed.')) return;
    try {
        await api('/api/email/settings', { method: 'DELETE' });
        inboxState.configured = false;
        inboxState.messages = [];
        setInboxBadge(0);
        closePeek();
        await loadEmailSettings();
        setEmailStatus('Email disconnected.', 'info');
        if (inboxState.loadedOnce) loadInbox();
    } catch (e) {
        setEmailStatus('Could not reach the Igris backend.', 'err');
    }
});

$('setting-speak').addEventListener('change', (e) => {
    prefs.speak = e.target.checked;
    applySpeakPref();
});
$('setting-voice-mode').addEventListener('change', (e) => setVoiceInteractionMode(e.target.value));
$('setting-clear-history').addEventListener('click', () => {
    if (!confirm('Permanently delete all chat history?')) return;
    newChat();
    closeSettings();
});

function openSettings(tab = 'ai') {
    settingsModal.classList.remove('hidden');
    switchSettingsTab(tab);
    loadAiSettings();
    loadEmailSettings();
    applySpeakPref();
    applyVoiceModeLabel();
}
function closeSettings() {
    settingsModal.classList.add('hidden');
}
settingsModal.querySelectorAll('[data-close-modal]').forEach((el) => el.addEventListener('click', closeSettings));

// ============================================================
// Global keyboard shortcuts
// ============================================================
document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;

    if (e.key === 'Escape') {
        if (voiceState !== 'INACTIVE') { exitVoiceMode(); return; }
        if (!settingsModal.classList.contains('hidden')) { closeSettings(); return; }
        if (!emailPeek.classList.contains('hidden')) { closePeek(); return; }
        if (isGenerating) { stopGenerating(); return; }
    }
    if (mod && e.key === ',') { e.preventDefault(); openSettings(); }
    if (mod && e.key === '\\') { e.preventDefault(); setSidebarCollapsed(!document.body.classList.contains('sidebar-collapsed')); }
    if (mod && e.shiftKey && (e.key === 'O' || e.key === 'o')) { e.preventDefault(); newChat(); }
});

// ============================================================
// Init
// ============================================================
window.addEventListener('DOMContentLoaded', () => {
    setSidebarCollapsed(prefs.sidebarCollapsed);
    applySpeakPref();
    applyVoiceModeLabel();
    setVoiceState('INACTIVE');
    updateHasMessages();
    updateSendState();
    loadAiSettings();
    connectWebSocket();
    userInput.focus();
    // Refresh unread badge periodically
    setInterval(refreshInboxBadge, 3 * 60 * 1000);
});
