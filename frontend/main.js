const { app, BrowserWindow, globalShortcut, Tray, Menu, ipcMain, nativeImage, screen } = require('electron')
const path = require('node:path')

let mainWindow = null;
let tray = null;
let isMiniMode = false;

function createWindow () {
  mainWindow = new BrowserWindow({
    width: 1000,
    height: 800,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: false
    },
    backgroundColor: '#050510',
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#050510',
      symbolColor: '#00f3ff'
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
  const icon = nativeImage.createEmpty();
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
    mainWindow.setSize(350, 400);
    const primaryDisplay = screen.getPrimaryDisplay();
    const { width, height } = primaryDisplay.workAreaSize;
    mainWindow.setPosition(width - 370, height - 420);
  } else {
    mainWindow.setAlwaysOnTop(false);
    mainWindow.setSize(1000, 800);
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
