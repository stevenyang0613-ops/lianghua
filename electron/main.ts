import { app, BrowserWindow, Tray, Menu, ipcMain, Notification, nativeImage, globalShortcut, shell, dialog, NativeImage, safeStorage } from 'electron'
// Dynamic import for electron-updater (optional dependency)
let autoUpdater: any = null
try {
  autoUpdater = require('electron-updater').autoUpdater
} catch {
  console.log('[Electron] electron-updater not available, skipping auto-update')
}
import { spawn, ChildProcess } from 'child_process'
import http from 'http'
import https from 'https'
import WebSocket from 'ws'
import crypto from 'crypto'
import path from 'path'
import fs from 'fs'

let mainWindow: BrowserWindow | null = null
let pythonProcess: ChildProcess | null = null
let tray: Tray | null = null
let isQuitting = false

const isDev = !app.isPackaged

// ---- Resource path helper ----
function getMimeType(filePath: string): string {
  const ext = path.extname(filePath).toLowerCase()
  const mime: Record<string, string> = {
    '.html': 'text/html',
    '.js': 'application/javascript',
    '.css': 'text/css',
    '.json': 'application/json',
    '.png': 'image/png',
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.gif': 'image/gif',
    '.svg': 'image/svg+xml',
    '.ico': 'image/x-icon',
    '.woff': 'font/woff',
    '.woff2': 'font/woff2',
    '.ttf': 'font/ttf',
    '.map': 'application/json',
  }
  return mime[ext] || 'application/octet-stream'
}

function resourcePath(relativePath: string): string {
  if (isDev) {
    return path.join(__dirname, '..', relativePath)
  }
  return path.join(process.resourcesPath, relativePath)
}

// App configuration
const APP_NAME = 'LiangHua - 可转债量化交易系统'
const APP_VERSION = '1.0.0'
const BACKEND_PORT = 8765
const BACKEND_HOST = '127.0.0.1'
const BACKEND_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`
const BACKEND_STARTUP_TIMEOUT = 180000
const HEALTH_CHECK_INTERVAL = 1000
const FRONTEND_PORT = 8766
const MAX_PORT_FALLBACK = 3

// Forward declaration
let restartBackend: () => void

// ---- Performance tracking ----
const perfMetrics = {
  appStartTime: Date.now(),
  backendReadyTime: 0,
  frontendLoadTime: 0,
  crashCount: 0,
  lastCrashTime: null as number | null,
}

// ---- Crash reports ----
interface CrashReport {
  timestamp: number
  type: 'renderer' | 'main' | 'backend' | 'gpu'
  message: string
  stack?: string
  appVersion: string
  electronVersion: string
  platform: string
  arch: string
  memoryUsage: NodeJS.MemoryUsage
  uptime: number
}

const crashReports: CrashReport[] = []
const MAX_CRASH_REPORTS = 50

function recordCrash(type: CrashReport['type'], message: string, stack?: string) {
  const report: CrashReport = {
    timestamp: Date.now(),
    type,
    message,
    stack,
    appVersion: APP_VERSION,
    electronVersion: process.versions.electron,
    platform: process.platform,
    arch: process.arch,
    memoryUsage: process.memoryUsage(),
    uptime: Date.now() - perfMetrics.appStartTime,
  }
  crashReports.unshift(report)
  if (crashReports.length > MAX_CRASH_REPORTS) crashReports.pop()
  perfMetrics.crashCount++
  perfMetrics.lastCrashTime = report.timestamp
}

// ---- WebSocket connection pool ----
const wsConnections = new Map<string, WebSocket>()

// ---- Child windows ----
const childWindows = new Map<number, BrowserWindow>()
let nextWindowId = 1

// ---- Resource hash tracking ----
const resourceHashes = new Map<string, string>()

function getResourceHash(filePath: string): string {
  try {
    const content = fs.readFileSync(filePath)
    return crypto.createHash('md5').update(content).digest('hex')
  } catch {
    return ''
  }
}

// ---- HTTP request handler (IPC proxy) ----
function httpRequestHandler(
  method: string,
  url: string,
  body?: any
): Promise<{ ok: boolean; status: number; data: any; error?: string }> {
  return new Promise((resolve) => {
    const timeout = 30000
    const parsedUrl = new URL(url)
    const isHttps = parsedUrl.protocol === 'https:'
    const httpModule = isHttps ? https : http

    const options: http.RequestOptions = {
      hostname: parsedUrl.hostname,
      port: parsedUrl.port || (isHttps ? 443 : 80),
      path: parsedUrl.pathname + parsedUrl.search,
      method: method.toUpperCase(),
      headers: {
        'Accept': 'application/json',
        'Content-Type': 'application/json',
      },
      timeout,
    }

    const req = httpModule.request(options, (res) => {
      let data = ''
      res.on('data', (chunk: Buffer) => { data += chunk.toString() })
      res.on('end', () => {
        let parsed: any
        try {
          parsed = JSON.parse(data)
        } catch {
          parsed = data
        }
        resolve({
          ok: res.statusCode !== undefined && res.statusCode >= 200 && res.statusCode < 300,
          status: res.statusCode || 0,
          data: parsed,
        })
      })
    })

    req.on('error', (err: Error) => {
      resolve({ ok: false, status: 0, data: null, error: err.message })
    })

    req.on('timeout', () => {
      req.destroy()
      resolve({ ok: false, status: 0, data: null, error: 'Request timeout' })
    })

    if (body && method.toUpperCase() !== 'GET') {
      req.write(JSON.stringify(body))
    }
    req.end()
  })
}

// ---- Backend health check ----
async function backendHealthcheck(): Promise<boolean> {
  const urls = [`${BACKEND_URL}/api/v1/health`, `${BACKEND_URL}/health`]
  for (const url of urls) {
    try {
      const result = await httpRequestHandler('GET', url)
      if (result.ok && ['ok', 'healthy'].includes(result.data?.status)) {
        return true
      }
    } catch {}
  }
  return false
}

// ---- Wait for backend to be ready ----
async function waitForBackend(maxWaitMs = 60000, intervalMs = 1000): Promise<boolean> {
  const start = Date.now()
  while (Date.now() - start < maxWaitMs) {
    if (await backendHealthcheck()) {
      perfMetrics.backendReadyTime = Date.now()
      return true
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return false
}

async function waitForBackendWithPort(port: number, maxWaitMs = BACKEND_STARTUP_TIMEOUT, intervalMs = HEALTH_CHECK_INTERVAL): Promise<boolean> {
  const start = Date.now()
  const urls = [
    `http://${BACKEND_HOST}:${port}/api/v1/health`,
    `http://${BACKEND_HOST}:${port}/health`
  ]
  while (Date.now() - start < maxWaitMs) {
    for (const url of urls) {
      try {
        const result = await httpRequestHandler('GET', url)
        if (result.ok && ['ok', 'healthy'].includes(result.data?.status)) {
          perfMetrics.backendReadyTime = Date.now()
          return true
        }
      } catch {}
    }
    await new Promise((r) => setTimeout(r, intervalMs))
  }
  return false
}

// ---- Health monitoring loop ----
let healthMonitorInterval: NodeJS.Timeout | null = null
let healthFailCount = 0
const HEALTH_MAX_FAILS = 3
const HEALTH_MONITOR_INTERVAL = 10000

function startHealthMonitor() {
  if (healthMonitorInterval) return

  healthMonitorInterval = setInterval(async () => {
    if (isQuitting) return
    const healthy = await backendHealthcheck()
    if (!healthy) {
      healthFailCount++
      console.log(`[HealthMonitor] Backend unhealthy (${healthFailCount}/${HEALTH_MAX_FAILS})`)
      if (healthFailCount >= HEALTH_MAX_FAILS) {
        console.log('[HealthMonitor] Max failures reached, restarting backend')
        healthFailCount = 0
        recordCrash('backend', 'Backend health check failed, auto-restarting')
        restartBackend()
      }
    } else {
      healthFailCount = 0
    }
  }, HEALTH_MONITOR_INTERVAL)
}

let frontendServer: http.Server | null = null

function startFrontendServer(frontendDir: string) {
  if (frontendServer) {
    frontendServer.close()
    frontendServer = null
  }
  frontendServer = http.createServer((req, res) => {
    const url = req.url || '/'

    if (url.startsWith('/api/')) {
      const proxyReq = http.request(
        { hostname: BACKEND_HOST, port: BACKEND_PORT, path: url, method: req.method, headers: req.headers },
        (proxyRes) => {
          res.writeHead(proxyRes.statusCode || 500, proxyRes.headers)
          proxyRes.pipe(res)
        }
      )
      proxyReq.on('error', () => { res.writeHead(502); res.end('Backend unavailable') })
      req.pipe(proxyReq)
      return
    }

    let filePath = url
    if (filePath === '/') filePath = '/index.html'
    const fullPath = path.join(frontendDir, filePath)
    try {
      let content = fs.readFileSync(fullPath, 'utf-8')
      if (filePath.endsWith('.html')) {
        content = content.replace(/\bcrossorigin(="")?\b/g, '')
      }
      res.writeHead(200, { 'Content-Type': getMimeType(fullPath) })
      res.end(content)
    } catch {
      res.writeHead(404)
      res.end('Not Found')
    }
  })

  frontendServer.on('upgrade', (req, socket, head) => {
    if ((req.url || '').startsWith('/ws')) {
      const proxyReq = http.request(
        { hostname: BACKEND_HOST, port: BACKEND_PORT, path: req.url, method: 'GET', headers: { ...req.headers, host: `${BACKEND_HOST}:${BACKEND_PORT}` } },
        (proxyRes) => { proxyRes.pipe(socket) }
      )
      proxyReq.on('upgrade', (proxyRes, proxySocket, proxyHead) => {
        socket.write(`HTTP/1.1 101 Switching Protocols\r\n${Object.entries(proxyRes.headers).map(([k, v]) => `${k}: ${v}`).join('\r\n')}\r\n\r\n`)
        proxySocket.pipe(socket)
        socket.pipe(proxySocket)
      })
      proxyReq.on('error', () => { socket.end() })
      proxyReq.end()
    }
  })

  frontendServer.listen(FRONTEND_PORT, '127.0.0.1', () => {
    console.log(`[Frontend] Server running on http://127.0.0.1:${FRONTEND_PORT} (proxy /api/* -> :${BACKEND_PORT})`)
  })
}

function stopHealthMonitor() {
  if (healthMonitorInterval) {
    clearInterval(healthMonitorInterval)
    healthMonitorInterval = null
  }
}

// ---- Create application menu ----
function createApplicationMenu() {
  const template: Electron.MenuItemConstructorOptions[] = [
    {
      label: 'LiangHua',
      submenu: [
        {
          label: '关于 LiangHua',
          click: () => {
            dialog.showMessageBox(mainWindow!, {
              type: 'info',
              title: '关于',
              message: APP_NAME,
              detail: `版本: ${APP_VERSION}\nElectron: ${process.versions.electron}\nNode.js: ${process.versions.node}\n平台: ${process.platform}`,
              buttons: ['确定'],
            })
          },
        },
        { type: 'separator' },
        {
          label: '偏好设置',
          accelerator: 'CmdOrCtrl+,',
          click: () => {
            mainWindow?.webContents.send('navigate', '/settings')
          },
        },
        { type: 'separator' },
        {
          label: '隐藏 LiangHua',
          accelerator: 'CmdOrCtrl+H',
          role: 'hide',
        },
        {
          label: '隐藏其他',
          accelerator: 'CmdOrCtrl+Shift+H',
          role: 'hideOthers',
        },
        { type: 'separator' },
        {
          label: '退出',
          accelerator: process.platform === 'darwin' ? 'Cmd+Q' : 'Alt+F4',
          click: () => {
            isQuitting = true
            app.quit()
          },
        },
      ],
    },
    {
      label: '文件',
      submenu: [
        {
          label: '刷新数据',
          accelerator: 'CmdOrCtrl+R',
          click: () => {
            mainWindow?.webContents.send('refresh-data')
          },
        },
        {
          label: '导出报告',
          accelerator: 'CmdOrCtrl+E',
          click: () => {
            mainWindow?.webContents.send('export-report')
          },
        },
      ],
    },
    {
      label: '视图',
      submenu: [
        {
          label: '首页',
          accelerator: 'CmdOrCtrl+1',
          click: () => mainWindow?.webContents.send('navigate', '/'),
        },
        {
          label: '市场行情',
          accelerator: 'CmdOrCtrl+2',
          click: () => mainWindow?.webContents.send('navigate', '/market'),
        },
        {
          label: '交易策略',
          accelerator: 'CmdOrCtrl+3',
          click: () => mainWindow?.webContents.send('navigate', '/strategies'),
        },
        {
          label: '回测分析',
          accelerator: 'CmdOrCtrl+4',
          click: () => mainWindow?.webContents.send('navigate', '/backtest'),
        },
        {
          label: '交易终端',
          accelerator: 'CmdOrCtrl+5',
          click: () => mainWindow?.webContents.send('navigate', '/trade'),
        },
        {
          label: '信号监控',
          accelerator: 'CmdOrCtrl+6',
          click: () => mainWindow?.webContents.send('navigate', '/signals'),
        },
        { type: 'separator' },
        {
          label: '重新加载',
          accelerator: 'CmdOrCtrl+Shift+R',
          click: () => mainWindow?.reload(),
        },
        {
          label: '开发者工具',
          accelerator: 'F12',
          click: () => mainWindow?.webContents.toggleDevTools(),
        },
        { type: 'separator' },
        {
          label: '实际大小',
          accelerator: 'CmdOrCtrl+0',
          click: () => mainWindow?.webContents.setZoomLevel(0),
        },
        {
          label: '放大',
          accelerator: 'CmdOrCtrl+=',
          click: () => {
            const level = mainWindow?.webContents.getZoomLevel() || 0
            mainWindow?.webContents.setZoomLevel(level + 1)
          },
        },
        {
          label: '缩小',
          accelerator: 'CmdOrCtrl+-',
          click: () => {
            const level = mainWindow?.webContents.getZoomLevel() || 0
            mainWindow?.webContents.setZoomLevel(level - 1)
          },
        },
        { type: 'separator' },
        {
          label: '全屏',
          accelerator: 'F11',
          click: () => {
            const isFullScreen = mainWindow?.isFullScreen()
            mainWindow?.setFullScreen(!isFullScreen)
          },
        },
      ],
    },
    {
      label: '工具',
      submenu: [
        {
          label: '自选股',
          accelerator: 'CmdOrCtrl+D',
          click: () => mainWindow?.webContents.send('navigate', '/watchlist'),
        },
        {
          label: '盈亏分析',
          accelerator: 'CmdOrCtrl+P',
          click: () => mainWindow?.webContents.send('navigate', '/pnl'),
        },
        {
          label: '套利计算',
          click: () => mainWindow?.webContents.send('navigate', '/arbitrage'),
        },
        {
          label: '强赎预警',
          click: () => mainWindow?.webContents.send('navigate', '/redemption'),
        },
        { type: 'separator' },
        {
          label: '性能监控',
          click: () => mainWindow?.webContents.send('navigate', '/performance'),
        },
        { type: 'separator' },
        {
          label: '重启后端服务',
          click: () => {
            restartBackend()
          },
        },
      ],
    },
    {
      label: '窗口',
      submenu: [
        {
          label: '最小化',
          accelerator: 'CmdOrCtrl+M',
          role: 'minimize',
        },
        {
          label: '关闭',
          accelerator: 'CmdOrCtrl+W',
          click: () => {
            if (mainWindow) {
              mainWindow.hide()
            }
          },
        },
        { type: 'separator' },
        {
          label: '置顶',
          click: () => {
            const isAlwaysOnTop = mainWindow?.isAlwaysOnTop()
            mainWindow?.setAlwaysOnTop(!isAlwaysOnTop)
          },
        },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '文档',
          click: () => {
            shell.openExternal('https://github.com/lianghua/docs')
          },
        },
        {
          label: '快捷键',
          accelerator: 'CmdOrCtrl+/',
          click: () => {
            dialog.showMessageBox(mainWindow!, {
              type: 'info',
              title: '快捷键',
              message: '键盘快捷键',
              detail: `Cmd/Ctrl+1-6: 切换页面
Cmd/Ctrl+R: 刷新数据
Cmd/Ctrl+E: 导出报告
Cmd/Ctrl+D: 自选股
Cmd/Ctrl+P: 盈亏分析
F12: 开发者工具
F11: 全屏`,
              buttons: ['确定'],
            })
          },
        },
        {
          label: '检查更新',
          click: () => {
            checkForUpdates()
          },
        },
      ],
    },
  ]

  const menu = Menu.buildFromTemplate(template)
  Menu.setApplicationMenu(menu)
}

// ---- Backend process management ----
let pythonRestartCount = 0
const MAX_PYTHON_RESTARTS = 5
const PYTHON_RESTART_RESET_INTERVAL = 60000

function getBackendDir(): string {
  return resourcePath('backend')
}

function getPythonCmd(backendDir: string): string {
  // 优先使用 PyInstaller 编译的二进制（根目录）
  const pyinstallerBin = path.join(backendDir, 'lianghua-backend')
  if (fs.existsSync(pyinstallerBin)) return pyinstallerBin
  // 再查 dist 子目录
  const pyinstallerBinDist = path.join(backendDir, 'dist', 'lianghua-backend')
  if (fs.existsSync(pyinstallerBinDist)) return pyinstallerBinDist
  // 开发环境回退到 .venv
  const venvPython = path.join(backendDir, '.venv', 'bin', 'python')
  if (fs.existsSync(venvPython)) return venvPython
  // 最后回退到系统 python3
  return 'python3'
}

async function startPythonBackendWithArgs(pythonCmd: string, args: string[], backendDir: string) {
  const port = parseInt(args[args.indexOf('--port') + 1])
  const available = await isPortAvailable(port)
  if (!available) {
    console.log(`[Electron] Port ${port} is not available, trying next port`)
    if (port < BACKEND_PORT + MAX_PORT_FALLBACK) {
      const nextPort = port + 1
      const newArgs = [...args]
      newArgs[args.indexOf('--port') + 1] = String(nextPort)
      startPythonBackendWithArgs(pythonCmd, newArgs, backendDir)
      return
    } else {
      console.error(`[Electron] All ports from ${BACKEND_PORT} to ${BACKEND_PORT + MAX_PORT_FALLBACK} are in use`)
      const attemptedPorts = Array.from({ length: MAX_PORT_FALLBACK }, (_, i) => BACKEND_PORT + i)
      mainWindow?.webContents.send('backend-error', {
        code: 'EADDRINUSE',
        title: '后端启动失败',
        message: `端口 ${BACKEND_PORT}-${BACKEND_PORT + MAX_PORT_FALLBACK} 全部被占用`,
        details: `请检查是否有其他应用占用了这些端口。\n\n诊断命令：\nmacOS: lsof -i :${BACKEND_PORT} -i :${BACKEND_PORT + 1} -i :${BACKEND_PORT + 2}\nWindows: netstat -ano | findstr "${BACKEND_PORT}"\n\n或尝试关闭其他占用端口的应用后重新启动。`,
        portsAttempted: attemptedPorts
      })
      return
    }
  }

  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }

  const isPyinstaller = pythonCmd.endsWith('lianghua-backend')
  console.log(`[Electron] Starting Python backend: ${pythonCmd} ${args.join(' ')}`)
  console.log(`[Electron] Backend directory: ${backendDir}`)
  pythonProcess = spawn(pythonCmd, args, {
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
      recordCrash('backend', `Python backend exited with code ${code}`)
      setTimeout(() => {
        if (pythonRestartCount < MAX_PYTHON_RESTARTS) {
          pythonRestartCount++
          console.log(`[Electron] Restarting Python backend (attempt ${pythonRestartCount}/${MAX_PYTHON_RESTARTS})...`)
          startPythonBackend()
        } else {
          console.error(`[Electron] Python backend restart limit reached (${MAX_PYTHON_RESTARTS}). Manual restart required.`)
          mainWindow?.webContents.send('backend-error', {
            title: '后端启动失败',
            message: 'Python 后端连续崩溃，已达到最大重启次数',
            details: '请检查后端配置后手动重启应用'
          })
        }
      }, 2000)
    }
  })

  pythonProcess.on('error', (err: Error) => {
    console.error('[Electron] Failed to start Python:', err.message)
    recordCrash('backend', `Failed to start Python: ${err.message}`)
    if ((err as any).code === 'EADDRINUSE') {
      const currentPort = parseInt(args[args.indexOf('--port') + 1] || String(BACKEND_PORT))
      if (currentPort < BACKEND_PORT + 3) {
        const nextPort = currentPort + 1
        console.log(`[Electron] Port ${currentPort} in use, trying ${nextPort}`)
        const newArgs = [...args]
        newArgs[args.indexOf('--port') + 1] = String(nextPort)
        startPythonBackendWithArgs(pythonCmd, newArgs, backendDir)
      } else {
        console.error(`[Electron] All ports from ${BACKEND_PORT} to ${BACKEND_PORT + MAX_PORT_FALLBACK} are in use`)
        const attemptedPorts = Array.from({ length: MAX_PORT_FALLBACK }, (_, i) => BACKEND_PORT + i)
        mainWindow?.webContents.send('backend-error', {
          code: 'EADDRINUSE',
          title: '后端启动失败',
          message: `端口 ${BACKEND_PORT}-${BACKEND_PORT + MAX_PORT_FALLBACK} 全部被占用`,
          details: `请检查是否有其他应用占用了这些端口。\n\n诊断命令：\nmacOS: lsof -i :${BACKEND_PORT} -i :${BACKEND_PORT + 1} -i :${BACKEND_PORT + 2}\nWindows: netstat -ano | findstr "${BACKEND_PORT}"\n\n或尝试关闭其他占用端口的应用后重新启动。`,
          portsAttempted: attemptedPorts
        })
      }
    }
  })

  waitForBackendWithPort(parseInt(args[args.indexOf('--port') + 1])).then((ready) => {
    if (ready) {
      console.log('[Electron] Backend is ready, notifying renderer')
      const actualPort = parseInt(args[args.indexOf('--port') + 1])
      savePreferredPort(actualPort)
      mainWindow?.webContents.send('backend-ready', { port: actualPort })
      startHealthMonitor()
    } else {
      console.error('[Electron] Backend did not become ready in time')
      mainWindow?.webContents.send('backend-error', {
        title: '后端启动超时',
        message: 'Python 后端未能在 60 秒内就绪',
        details: '请检查后端日志并手动重启'
      })
    }
  })

  setTimeout(() => { pythonRestartCount = 0 }, PYTHON_RESTART_RESET_INTERVAL)
}

function getPreferredPort(): number {
  try {
    const portFile = path.join(app.getPath('userData'), 'last-port.txt')
    if (fs.existsSync(portFile)) {
      const port = parseInt(fs.readFileSync(portFile, 'utf-8').trim())
      if (!isNaN(port) && port >= 8765 && port <= 8768) {
        console.log(`[Electron] Using preferred port from last session: ${port}`)
        return port
      }
    }
  } catch {}
  return BACKEND_PORT
}

function savePreferredPort(port: number): void {
  try {
    const portFile = path.join(app.getPath('userData'), 'last-port.txt')
    fs.writeFileSync(portFile, String(port))
    console.log(`[Electron] Saved preferred port: ${port}`)
  } catch {}
}

function isPortAvailable(port: number): Promise<boolean> {
  return new Promise((resolve) => {
    const server = http.createServer()
    server.once('error', () => { resolve(false) })
    server.once('listening', () => { try { server.close() } catch {} resolve(true) })
    server.listen(port, BACKEND_HOST)
    setTimeout(() => { try { server.close() } catch {} resolve(true) }, 1000)
  })
}

function startPythonBackend() {
  const backendDir = getBackendDir()
  const pythonCmd = getPythonCmd(backendDir)
  const preferredPort = getPreferredPort()
  const isPyinstaller = pythonCmd.endsWith('lianghua-backend')
  const args = isPyinstaller
    ? ['--host', BACKEND_HOST, '--port', String(preferredPort)]
    : ['-m', 'uvicorn', 'app.main:app', '--host', BACKEND_HOST, '--port', String(preferredPort)]
  startPythonBackendWithArgs(pythonCmd, args, backendDir)
}

// ---- Tray ----
function createTrayIcon() {
  const iconPath = resourcePath(path.join('resources', 'icons', 'tray-icon.png'))

  let trayIcon: NativeImage
  if (fs.existsSync(iconPath)) {
    trayIcon = nativeImage.createFromPath(iconPath).resize({ width: 16, height: 16 })
  } else {
    trayIcon = nativeImage.createFromNamedImage('NSStatusItem', [0, 0, 16, 16])
  }

  tray = new Tray(trayIcon)
  tray.setToolTip('LiangHua - 可转债量化交易系统')

  const contextMenu = Menu.buildFromTemplate([
    {
      label: '显示主窗口',
      click: () => {
        if (mainWindow) {
          mainWindow.show()
          mainWindow.focus()
        }
      },
    },
    { type: 'separator' },
    {
      label: '快速操作',
      enabled: false,
    },
    {
      label: '   刷新行情',
      click: () => mainWindow?.webContents.send('refresh-data'),
    },
    {
      label: '   查看自选股',
      click: () => {
        mainWindow?.show()
        mainWindow?.webContents.send('navigate', '/watchlist')
      },
    },
    {
      label: '   交易信号',
      click: () => {
        mainWindow?.show()
        mainWindow?.webContents.send('navigate', '/signals')
      },
    },
    { type: 'separator' },
    {
      label: '重启后端',
      click: () => restartBackend(),
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

  tray.on('click', () => {
    if (mainWindow) {
      if (mainWindow.isVisible() && mainWindow.isFocused()) {
        mainWindow.hide()
      } else {
        mainWindow.show()
        mainWindow.focus()
      }
    }
  })
}

// ---- Window state persistence ----
function getWindowStatePath(): string {
  return path.join(app.getPath('userData'), 'window-state.json')
}

function loadWindowState(): { width: number; height: number; x?: number; y?: number; isMaximized?: boolean } {
  const statePath = getWindowStatePath()
  try {
    if (fs.existsSync(statePath)) {
      const state = JSON.parse(fs.readFileSync(statePath, 'utf-8'))
      if (state.width && state.height) {
        return state
      }
    }
  } catch (e) {
    console.error('[Electron] Failed to load window state:', e)
  }
  return { width: 1400, height: 900 }
}

function saveWindowState() {
  if (!mainWindow) return
  try {
    const [width, height] = mainWindow.getSize()
    const [x, y] = mainWindow.getPosition()
    const statePath = getWindowStatePath()
    const state = { width, height, x, y, isMaximized: mainWindow.isMaximized() }
    fs.writeFileSync(statePath, JSON.stringify(state, null, 2))
  } catch (e) {
    console.error('[Electron] Failed to save window state:', e)
  }
}

// ---- Create main window ----
function createWindow() {
  const savedState = loadWindowState()

  mainWindow = new BrowserWindow({
    width: savedState.width,
    height: savedState.height,
    x: savedState.x,
    y: savedState.y,
    minWidth: 1024,
    minHeight: 680,
    title: APP_NAME,
    show: false,
    icon: resourcePath(path.join('resources', 'icons', 'icon.png')),
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webSecurity: !isDev,
      allowRunningInsecureContent: isDev,
    },
  })

  // Restore maximized state
  if (savedState.isMaximized) {
    mainWindow.maximize()
  }

  mainWindow.once('ready-to-show', () => {
    mainWindow?.show()
    perfMetrics.frontendLoadTime = Date.now()
    if (isDev) {
      mainWindow?.webContents.openDevTools()
    }
  })

  mainWindow.setBackgroundColor('#1a1a2e')

  if (isDev) {
    mainWindow.loadURL('http://localhost:5173')
  } else {
    mainWindow.loadURL(`http://127.0.0.1:${FRONTEND_PORT}`)
  }

  // Handle frontend loading errors
  mainWindow.webContents.on('did-fail-load', (_event, errorCode, errorDescription, validatedURL) => {
    console.error(`[Electron] Failed to load: ${validatedURL}, error: ${errorCode} - ${errorDescription}`)
    if (!isDev) {
      mainWindow?.loadURL(`data:text/html,<html><body style="background:#1a1a2e;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;font-family:sans-serif"><h1 style="color:#ff4d4f">页面加载失败</h1><p style="color:#aaa">无法加载应用页面 (错误码: ${errorCode})</p><p style="margin-top:20px"><button onclick="window.location.reload()" style="padding:10px 24px;background:#1890ff;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px">重新加载</button></p></body></html>`)
    }
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })

  // Save window state on resize/move
  mainWindow.on('resize', saveWindowState)
  mainWindow.on('move', saveWindowState)
  mainWindow.on('maximize', saveWindowState)
  mainWindow.on('unmaximize', saveWindowState)

  mainWindow.on('close', (e) => {
    saveWindowState()
    if (!isQuitting) {
      e.preventDefault()
      mainWindow?.hide()
      if (Notification.isSupported()) {
        const notification = new Notification({
          title: 'LiangHua',
          body: '应用已最小化到系统托盘',
          silent: true,
        })
        notification.show()
      }
    }
  })

  mainWindow.on('closed', () => {
    mainWindow = null
  })

  mainWindow.on('focus', () => {
    mainWindow?.webContents.send('window-focus', true)
  })

  mainWindow.on('blur', () => {
    mainWindow?.webContents.send('window-focus', false)
  })

  // Renderer crash detection
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    recordCrash('renderer', `Renderer crashed: ${details.reason}`, details.reason)
  })

  // Child process crash detection
  app.on('child-process-gone', (_event: any, details: any) => {
    recordCrash('gpu', `Child process gone: ${details.type} - ${details.reason}`)
  })
}

// ---- Register global shortcuts ----
function registerGlobalShortcuts() {
  globalShortcut.register('Alt+CommandOrControl+L', () => {
    if (mainWindow) {
      if (mainWindow.isVisible()) {
        mainWindow.hide()
      } else {
        mainWindow.show()
        mainWindow.focus()
      }
    }
  })

  globalShortcut.register('CommandOrCtrl+Shift+R', () => {
    mainWindow?.webContents.send('refresh-data')
  })
}

// ============================================================
// IPC Handlers
// ============================================================

// ---- HTTP proxy IPC handlers ----
ipcMain.handle('http-request', async (_event, method: string, url: string, body?: any) => {
  return httpRequestHandler(method, url, body)
})

ipcMain.handle('http-get', async (_event, url: string) => {
  return httpRequestHandler('GET', url)
})

ipcMain.handle('http-post', async (_event, url: string, body: any) => {
  return httpRequestHandler('POST', url, body)
})

// ---- WebSocket IPC proxy handlers ----
ipcMain.handle('ws-connect', async (_event, wsId: string, url: string) => {
  try {
    // Close existing connection for this wsId
    const existing = wsConnections.get(wsId)
    if (existing) {
      existing.close()
      wsConnections.delete(wsId)
    }

    const ws = new WebSocket(url)

    ws.on('open', () => {
      mainWindow?.webContents.send('ws-state', wsId, 'open')
    })

    ws.on('message', (data: WebSocket.Data, isBinary: boolean) => {
      mainWindow?.webContents.send('ws-message', wsId, data.toString(), isBinary)
    })

    ws.on('close', (code: number, reason: Buffer) => {
      wsConnections.delete(wsId)
      mainWindow?.webContents.send('ws-state', wsId, 'closed', code, reason.toString())
    })

    ws.on('error', (err: Error) => {
      console.error(`[WS ${wsId}] Error:`, err.message)
      mainWindow?.webContents.send('ws-state', wsId, 'error', 0, err.message)
    })

    wsConnections.set(wsId, ws)

    // Wait for connection to open or error
    return new Promise((resolve) => {
      const openHandler = () => {
        cleanup()
        resolve({ ok: true, state: 'open' })
      }
      const errorHandler = (err: Error) => {
        cleanup()
        resolve({ ok: false, state: 'error', error: err.message })
      }
      const timeoutId = setTimeout(() => {
        cleanup()
        resolve({ ok: false, state: 'timeout', error: 'Connection timeout' })
      }, 10000)

      const cleanup = () => {
        ws.removeListener('open', openHandler)
        ws.removeListener('error', errorHandler)
        clearTimeout(timeoutId)
      }

      ws.once('open', openHandler)
      ws.once('error', errorHandler)
    })
  } catch (err: any) {
    return { ok: false, state: 'error', error: err.message }
  }
})

ipcMain.handle('ws-send', async (_event, wsId: string, message: string) => {
  const ws = wsConnections.get(wsId)
  if (!ws || ws.readyState !== WebSocket.OPEN) {
    return { ok: false, error: `WebSocket ${wsId} not connected` }
  }
  try {
    ws.send(message)
    return { ok: true }
  } catch (err: any) {
    return { ok: false, error: err.message }
  }
})

ipcMain.handle('ws-close', async (_event, wsId: string) => {
  const ws = wsConnections.get(wsId)
  if (ws) {
    ws.close()
    wsConnections.delete(wsId)
  }
  return { ok: true }
})

ipcMain.handle('ws-state', async (_event, wsId: string) => {
  const ws = wsConnections.get(wsId)
  if (!ws) return { state: 'disconnected' }
  const stateMap: Record<number, string> = {
    [WebSocket.CONNECTING]: 'connecting',
    [WebSocket.OPEN]: 'open',
    [WebSocket.CLOSING]: 'closing',
    [WebSocket.CLOSED]: 'closed',
  }
  return { state: stateMap[ws.readyState] || 'unknown' }
})

// ---- Notifications ----
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

// ---- App info ----
ipcMain.handle('get-app-info', () => ({
  version: app.getVersion(),
  electronVersion: process.versions.electron,
  nodeVersion: process.versions.node,
  platform: process.platform,
  arch: process.arch,
  isDev,
}))

// ---- Safe storage (encryption) ----
ipcMain.handle('encrypt-string', (_event, plainText: string) => {
  if (!safeStorage.isEncryptionAvailable()) {
    return Buffer.from(plainText).toString('base64')
  }
  return safeStorage.encryptString(plainText).toString('base64')
})

ipcMain.handle('decrypt-string', (_event, cipherText: string) => {
  if (!safeStorage.isEncryptionAvailable()) {
    return Buffer.from(cipherText, 'base64').toString('utf-8')
  }
  return safeStorage.decryptString(Buffer.from(cipherText, 'base64'))
})

// ---- Restart backend ----
restartBackend = () => {
  stopHealthMonitor()
  healthFailCount = 0
  pythonRestartCount = 0
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
  // Close all WebSocket connections
  for (const [wsId, ws] of wsConnections) {
    ws.close()
    wsConnections.delete(wsId)
  }
  startPythonBackend()
}

ipcMain.handle('restart-backend', async () => {
  restartBackend()
})

// ---- Performance metrics ----
ipcMain.handle('get-performance-metrics', () => ({
  startupTime: perfMetrics.appStartTime,
  backendReadyTime: perfMetrics.backendReadyTime,
  frontendLoadTime: perfMetrics.frontendLoadTime,
  memoryUsage: process.memoryUsage(),
  cpuUsage: process.cpuUsage(),
  crashCount: perfMetrics.crashCount,
  lastCrashTime: perfMetrics.lastCrashTime,
  uptime: Date.now() - perfMetrics.appStartTime,
}))

// ---- Crash reports ----
ipcMain.handle('get-crash-reports', (_event, limit?: number) => {
  return limit ? crashReports.slice(0, limit) : crashReports
})

ipcMain.handle('clear-crash-reports', () => {
  crashReports.length = 0
  perfMetrics.crashCount = 0
  perfMetrics.lastCrashTime = null
  return { success: true }
})

ipcMain.handle('export-diagnostic-logs', () => {
  const logPath = path.join(app.getPath('userData'), 'diagnostic-logs.json')
  const diagnosticData = {
    appVersion: APP_VERSION,
    electronVersion: process.versions.electron,
    platform: process.platform,
    arch: process.arch,
    timestamp: Date.now(),
    perfMetrics,
    crashReports,
    memoryUsage: process.memoryUsage(),
    wsConnections: Array.from(wsConnections.keys()),
    childWindows: Array.from(childWindows.keys()),
  }
  fs.writeFileSync(logPath, JSON.stringify(diagnosticData, null, 2))
  return { path: logPath }
})

// ---- Resource update detection ----
ipcMain.handle('detect-resource-changes', async () => {
  const resourcesDir = isDev
    ? path.join(__dirname, '..')
    : process.resourcesPath
  const changed: string[] = []
  const walkDir = (dir: string) => {
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true })
      for (const entry of entries) {
        if (entry.name.startsWith('.') || entry.name === 'node_modules') continue
        const fullPath = path.join(dir, entry.name)
        if (entry.isDirectory()) {
          walkDir(fullPath)
        } else {
          const hash = getResourceHash(fullPath)
          const prev = resourceHashes.get(fullPath)
          if (prev && prev !== hash) {
            changed.push(fullPath)
            mainWindow?.webContents.send('resource-updated', {
              file: fullPath,
              oldHash: prev,
              newHash: hash,
              timestamp: Date.now(),
            })
          }
          if (hash) resourceHashes.set(fullPath, hash)
        }
      }
    } catch { /* ignore */ }
  }
  walkDir(resourcesDir)
  return { changed }
})

// ---- Window control IPC handlers ----
ipcMain.on('window-minimize', () => {
  mainWindow?.minimize()
})

ipcMain.on('window-maximize', () => {
  if (mainWindow?.isMaximized()) {
    mainWindow.unmaximize()
  } else {
    mainWindow?.maximize()
  }
})

ipcMain.on('window-close', () => {
  mainWindow?.hide()
})

ipcMain.handle('window-is-maximized', () => {
  return mainWindow?.isMaximized() || false
})

ipcMain.on('open-external', (_event, url: string) => {
  shell.openExternal(url)
})

// ---- Multi-window management ----
ipcMain.handle('get-windows', () => {
  const windows: Array<{ id: number; type: string; title: string; bondCode?: string }> = [{ id: 0, type: 'main', title: APP_NAME }]
  for (const [id, win] of childWindows) {
    windows.push({
      id,
      type: (win as any).windowType || 'child',
      title: win.getTitle(),
      bondCode: (win as any).bondCode,
    })
  }
  return windows
})

ipcMain.handle('create-chart-window', (_event, bondCode: string, bondName: string) => {
  const win = new BrowserWindow({
    width: 1000,
    height: 700,
    title: `${bondName} (${bondCode}) - 图表`,
    parent: mainWindow || undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  const id = nextWindowId++
  ;(win as any).windowType = 'chart'
  ;(win as any).bondCode = bondCode
  childWindows.set(id, win)

  if (isDev) {
    win.loadURL(`http://localhost:5173#/chart/${bondCode}`)
  } else {
    win.loadURL(`http://127.0.0.1:${FRONTEND_PORT}#/chart/${bondCode}`)
  }

  win.on('closed', () => { childWindows.delete(id) })
  return { id }
})

ipcMain.handle('create-detail-window', (_event, bondCode: string, bondName: string) => {
  const win = new BrowserWindow({
    width: 900,
    height: 650,
    title: `${bondName} (${bondCode}) - 详情`,
    parent: mainWindow || undefined,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  const id = nextWindowId++
  ;(win as any).windowType = 'detail'
  ;(win as any).bondCode = bondCode
  childWindows.set(id, win)

  if (isDev) {
    win.loadURL(`http://localhost:5173#/detail/${bondCode}`)
  } else {
    win.loadURL(`http://127.0.0.1:${FRONTEND_PORT}#/detail/${bondCode}`)
  }

  win.on('closed', () => { childWindows.delete(id) })
  return { id }
})

ipcMain.handle('close-window', (_event, windowId: number) => {
  const win = childWindows.get(windowId)
  if (win) {
    win.close()
    return true
  }
  return false
})

ipcMain.handle('focus-window', (_event, windowId: number) => {
  const win = childWindows.get(windowId)
  if (win) {
    win.show()
    win.focus()
    return true
  }
  return false
})

ipcMain.handle('send-to-window', (_event, windowId: number, channel: string, data: unknown) => {
  const win = childWindows.get(windowId)
  if (win) {
    win.webContents.send(channel, data)
    return true
  }
  return false
})

ipcMain.on('broadcast', (_event, channel: string, data: unknown) => {
  mainWindow?.webContents.send(channel, data)
  for (const win of childWindows.values()) {
    win.webContents.send(channel, data)
  }
})

// ---- Auto-updater ----
let updateStatus: any = { status: 'not-available' }

function setupAutoUpdater() {
  if (isDev) {
    console.log('[AutoUpdater] Skipped in development mode')
    return
  }

  if (!autoUpdater) {
    console.log('[AutoUpdater] electron-updater not available')
    return
  }

  autoUpdater.autoDownload = false
  autoUpdater.autoInstallOnAppQuit = true

  autoUpdater.on('checking-for-update', () => {
    updateStatus = { status: 'checking' }
    mainWindow?.webContents.send('update-status', updateStatus)
  })

  autoUpdater.on('update-available', (info: any) => {
    updateStatus = { status: 'available', version: info.version }
    mainWindow?.webContents.send('update-status', updateStatus)

    if (mainWindow) {
      dialog.showMessageBox(mainWindow, {
        type: 'info',
        title: '发现新版本',
        message: `发现新版本 ${info.version}`,
        detail: '是否立即下载更新？',
        buttons: ['下载', '稍后'],
        defaultId: 0,
      }).then((result) => {
        if (result.response === 0) {
          autoUpdater.downloadUpdate()
        }
      })
    }
  })

  autoUpdater.on('update-not-available', () => {
    updateStatus = { status: 'not-available' }
    mainWindow?.webContents.send('update-status', updateStatus)
  })

  autoUpdater.on('error', (err: any) => {
    updateStatus = { status: 'error', error: err.message }
    mainWindow?.webContents.send('update-status', updateStatus)
  })

  autoUpdater.on('download-progress', (progressObj: any) => {
    updateStatus = {
      status: 'downloading',
      percent: Math.round(progressObj.percent),
      transferred: progressObj.transferred,
      total: progressObj.total,
    }
    mainWindow?.webContents.send('update-status', updateStatus)
  })

  autoUpdater.on('update-downloaded', (info: any) => {
    updateStatus = { status: 'downloaded', version: info.version }
    mainWindow?.webContents.send('update-status', updateStatus)

    if (mainWindow) {
      dialog.showMessageBox(mainWindow, {
        type: 'question',
        title: '更新已下载',
        message: `新版本 ${info.version} 已准备就绪`,
        detail: '是否立即安装更新？应用将重新启动。',
        buttons: ['立即安装', '稍后安装'],
        defaultId: 0,
      }).then((result) => {
        if (result.response === 0) {
          autoUpdater.quitAndInstall()
        }
      })
    }
  })

  // Check for updates on startup
  autoUpdater.checkForUpdates()
}

function checkForUpdates() {
  if (isDev) {
    dialog.showMessageBox(mainWindow!, {
      type: 'info',
      title: '检查更新',
      message: '开发模式',
      detail: '自动更新功能在开发模式下不可用。',
      buttons: ['确定'],
    })
    return
  }
  if (!autoUpdater) {
    dialog.showMessageBox(mainWindow!, {
      type: 'warning',
      title: '检查更新',
      message: '自动更新不可用',
      detail: 'electron-updater 模块未安装。',
      buttons: ['确定'],
    })
    return
  }
  autoUpdater.checkForUpdates()
}

ipcMain.handle('check-for-updates', async () => {
  if (isDev || !autoUpdater) {
    return { available: false, error: isDev ? 'Dev mode' : 'Updater not available' }
  }
  try {
    const result = await autoUpdater.checkForUpdates()
    return {
      available: result.updateInfo?.version !== app.getVersion(),
      version: result.updateInfo?.version,
    }
  } catch (err: any) {
    return { available: false, error: err.message }
  }
})


// ---- Single instance lock ----
const gotTheLock = app.requestSingleInstanceLock()
if (!gotTheLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

// ---- Global error handlers ----
process.on('uncaughtException', (error: Error) => {
  console.error('[APP] Uncaught exception:', error)
  recordCrash('main', error.message, error.stack)
})

process.on('unhandledRejection', (reason: any) => {
  console.error('[APP] Unhandled rejection:', reason)
  recordCrash('main', String(reason))
})
// ============================================================
// App lifecycle
// ============================================================

app.whenReady().then(() => {
  if (!isDev) {
    const frontendDir = isDev
        ? path.join(__dirname, '..', 'frontend', 'dist')
        : path.join(process.resourcesPath, 'frontend')
    startFrontendServer(frontendDir)
  }
  startPythonBackend()
  createApplicationMenu()
  createTrayIcon()
  createWindow()
  registerGlobalShortcuts()
  setupAutoUpdater()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow()
    } else {
      mainWindow?.show()
    }
  })
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  stopHealthMonitor()
  // Close all WebSocket connections
  for (const [wsId, ws] of wsConnections) {
    ws.close()
    wsConnections.delete(wsId)
  }
  if (tray) {
    tray.destroy()
    tray = null
  }
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit()
  }
})

app.on('before-quit', () => {
  isQuitting = true
  stopHealthMonitor()
  // Persist crash reports
  try {
    const crashPath = path.join(app.getPath('userData'), 'crash-reports.json')
    fs.writeFileSync(crashPath, JSON.stringify(crashReports.slice(0, 20), null, 2))
  } catch {}
  if (pythonProcess) {
    pythonProcess.kill()
    pythonProcess = null
  }
  if (frontendServer) {
    frontendServer.close()
    frontendServer = null
  }
})
