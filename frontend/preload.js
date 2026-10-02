const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    toggleMiniMode: (enable) => ipcRenderer.send('toggle-mini-mode', enable),
    setVoiceModeActive: (active) => ipcRenderer.send('voice-mode-active', active),
    openSandboxBrowser: (url) => ipcRenderer.send('open-sandbox-browser', url),
});
