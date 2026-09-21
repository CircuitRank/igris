const { ipcRenderer } = require('electron');

// ============================================================
// DOM Elements
// ============================================================
const chatContainer = document.getElementById('chat-container');
const userInput = document.getElementById('user-input');
const miniModeBtn = document.getElementById('mini-mode-btn');
const sendBtn = document.getElementById('send-btn');
const orb = document.getElementById('igris-orb');
const stateText = document.getElementById('state-text');
const statusMessage = document.getElementById('status-message');
const pingMetric = document.getElementById('ping-metric');

// Voice overlay elements
const voiceOverlay = document.getElementById('voice-overlay');
const voiceOrb = document.getElementById('voice-orb');
const voiceStateLabel = document.getElementById('voice-state-label');
const voiceTranscript = document.getElementById('voice-transcript');
const voiceResponse = document.getElementById('voice-response');
const voiceBtn = document.getElementById('voice-btn');
const voiceCloseBtn = document.getElementById('voice-close-btn');
const voiceModeToggle = document.getElementById('voice-mode-toggle');
const voiceInterruptBtn = document.getElementById('voice-interrupt-btn');
const modeLabel = document.getElementById('mode-label');

// ============================================================
// State
// ============================================================
let ws = null;
let currentStreamContentSpan = null;

// Voice state machine: INACTIVE | LISTENING | PROCESSING | SPEAKING
let voiceState = 'INACTIVE';
let voiceInteractionMode = 'hands-free'; // 'hands-free' | 'push-to-talk'

// Audio playback
let audioQueue = [];
let isPlayingAudio = false;
let currentAudio = null;

// Mic & VAD
let micStream = null;
let vadAudioCtx = null;
let vadAnalyser = null;
let mediaRecorder = null;
let audioChunks = [];
let isSpeaking = false;
let silenceTimer = null;
let vadCheckRunning = false;
let recordingStartTime = 0; // Track when recording started

// Audio visualizer for TTS playback
let audioCtx = null;
let analyser = null;

// Push-to-talk state
let pttActive = false;

// ============================================================
// Mini Mode
// ============================================================
miniModeBtn.addEventListener('click', () => {
    const isMini = document.body.classList.toggle('mini-mode');
    ipcRenderer.send('toggle-mini-mode', isMini);
    miniModeBtn.textContent = isMini ? 'MAX' : 'MINI';
});

// ============================================================
// Audio Visualizer (for TTS playback → orb reaction)
// ============================================================
function initVisualizer(audioElement) {
    if (!audioCtx) {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
    }
    try {
        const source = audioCtx.createMediaElementSource(audioElement);
        source.connect(analyser);
        analyser.connect(audioCtx.destination);
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
    for (let i = 0; i < dataArray.length; i++) {
        sum += dataArray[i];
    }
    let average = sum / dataArray.length;
    let scale = 1 + (average / 300);
    voiceOrb.style.transform = `scale(${scale})`;
}

function animateMainOrb() {
    if (!isPlayingAudio || !analyser) {
        orb.style.transform = 'scale(1)';
        return;
    }
    requestAnimationFrame(animateMainOrb);
    const dataArray = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(dataArray);

    let sum = 0;
    for (let i = 0; i < dataArray.length; i++) {
        sum += dataArray[i];
    }
    let average = sum / dataArray.length;
    let scale = 1 + (average / 256);
    orb.style.transform = `scale(${scale})`;
}

// ============================================================
// Voice State Machine
// ============================================================
function setVoiceState(newState) {
    voiceState = newState;

    // Remove all state classes from voice orb
    voiceOrb.classList.remove('idle', 'listening', 'processing', 'speaking');
    voiceStateLabel.classList.remove('listening', 'processing', 'speaking');

    switch (newState) {
        case 'INACTIVE':
            voiceOrb.classList.add('idle');
            voiceStateLabel.textContent = 'Tap to start speaking';
            break;

        case 'LISTENING':
            voiceOrb.classList.add('listening');
            voiceStateLabel.classList.add('listening');
            if (voiceInteractionMode === 'hands-free') {
                voiceStateLabel.textContent = 'Listening...';
            } else {
                voiceStateLabel.textContent = 'Hold Space to speak';
            }
            break;

        case 'PROCESSING':
            voiceOrb.classList.add('processing');
            voiceStateLabel.classList.add('processing');
            voiceStateLabel.textContent = 'Processing...';
            break;

        case 'SPEAKING':
            voiceOrb.classList.add('speaking');
            voiceStateLabel.classList.add('speaking');
            voiceStateLabel.textContent = 'Speaking...';
            break;
    }
}

// ============================================================
// Voice Mode Activation / Deactivation
// ============================================================
function enterVoiceMode() {
    voiceOverlay.classList.remove('hidden');
    voiceTranscript.textContent = '';
    voiceResponse.textContent = '';
    setVoiceState('LISTENING');
    startMicAndVAD();
}

function exitVoiceMode() {
    voiceOverlay.classList.add('hidden');
    setVoiceState('INACTIVE');
    stopMicAndVAD();
    interruptPlayback();
}

voiceBtn.addEventListener('click', () => enterVoiceMode());
voiceCloseBtn.addEventListener('click', () => exitVoiceMode());

// ============================================================
// Mic & VAD (Voice Activity Detection)
// ============================================================
async function startMicAndVAD() {
    try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true });

        vadAudioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const vadSource = vadAudioCtx.createMediaStreamSource(micStream);
        vadAnalyser = vadAudioCtx.createAnalyser();
        vadAnalyser.fftSize = 512;
        vadAnalyser.smoothingTimeConstant = 0.1;
        vadSource.connect(vadAnalyser);

        vadCheckRunning = true;
        if (voiceInteractionMode === 'hands-free') {
            runVADLoop();
        }
    } catch (err) {
        console.error('Microphone access failed:', err);
        exitVoiceMode();
        alert('Microphone access denied or unavailable.');
    }
}

function stopMicAndVAD() {
    vadCheckRunning = false;
    isSpeaking = false;
    clearTimeout(silenceTimer);
    stopRecording();

    if (micStream) {
        micStream.getTracks().forEach(track => track.stop());
        micStream = null;
    }
    if (vadAudioCtx) {
        vadAudioCtx.close();
        vadAudioCtx = null;
    }
}

let vadAnimationFrameId = null;

function runVADLoop() {
    if (!vadCheckRunning || !vadAnalyser) return;
    if (vadAnimationFrameId) cancelAnimationFrame(vadAnimationFrameId);
    vadAnimationFrameId = requestAnimationFrame(runVADLoop);

    // Don't start recording if AI is speaking
    if (voiceState === 'SPEAKING' || voiceState === 'PROCESSING') return;

    const bufferLength = vadAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    vadAnalyser.getByteFrequencyData(dataArray);

    let sum = 0;
    for (let i = 0; i < bufferLength; i++) sum += dataArray[i];
    let average = sum / bufferLength;

    // Also drive the voice orb scale while listening
    if (voiceState === 'LISTENING' && isSpeaking) {
        let micScale = 1 + (average / 200);
        voiceOrb.style.transform = `scale(${micScale})`;
    }

    const threshold = 30;
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
        }, 2500); // 2.5 seconds of silence ends the turn
    }
}

// ============================================================
// Recording
// ============================================================
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
    if (mediaRecorder && mediaRecorder.state !== 'inactive') {
        mediaRecorder.stop();
    }
}

function finishRecordingAndSend() {
    if (!mediaRecorder || mediaRecorder.state === 'inactive') return;

    mediaRecorder.onstop = () => {
        const recordingDuration = Date.now() - recordingStartTime;
        
        // Reject recordings shorter than 700ms — likely noise, not speech
        if (audioChunks.length === 0 || recordingDuration < 700) {
            console.log(`[VAD] Discarding short recording: ${recordingDuration}ms`);
            setVoiceState('LISTENING');
            // Restart VAD loop
            if (voiceInteractionMode === 'hands-free') {
                vadCheckRunning = true;
                runVADLoop();
            }
            return;
        }

        const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
        const reader = new FileReader();
        reader.readAsDataURL(audioBlob);
        reader.onloadend = () => {
            const base64data = reader.result.split(',')[1];
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'voice_input', data: base64data }));
                setVoiceState('PROCESSING');
                voiceOrb.style.transform = 'scale(1)';
            }
        };
    };

    mediaRecorder.stop();
}

// ============================================================
// Push-to-Talk
// ============================================================
document.addEventListener('keydown', (e) => {
    if (voiceState === 'INACTIVE') return;
    if (voiceInteractionMode !== 'push-to-talk') return;
    if (e.code === 'Space' && !e.repeat && !pttActive) {
        e.preventDefault();
        pttActive = true;
        // Interrupt if AI is speaking
        if (voiceState === 'SPEAKING') {
            interruptPlayback();
            sendInterrupt();
        }
        startRecording();
    }
});

document.addEventListener('keyup', (e) => {
    if (voiceState === 'INACTIVE') return;
    if (voiceInteractionMode !== 'push-to-talk') return;
    if (e.code === 'Space' && pttActive) {
        e.preventDefault();
        pttActive = false;
        finishRecordingAndSend();
    }
});

// ============================================================
// Interrupt
// ============================================================
function interruptPlayback() {
    audioQueue = [];
    if (currentAudio) {
        currentAudio.pause();
        currentAudio.currentTime = 0;
        currentAudio = null;
    }
    isPlayingAudio = false;
    voiceOrb.style.transform = 'scale(1)';
    orb.style.transform = 'scale(1)';
}

function sendInterrupt() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'interrupt' }));
    }
}

voiceInterruptBtn.addEventListener('click', () => {
    if (voiceState === 'SPEAKING' || voiceState === 'PROCESSING') {
        interruptPlayback();
        sendInterrupt();
        setVoiceState('LISTENING');
    }
});

// ============================================================
// Hands-free Interrupt: speak while AI is talking
// ============================================================
let interruptAnimationFrameId = null;

function checkInterruptWhileSpeaking() {
    if (!vadCheckRunning || !vadAnalyser) return;
    if (voiceState !== 'SPEAKING') return;
    if (voiceInteractionMode !== 'hands-free') return;

    if (interruptAnimationFrameId) cancelAnimationFrame(interruptAnimationFrameId);
    interruptAnimationFrameId = requestAnimationFrame(checkInterruptWhileSpeaking);

    const bufferLength = vadAnalyser.frequencyBinCount;
    const dataArray = new Uint8Array(bufferLength);
    vadAnalyser.getByteFrequencyData(dataArray);

    let sum = 0;
    for (let i = 0; i < bufferLength; i++) sum += dataArray[i];
    let average = sum / bufferLength;

    // Threshold lowered so user doesn't have to yell to interrupt
    if (average > 35) {
        interruptPlayback();
        sendInterrupt();
        setVoiceState('LISTENING');
        // Restart VAD recording loop
        isSpeaking = false;
        runVADLoop();
    }
}

// ============================================================
// Mode Toggle (Hands-free ↔ Push-to-Talk)
// ============================================================
voiceModeToggle.addEventListener('click', () => {
    if (voiceInteractionMode === 'hands-free') {
        voiceInteractionMode = 'push-to-talk';
        modeLabel.textContent = 'PUSH-TO-TALK';
        voiceModeToggle.classList.add('active');
        // Stop VAD loop
        vadCheckRunning = false;
        if (voiceState === 'LISTENING') {
            setVoiceState('LISTENING'); // Update label
        }
    } else {
        voiceInteractionMode = 'hands-free';
        modeLabel.textContent = 'HANDS-FREE';
        voiceModeToggle.classList.remove('active');
        // Restart VAD loop
        vadCheckRunning = true;
        if (voiceState === 'LISTENING') {
            setVoiceState('LISTENING');
            runVADLoop();
        }
    }
});

// ============================================================
// Audio Playback Queue
// ============================================================
function playNextAudio() {
    if (audioQueue.length === 0) {
        isPlayingAudio = false;
        voiceOrb.style.transform = 'scale(1)';
        orb.style.transform = 'scale(1)';

        // If in voice mode, transition back to listening after speaking finishes
        if (voiceState === 'SPEAKING') {
            setVoiceState('LISTENING');
            if (voiceInteractionMode === 'hands-free') {
                isSpeaking = false;
                vadCheckRunning = true;
                runVADLoop();
            }
        }
        return;
    }

    isPlayingAudio = true;
    const base64Audio = audioQueue.shift();

    currentAudio = new Audio('data:audio/mp3;base64,' + base64Audio);

    currentAudio.onplay = () => {
        initVisualizer(currentAudio);
        if (voiceState !== 'INACTIVE') {
            animateVoiceOrb();
            // Start checking for interrupt via voice
            checkInterruptWhileSpeaking();
        } else {
            animateMainOrb();
        }
    };

    currentAudio.onended = () => {
        playNextAudio();
    };
    currentAudio.onerror = (e) => {
        console.error('Audio playback error', e);
        playNextAudio();
    };
    currentAudio.play().catch(e => {
        console.error('Audio play failed', e);
        playNextAudio();
    });
}

// ============================================================
// WebSocket Connection
// ============================================================
function connectWebSocket() {
    appendMessage('SYSTEM', 'Connecting to core...', 'system-msg');

    ws = new WebSocket('ws://127.0.0.1:8000/ws/chat');

    ws.onopen = () => {
        appendMessage('SYSTEM', 'Connection to core established.', 'system-msg');
        setAssistantState('idle', 'Awaiting Input...');

        setInterval(() => {
            const randomPing = Math.floor(Math.random() * 15) + 5;
            pingMetric.textContent = `PING: ${randomPing}ms`;
        }, 3000);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);

            if (data.type === 'status') {
                setAssistantState('thinking', data.content);
            } else if (data.type === 'response') {
                setAssistantState('idle', 'Awaiting Input...');
                appendMessage('IGRIS', data.content, 'igris-msg');
            } else if (data.type === 'stream_start') {
                setAssistantState('thinking', 'Processing...');
                currentStreamContentSpan = appendMessage('IGRIS', '', 'igris-msg');
            } else if (data.type === 'stream_chunk') {
                if (currentStreamContentSpan) {
                    currentStreamContentSpan.textContent += data.content;
                    chatContainer.scrollTop = chatContainer.scrollHeight;
                }
                // Also update voice response if in voice mode
                if (voiceState !== 'INACTIVE') {
                    voiceResponse.textContent += data.content;
                }
            } else if (data.type === 'stream_end') {
                setAssistantState('idle', 'Awaiting Input...');
                currentStreamContentSpan = null;
            } else if (data.type === 'transcription') {
                // Backend sent the transcribed user speech
                const text = data.text;
                voiceTranscript.textContent = `"${text}"`;
                voiceResponse.textContent = '';
                appendMessage('USER', text + ' (Voice)', 'user-msg');
            } else if (data.type === 'voice_empty') {
                // No speech detected, go back to listening
                if (voiceState === 'PROCESSING') {
                    setVoiceState('LISTENING');
                    if (voiceInteractionMode === 'hands-free') {
                        vadCheckRunning = true;
                        runVADLoop();
                    }
                }
            } else if (data.type === 'voice_error') {
                if (voiceState !== 'INACTIVE') {
                    voiceStateLabel.textContent = 'Error — try again';
                    setTimeout(() => {
                        setVoiceState('LISTENING');
                        if (voiceInteractionMode === 'hands-free') {
                            vadCheckRunning = true;
                            runVADLoop();
                        }
                    }, 1500);
                }
            } else if (data.type === 'speaking_start') {
                if (voiceState !== 'INACTIVE') {
                    setVoiceState('SPEAKING');
                }
            } else if (data.type === 'speaking_end') {
                // Audio may still be queued/playing — the actual transition
                // back to LISTENING happens when playNextAudio() exhausts the queue
            } else if (data.type === 'interrupted') {
                if (voiceState !== 'INACTIVE') {
                    setVoiceState('LISTENING');
                    if (voiceInteractionMode === 'hands-free') {
                        isSpeaking = false;
                        vadCheckRunning = true;
                        runVADLoop();
                    }
                }
            } else if (data.type === 'audio') {
                audioQueue.push(data.data);
                if (!isPlayingAudio) {
                    playNextAudio();
                }
            }
        } catch (e) {
            appendMessage('IGRIS', event.data, 'igris-msg');
        }
    };

    ws.onclose = () => {
        appendMessage('SYSTEM', 'Connection lost. Reconnecting...', 'system-msg');
        setAssistantState('offline', 'System Offline');
        setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };
}

// ============================================================
// Chat UI Helpers
// ============================================================
function appendMessage(sender, text, className) {
    const msgDiv = document.createElement('div');
    msgDiv.className = `message ${className}`;

    const senderSpan = document.createElement('span');
    senderSpan.className = 'sender';
    senderSpan.textContent = `[${sender}]:`;

    const contentSpan = document.createElement('span');
    contentSpan.className = 'content';
    contentSpan.textContent = text;

    msgDiv.appendChild(senderSpan);
    msgDiv.appendChild(contentSpan);

    chatContainer.appendChild(msgDiv);
    chatContainer.scrollTop = chatContainer.scrollHeight;

    return contentSpan;
}

function setAssistantState(state, message) {
    orb.className = 'orb'; // Reset
    if (state === 'thinking') {
        orb.classList.add('thinking');
        stateText.textContent = 'PROCESSING';
        stateText.style.color = 'var(--secondary-color)';
    } else if (state === 'idle') {
        orb.classList.add('idle');
        stateText.textContent = 'IDLE';
        stateText.style.color = 'var(--primary-color)';
    } else {
        stateText.textContent = 'OFFLINE';
        stateText.style.color = '#ff0000';
    }
    statusMessage.textContent = message;
}

function sendMessage() {
    const text = userInput.value.trim();
    if (text && ws && ws.readyState === WebSocket.OPEN) {
        appendMessage('USER', text, 'user-msg');
        ws.send(text);
        userInput.value = '';
    }
}

sendBtn.addEventListener('click', sendMessage);
userInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
});

// ============================================================
// Escape key to exit voice mode
// ============================================================
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && voiceState !== 'INACTIVE') {
        exitVoiceMode();
    }
});

// ============================================================
// Initialize
// ============================================================
window.addEventListener('DOMContentLoaded', () => {
    orb.classList.add('idle');
    connectWebSocket();
    userInput.focus();
});
