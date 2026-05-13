import { app, BrowserWindow, Tray, Menu, ipcMain, Notification, nativeImage } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'

let mainWindow: BrowserWindow | null = null
let pythonProcess: ChildProcess | null = null
let tray: Tray | null = null
let isQuitting = false

const isDev = !app.isPackaged

function getBackendDir(): string {
  if (isDev) {
    return path.join(__dirname, '..', 'backend')
  }
  return path.join(process.resourcesPath, 'backend')
}

function ensurePythonDeps(backendDir: string) {
  const venvDir = path.join(backendDir, '.venv')
  if (!fs.existsSync(path.join(venvDir, 'bin', 'python'))) {
    console.log('[Electron] Virtual env not found, using system Python')
    return false
  }
  return true
}

function getPythonCmd(backendDir: string): string {
  const venvPython = path.join(backendDir, '.venv', 'bin', 'python')
  if (fs.existsSync(venvPython)) return venvPython
  return 'python3'
}

function startPythonBackend() {
  const backendDir = getBackendDir()
  const pythonCmd = getPythonCmd(backendDir)

  pythonProcess = spawn(pythonCmd, ['-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8765'], {
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  pythonProcess.stdout?.on('data', (data: Buffer) => {
    console.log('[Python] ' + data.toString().trim())
  })
  pythonProcess.stderr?.on('data', (data: Buffer) => {
    console.log('[Python] ' + data.toString().trim())
  })

  pythonProcess.on('exit', (code: number | null) => {
    console.log('[Electron] Python process exited with code ' + code)
    if (!isQuitting && code !== 0) {
      // Auto-restart after 2 seconds
      setTimeout(() => {
        console.log('[Electron] Restarting Python backend...')
        startPythonBackend()
      }, 2000)
    }
  })

  pythonProcess.on('error', (err: Error) => {
    console.error('[Electron] Failed to start Python:', err.message)
  })
}

function createTrayIcon() {
  // Create a simple 16x16 tray icon
  const icon = nativeImage.createEmpty()
  tray = new Tray(icon)
  tray.setToolTip('LiangHua - 可转债量化交易系统')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show()
          mainWindow.focus()
        }
      },
    },
    { type: 'separator' },
    {
      label: '退出',
      click: () => {
        isQuitting = true
        app.quit()
      },
    },
  ])

  tray.setContextMenu(contextMenu)
  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    title: 'LiangHua - 可转债量化交易系统',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
    mainWindow.webContents.openDevTools()
  } else {
    mainWindow.loadFile(path.join(__dirname, '..', 'frontend', 'dist', 'index.html'))
  }

  // Hide to tray instead of closing
  mainWindow.on('close', (e) => {
    if (!isQuitting) {
      e.preventDefault()
      mainWindow?.hide()
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

// IPC handlers
ipcMain.handle('show-notification', (_event, { title, body }: { title: string; body: string }) => {
  if (Notification.isSupported()) {
    const notification = new Notification({ title, body })
    notification.show()
    notification.on('click', () => {
      if (mainWindow) {
        mainWindow.show()
        mainWindow.focus()
      }
    })
  }
})

ipcMain.handle('get-app-info', () => ({
  version: app.getVersion(),
  electronVersion: process.versions.electron,
  nodeVersion: process.versions.node,
  platform: process.platform,
  arch: process.arch,
  isDev,
}))

ipcMain.handle('restart-backend', async () => {
  if (pythonProcess) {
    pythonProcess.kill()
  }
  startPythonBackend()
})

app.whenReady().then(() => {
  startPythonBackend()
  createTrayIcon()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    } else {
      mainWindow?.show()
    }
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  isQuitting = true
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
})

app.on('will-quit', () => {
  if (tray) {
    tray.destroy()
    tray = null
  }
})
