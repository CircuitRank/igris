const { app, BrowserWindow, globalShortcut, Tray, Menu, ipcMain, nativeImage, screen, shell } = require('electron')
const path = require('node:path')

let mainWindow = null;
let tray = null;
let isMiniMode = false;

function createWindow () {
  const iconPath = path.join(__dirname, 'icon.png');
  mainWindow = new BrowserWindow({
    width: 1060,
    height: 820,
    minWidth: 420,
    minHeight: 480,
    icon: iconPath,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      preload: path.join(__dirname, 'preload.js')
    },
    backgroundColor: '#191919',
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#202020',
      symbolColor: '#9c9c9c',
      height: 44
    }
  })

  mainWindow.loadFile('index.html')
  
  // Prevent default close behavior to keep it in tray
  mainWindow.on('close', (event) => {
    if (!app.isQuiting) {
      event.preventDefault();
      mainWindow.hide();
    }
    return false;
  });
}

function createTray() {
  const iconPath = path.join(__dirname, 'icon.png');
  let icon = nativeImage.createFromPath(iconPath);
  if (!icon.isEmpty()) {
    icon = icon.resize({ width: 16, height: 16 });
  } else {
    icon = nativeImage.createEmpty();
  }

  tray = new Tray(icon);
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show/Hide Igris', click: toggleWindow },
    { type: 'separator' },
    { label: 'Quit', click: () => {
        app.isQuiting = true;
        app.quit();
      } 
    }
  ]);
  tray.setToolTip('Igris AI Assistant');
  tray.setContextMenu(contextMenu);
  tray.on('click', toggleWindow);
}

function toggleWindow() {
  if (mainWindow.isVisible()) {
    mainWindow.hide();
  } else {
    mainWindow.show();
    mainWindow.focus();
  }
}

app.whenReady().then(() => {
  createWindow()
  createTray()

  // Register Global Hotkey
  globalShortcut.register('CommandOrControl+Space', () => {
    toggleWindow();
  })

  app.on('activate', function () {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
})

app.on('window-all-closed', function () {
  if (process.platform !== 'darwin') app.quit()
})

// IPC Handlers for Mini Mode
ipcMain.on('toggle-mini-mode', (event, enable) => {
  if (!mainWindow) return;
  
  isMiniMode = enable;
  if (enable) {
    mainWindow.setAlwaysOnTop(true, 'floating');
    mainWindow.setSize(380, 520);
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width, height } = primaryDisplay.workAreaSize;
    mainWindow.setPosition(width - 400, height - 550);
  } else {
    mainWindow.setAlwaysOnTop(false);
    mainWindow.setSize(1060, 820);
    mainWindow.center();
  }
})

// IPC Handler for Voice Mode — keep on top during voice conversation
ipcMain.on('voice-mode-active', (event, active) => {
  if (!mainWindow || isMiniMode) return;
  if (active) {
    mainWindow.setAlwaysOnTop(true, 'floating');
  } else {
    mainWindow.setAlwaysOnTop(false);
  }
})

ipcMain.on('open-external', (event, url) => {
  if (typeof url === 'string' && (url.startsWith('http://') || url.startsWith('https://') || url.startsWith('mailto:'))) {
    shell.openExternal(url);
  }
})

ipcMain.on('open-sandbox-browser', (event, url) => {
  const sandboxWin = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: true,
      partition: 'sandbox_temp_' + Date.now()
    }
  });
  sandboxWin.loadURL(url);
});
