const { app, BrowserWindow, Menu, Tray, ipcMain, screen, nativeImage, session, globalShortcut } = require('electron');
const fs = require('fs');
const path = require('path');

const isDevelopment = !app.isPackaged;
const startupLogPath = path.join(__dirname, 'tmp', 'electron-startup.log');
function startupLog(message) {
  try {
    fs.mkdirSync(path.dirname(startupLogPath), { recursive: true });
    fs.appendFileSync(
      startupLogPath,
      `${new Date().toISOString()} ${message}\n`,
      'utf8'
    );
  } catch (_) {
    // Logging must never prevent the desktop character from starting.
  }
}
startupLog(`main.js loaded; packaged=${app.isPackaged}; argv=${JSON.stringify(process.argv)}`);
process.on('uncaughtException', (error) => {
  startupLog(`uncaughtException: ${error && error.stack ? error.stack : error}`);
});
process.on('unhandledRejection', (error) => {
  startupLog(`unhandledRejection: ${error && error.stack ? error.stack : error}`);
});

let basePath;
if (isDevelopment) {
  basePath = __dirname;
} else {
  basePath = path.join(process.resourcesPath, 'app.asar.unpacked');
}
console.log('Base path is:', basePath);

let mainWindow;
let tray = null;
let contextMenu;
let currentConfigFile = '';
let configFiles = [];
const isMac = process.platform === 'darwin';
const hasSingleInstanceLock = app.requestSingleInstanceLock();

if (!hasSingleInstanceLock) {
  startupLog('second instance rejected');
  app.quit();
} else {
  app.on('second-instance', () => {
    startupLog('second-instance event; showing existing window');
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore();
      mainWindow.show();
      mainWindow.moveTop();
    }
  });
}


function updateContextMenu() {
  const configMenuItems = configFiles.map(configFile => {
    return {
      label: configFile,
      type: 'radio',
      checked: configFile === currentConfigFile,
      click: () => switchConfig(configFile)
    };
  });

  contextMenu = Menu.buildFromTemplate([
    { label: 'Show Subtitles', type: 'checkbox', checked: false, click: (menuItem) => toggleSubtitles(menuItem.checked) },
    { label: 'Microphone', type: 'checkbox', checked: true, click: (menuItem) => toggleMicrophone(menuItem.checked) },
    { label: 'Allow Interruption', type: 'checkbox', checked: false, click: (menuItem) => toggleInterruption(menuItem.checked) },
    { label: 'Wake-up', type: 'checkbox', checked: false, click: (menuItem) => toggleWakeUp(menuItem.checked) },
    { label: 'Hide', type: 'checkbox', checked: false, click: (menuItem) => toggleMinimize(menuItem.checked) },
    {
      label: 'Speech Sensitivity',
      submenu: [
        { label: 'Very High (70%)', type: 'radio', checked: false, click: () => setSensitivity(0.7) },
        { label: 'High (80%)', type: 'radio', checked: false, click: () => setSensitivity(0.8) },
        { label: 'Medium (90%)', type: 'radio', checked: true, click: () => setSensitivity(0.9) },
        { label: 'Low (95%)', type: 'radio', checked: false, click: () => setSensitivity(0.95) },
        { label: 'Very Low (99%)', type: 'radio', checked: false, click: () => setSensitivity(0.99) }
      ]
    },
    {
      label: 'Switch Config',
      submenu: configMenuItems
    },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ]);

  if (tray) {
    tray.setContextMenu(contextMenu);
  }
}

function createWindow() {
  startupLog('createWindow started');
  const { width, height } = screen.getPrimaryDisplay().workAreaSize;

  // Use a smaller window that doesn't block the entire screen
  const winWidth = 500;
  const winHeight = 700;

  mainWindow = new BrowserWindow({
    width: winWidth,
    height: winHeight,
    x: width - winWidth - 20,
    y: height - winHeight,
    transparent: true,
    frame: false,
    resizable: false,
    alwaysOnTop: true,
    skipTaskbar: false,
    hasShadow: false,
    focusable: true,
    acceptFirstMouse: true,
    backgroundColor: '#00000000',
    webPreferences: {
      preload: path.join(basePath, 'static', 'desktop', 'preload.js'),
      contextIsolation: true,
      nodeIntegration: true,
      enableRemoteModule: true,
      sandbox: false,
    },
  });

  mainWindow.webContents.on('did-finish-load', () => {
    startupLog('desktop.html did-finish-load');
    if (!mainWindow || mainWindow.isDestroyed()) return;
    mainWindow.setPosition(width - winWidth - 20, height - winHeight);
    mainWindow.show();
    mainWindow.setAlwaysOnTop(true, 'screen-saver');
    mainWindow.moveTop();
    startupLog(`window shown; bounds=${JSON.stringify(mainWindow.getBounds())}`);
  });
  mainWindow.webContents.on('did-fail-load', (_event, code, description) => {
    startupLog(`desktop.html did-fail-load: ${code} ${description}`);
  });
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    startupLog(`render-process-gone: ${JSON.stringify(details)}`);
  });

  mainWindow.loadFile(path.join(basePath, 'static', 'desktop.html'));
  startupLog('desktop.html load requested');
  // mainWindow.webContents.openDevTools();

  if (isMac) mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  if (isMac) mainWindow.setIgnoreMouseEvents(true);

  mainWindow.setAlwaysOnTop(true, 'normal');

  // Register global shortcuts for window control
  globalShortcut.register('CommandOrControl+Shift+H', () => {
    if (mainWindow.isVisible()) {
      mainWindow.hide();
      console.log('Character hidden. Press Ctrl+Shift+H to show.');
    } else {
      mainWindow.show();
      console.log('Character shown.');
    }
  });
  globalShortcut.register('CommandOrControl+Shift+Q', () => {
    app.quit();
  });
  console.log('Shortcuts: Ctrl+Shift+H = Hide/Show, Ctrl+Shift+Q = Quit');

  mainWindow.on('closed', function () {
    startupLog('main window closed');
    mainWindow = null;
  });

  createTray();
  startupLog('createWindow completed');
}

function createTray() {
  let iconPath = path.join(basePath, 'static', 'pictures', 'icon.png');
  let trayIcon;

  if (isMac) {
    trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 });
    tray = new Tray(trayIcon);
  } else {
    tray = new Tray(iconPath);
  }
  tray.setToolTip('Elaina');

  if (!contextMenu) {
    updateContextMenu();
  } else {
    tray.setContextMenu(contextMenu);
  }
}


function toggleSubtitles(isChecked) {
  mainWindow.webContents.send('toggle-subtitles', isChecked);
}

function toggleMicrophone(isChecked) {
  mainWindow.webContents.send('toggle-microphone', isChecked);
}

function toggleInterruption(isChecked) {
  mainWindow.webContents.send('toggle-interruption', isChecked);
}

function toggleWakeUp(isChecked) {
  mainWindow.webContents.send('toggle-wake-up', isChecked);
}

function toggleMinimize(isChecked) {
  if (isChecked) {
    mainWindow.minimize();
  } else {
    mainWindow.restore();
    mainWindow.setAlwaysOnTop(true, 'screen-saver');
  }
}

function switchConfig(configFile) {
  currentConfigFile = configFile;
  mainWindow.webContents.send('switch-config', configFile);
}

function setSensitivity(value) {
  mainWindow.webContents.send('set-sensitivity', value);
}

app.on('ready', () => {
  startupLog('app ready');

  // Grant microphone permission for voice input
  session.defaultSession.setPermissionRequestHandler((webContents, permission, callback) => {
    const allowedPermissions = ['media', 'microphone', 'audio'];
    if (allowedPermissions.includes(permission)) {
      callback(true);
    } else {
      callback(false);
    }
  });

  // Also bypass permission checks for media
  session.defaultSession.setPermissionCheckHandler((webContents, permission, requestingOrigin) => {
    const allowedPermissions = ['media', 'microphone', 'audio'];
    return allowedPermissions.includes(permission);
  });

  createWindow();
});

app.on('window-all-closed', function () {
  startupLog('window-all-closed');
  if (!isMac) {
    app.quit();
  }
});

app.on('activate', function () {
  if (mainWindow === null) {
    createWindow();
  }
});

app.on('will-quit', () => {
  startupLog('will-quit');
  globalShortcut.unregisterAll();
});

ipcMain.on('set-ignore-mouse-events', (event, ignore) => {
  if (isMac) mainWindow.setIgnoreMouseEvents(ignore);
  else mainWindow.setIgnoreMouseEvents(ignore, { forward: true });
});

ipcMain.on('show-context-menu', (event, x, y) => {
  contextMenu.popup({
    window: mainWindow,
    x: x,
    y: y,
  });
});

ipcMain.on('update-menu-checked', (event, label, checked) => {
  const menuItem = contextMenu.items.find(item => item.label === label);
  if (menuItem) {
    menuItem.checked = checked;
    Menu.setApplicationMenu(Menu.buildFromTemplate(contextMenu.items));
    tray.setContextMenu(contextMenu);
  }
});

ipcMain.on('update-config-files', (event, files) => {
  configFiles = files;
  updateContextMenu();
});

ipcMain.on('update-sensitivity', (event, value) => {
  const sensitivityMenu = contextMenu.items.find(item => item.label === 'Speech Sensitivity');
  if (sensitivityMenu) {
    const threshold = value * 100;
    sensitivityMenu.submenu.items.forEach(item => {
      item.checked = item.label.includes(`(${threshold}%)`);
    });
  }
});

ipcMain.handle('get-clipboard-content', async () => {
    const content = {};
    const { clipboard } = require('electron');
    
    try {
        content.text = clipboard.readText() || '';
        
        const image = clipboard.readImage();
        if (!image.isEmpty()) {
            const scaledImage = image.resize({
                width: 800,
                height: 800,
                quality: 'good'
            });
            content.image = scaledImage.toPNG().toString('base64');
        } else {
            content.image = null;
        }
    } catch (error) {
        console.error('Error getting clipboard content:', error);
        content.text = '';
        content.image = null;
    }
    
    return content;
});
