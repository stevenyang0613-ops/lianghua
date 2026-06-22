import { app, BrowserWindow, Tray, Menu, ipcMain, Notification, nativeImage, globalShortcut, shell, dialog, NativeImage, safeStorage, screen } from 'electron'
import { spawn, ChildProcess } from 'child_process'
import http from 'http'
import https from 'https'
import WebSocket from 'ws'
import crypto from 'crypto'
import path from 'path'
import fs from 'fs'
import os from 'os'

const isDev = !app.isPackaged

// 抑制开发模式下的Electron安全警告（打包后自动消失）
if (isDev) {
  process.env.ELECTRON_DISABLE_SECURITY_WARNINGS = 'true'
}
// Dynamic import for electron-updater (optional dependency)
let autoUpdater: any = null
try {
  autoUpdater = require('electron-updater').autoUpdater
} catch {
  console.log('[Electron] electron-updater not available, skipping auto-update')
}

let mainWindow: BrowserWindow | null = null
let pythonProcess: ChildProcess | null = null
let tray: Tray | null = null
let isQuitting = false

// ---- Resource path helper ----
function resourcePath(relativePath: string): string {
  if (isDev) {
    return path.join(__dirname, '..', relativePath)
  }
  return path.join(process.resourcesPath, relativePath)
}

// ---- Frontend page path (in extraResources, not asar) ----
function getFrontendIndexPath(): string {
  if (isDev) {
    // 开发模式：优先使用dist构建产物，Vite dev server需手动启动
    // __dirname = electron/dist，需上溯两级到项目根目录
    const distPath = path.join(__dirname, '..', '..', 'frontend', 'dist', 'index.html')
    if (require('fs').existsSync(distPath)) {
      return distPath
    }
    return 'http://localhost:5173'
  }
  // Frontend dist is in extraResources (process.resourcesPath/frontend/index.html)
  return path.join(process.resourcesPath, 'frontend', 'index.html')
}

// App configuration
const APP_NAME = 'LiangHua - 可转债量化交易系统'
const APP_VERSION = '1.0.0'
const BACKEND_PORT = 8765
const BACKEND_HOST = '127.0.0.1'
const BACKEND_URL = `http://${BACKEND_HOST}:${BACKEND_PORT}`

// ---- Local HTTP server for frontend static files ----
// Serves frontend from a real HTTP server instead of file:// protocol,
// enabling proper code splitting, ES module loading, and faster resource fetching.
const FRONTEND_PORT = 8766
let frontendServer: http.Server | null = null

function startFrontendServer(): Promise<number> {
  return new Promise((resolve, reject) => {
    const frontendDir = isDev
      ? path.join(__dirname, '..', '..', 'frontend', 'dist')
      : path.join(process.resourcesPath, 'frontend')

    const mimeTypes: Record<string, string> = {
      '.html': 'text/html',
      '.js': 'application/javascript',
      '.mjs': 'application/javascript',
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
      '.eot': 'application/vnd.ms-fontobject',
      '.map': 'application/json',
    }

    const server = http.createServer((req, res) => {
      try {
        // Normalize URL and prevent directory traversal
        const urlPath = new URL(req.url || '/', `http://localhost:${FRONTEND_PORT}`).pathname

        // Proxy API and health requests to the backend server
        if (urlPath.startsWith('/api/') || urlPath.startsWith('/health')) {
          // Path-based timeout: slow refresh endpoints need more time
          const PROXY_TIMEOUT_MS = urlPath.includes('/refresh')
            ? 120000   // 2 min for data-refresh endpoints
            : urlPath.startsWith('/health')
            ? 10000    // 10 s for health checks
            : 30000    // 30 s default

          const proxyReq = http.request(
            {
              hostname: BACKEND_HOST,
              port: BACKEND_PORT,
              path: req.url,
              method: req.method,
              headers: {
                ...req.headers,
                host: `${BACKEND_HOST}:${BACKEND_PORT}`,
              },
              timeout: PROXY_TIMEOUT_MS,
            },
            (proxyRes) => {
              res.writeHead(proxyRes.statusCode || 500, proxyRes.headers)
              proxyRes.on('error', (err) => {
                console.error(`[FrontendServer] Proxy response error for ${req.url}: ${err.message}`)
                if (!res.writableEnded) {
                  res.writeHead(502, { 'Content-Type': 'application/json' })
                  res.end(JSON.stringify({ detail: 'Backend response error' }))
                }
              })
              proxyRes.pipe(res)
            }
          )
          proxyReq.on('error', (err) => {
            console.error(`[FrontendServer] Proxy error for ${req.url}: ${err.message}`)
            if (!res.writableEnded) {
              res.writeHead(502, { 'Content-Type': 'application/json' })
              res.end(JSON.stringify({ detail: 'Backend unavailable' }))
            }
          })
          proxyReq.on('timeout', () => {
            proxyReq.destroy()
            if (!res.writableEnded) {
              res.writeHead(504, { 'Content-Type': 'application/json' })
              res.end(JSON.stringify({ detail: 'Backend timeout' }))
            }
          })
          req.on('error', (err) => {
            console.error(`[FrontendServer] Client request error for ${req.url}: ${err.message}`)
            proxyReq.destroy()
          })
          req.on('close', () => {
            if (req.destroyed) {
              proxyReq.destroy()
            }
          })
          req.pipe(proxyReq)
          return
        }

        let filePath = path.join(frontendDir, urlPath === '/' ? 'index.html' : urlPath)

        // Security: ensure the resolved path is within frontendDir
        if (!filePath.startsWith(frontendDir)) {
          res.writeHead(403)
          res.end('Forbidden')
          return
        }

        if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
          // SPA fallback: serve index.html for client-side routing
          filePath = path.join(frontendDir, 'index.html')
        }

        const ext = path.extname(filePath).toLowerCase()
        const contentType = mimeTypes[ext] || 'application/octet-stream'

        const stream = fs.createReadStream(filePath)
        stream.on('error', () => {
          if (!res.headersSent) {
            res.writeHead(404)
            res.end('Not Found')
          }
        })
        res.writeHead(200, {
          'Content-Type': contentType,
          'Cache-Control': ext === '.html' ? 'no-cache' : 'public, max-age=86400',
        })
        stream.pipe(res)
      } catch (e) {
        res.writeHead(404)
        res.end('Not Found')
      }
    })

    // Try FRONTEND_PORT first, fall back to a random port if occupied
    server.on('error', (e: NodeJS.ErrnoException) => {
      if (e.code === 'EADDRINUSE') {
        // Port occupied, try a random port
        server.listen(0, '127.0.0.1', () => {
          const addr = server.address()
          const port = typeof addr === 'object' && addr ? addr.port : FRONTEND_PORT
          frontendServer = server
          console.log(`[FrontendServer] Serving on http://127.0.0.1:${port} (fallback port) from ${frontendDir}`)
          resolve(port)
        })
      } else {
        reject(e)
      }
    })

    server.listen(FRONTEND_PORT, '127.0.0.1', () => {
      frontendServer = server
      console.log(`[FrontendServer] Serving on http://127.0.0.1:${FRONTEND_PORT} from ${frontendDir}`)
      resolve(FRONTEND_PORT)
    })
  })
}

let actualFrontendPort: number = FRONTEND_PORT

// Forward declaration
let restartBackend: (isManualRestart?: boolean) => void
let restartInFlight = false
let _backendStarting = false
let creatingWindow = false

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
const MAX_WS_CONNECTIONS = 64

// 改进 (2025-06-20): WebSocket 心跳与死连接清理
const WS_HEARTBEAT_INTERVAL_MS = 30000  // 30s 发一次 ping
const WS_HEARTBEAT_TIMEOUT_MS = 60000 // 60s 未收到 pong 视为死连接
const wsHeartbeatTimers = new Map<string, ReturnType<typeof setTimeout>>()

function _cleanupWsConnection(wsId: string) {
  const ws = wsConnections.get(wsId)
  if (ws) {
    ws.removeAllListeners()
    ws.close()
    wsConnections.delete(wsId)
  }
  const timer = wsHeartbeatTimers.get(wsId)
  if (timer) {
    clearTimeout(timer)
    wsHeartbeatTimers.delete(wsId)
  }
}

function _startWsHeartbeat(wsId: string) {
  const timer = setInterval(() => {
    const ws = wsConnections.get(wsId)
    if (!ws) {
      _cleanupWsConnection(wsId)
      return
    }
    if (ws.readyState === WebSocket.OPEN) {
      ws.ping()
      // 设置 pong 超时检测
      const pongTimeout = setTimeout(() => {
        console.warn(`[WS ${wsId}] Pong timeout, closing dead connection`)
        _cleanupWsConnection(wsId)
        mainWindow?.webContents.send('ws-state', wsId, 'disconnected', 1006, 'Heartbeat timeout')
      }, WS_HEARTBEAT_TIMEOUT_MS)
      ws.once('pong', () => clearTimeout(pongTimeout))
    } else if (ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      _cleanupWsConnection(wsId)
    }
  }, WS_HEARTBEAT_INTERVAL_MS)
  wsHeartbeatTimers.set(wsId, timer as unknown as ReturnType<typeof setTimeout>)
}

// 全局定时器：每 60s 扫描一次 wsConnections，清理所有已关闭的连接
setInterval(() => {
  for (const [wsId, ws] of wsConnections.entries()) {
    if (ws.readyState === WebSocket.CLOSED || ws.readyState === WebSocket.CLOSING) {
      console.log(`[WS] Cleanup dead connection ${wsId}`)
      _cleanupWsConnection(wsId)
    }
  }
}, 60000)

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
let cachedAuthToken: { value: string; expiresAt: number } | null = null

function readTokenFile(p: string): string {
  try {
    if (fs.existsSync(p)) {
      const t = fs.readFileSync(p, 'utf-8').trim()
      if (t) return t
    }
  } catch {
    // ignore
  }
  return ''
}

function fetchTokenFromBackend(): Promise<string> {
  return new Promise((resolve) => {
    try {
      const req = http.get(`${BACKEND_URL}/health`, { timeout: 3000 }, (res) => {
        let data = ''
        res.on('data', (chunk: Buffer) => { data += chunk.toString() })
        res.on('end', () => {
          try {
            const parsed = JSON.parse(data)
            const t = parsed?.ws_auth_token
            resolve(typeof t === 'string' ? t.trim() : '')
          } catch {
            resolve('')
          }
        })
      })
      req.on('error', () => resolve(''))
      req.on('timeout', () => { req.destroy(); resolve('') })
    } catch {
      resolve('')
    }
  })
}

function getDesktopAuthTokenSync(): string {
  const candidates = [
    path.join(os.homedir(), '.lianghua', '.ws_token'),
    path.join(process.resourcesPath || '', 'backend', 'data', '.ws_token'),
    path.join(__dirname, '..', '..', 'backend', 'data', '.ws_token'),
  ]
  for (const p of candidates) {
    if (!p) continue
    const t = readTokenFile(p)
    if (t) return t
  }
  return ''
}

function getDesktopAuthToken(): string {
  if (cachedAuthToken && cachedAuthToken.expiresAt > Date.now()) {
    return cachedAuthToken.value
  }
  const t = getDesktopAuthTokenSync()
  cachedAuthToken = { value: t, expiresAt: Date.now() + 60_000 }
  return t
}

async function ensureDesktopAuthToken(): Promise<string> {
  const t = getDesktopAuthToken()
  if (t) return t
  const fetched = await fetchTokenFromBackend()
  if (fetched) {
    cachedAuthToken = { value: fetched, expiresAt: Date.now() + 60_000 }
    return fetched
  }
  return ''
}

// Loopback hostnames permitted for IPC-driven http requests. Anything else
// is rejected to prevent the renderer (or a compromised renderer) from using
// the desktop token to hit intranet / metadata services.
const ALLOWED_HTTP_HOSTS = new Set(['127.0.0.1', 'localhost', '::1'])

function isAllowedHttpHost(hostname: string): boolean {
  return ALLOWED_HTTP_HOSTS.has(hostname.toLowerCase())
}

async function httpRequestHandler(
  method: string,
  url: string,
  body?: any
): Promise<{ ok: boolean; status: number; data: any; error?: string }> {
  const authToken = await ensureDesktopAuthToken()
  let parsedUrl: URL
  try {
    parsedUrl = new URL(url)
  } catch {
    return { ok: false, status: 0, data: null, error: 'Invalid URL' }
  }
  if (parsedUrl.protocol !== 'http:' && parsedUrl.protocol !== 'https:') {
    return { ok: false, status: 0, data: null, error: 'Unsupported protocol' }
  }
  if (!isAllowedHttpHost(parsedUrl.hostname)) {
    return { ok: false, status: 0, data: null, error: `Host not allowed: ${parsedUrl.hostname}` }
  }
  return new Promise((resolve) => {
    const timeout = 30000
    const isHttps = parsedUrl.protocol === 'https:'
    const httpModule = isHttps ? https : http

    const headers: Record<string, string> = {
      'Accept': 'application/json',
      'Content-Type': 'application/json',
    }
    if (authToken) {
      headers['Authorization'] = `Bearer ${authToken}`
    }

    const options: http.RequestOptions = {
      hostname: parsedUrl.hostname,
      port: parsedUrl.port || (isHttps ? 443 : 80),
      path: parsedUrl.pathname + parsedUrl.search,
      method: method.toUpperCase(),
      headers,
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
  try {
    const result = await httpRequestHandler('GET', `${BACKEND_URL}/health`)
    return result.ok && result.data?.status === 'ok'
  } catch {
    return false
  }
}

// ---- Wait for backend to be ready ----
async function waitForBackend(maxWaitMs = 120000, intervalMs = 2000): Promise<boolean> {
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

// ---- Prefetch market data for first-screen optimization ----
let prefetchedMarketData: any = null

async function prefetchMarketData(): Promise<void> {
  try {
    const resp = await new Promise<any>((resolve, reject) => {
      const req = http.get(`${BACKEND_URL}/api/v1/market/quotes`, (res) => {
        let body = ''
        res.on('data', (chunk: string) => { body += chunk })
        res.on('end', () => {
          try { resolve(JSON.parse(body)) } catch { reject(new Error('Parse error')) }
        })
      })
      req.on('error', reject)
      req.setTimeout(10000, () => { req.destroy(); reject(new Error('Timeout')) })
    })
    if (resp?.bonds && Array.isArray(resp.bonds)) {
      prefetchedMarketData = resp
      console.log(`[Prefetch] Market data: ${resp.bonds.length} bonds`)
      // Send to renderer if window is already loaded
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send('prefetched-market-data', resp)
      }
    }
  } catch (e) {
    console.warn(`[Prefetch] Market data prefetch failed: ${e}`)
  }
}

// ---- Health monitoring loop ----
let healthMonitorInterval: NodeJS.Timeout | null = null
let healthFailCount = 0
const HEALTH_MAX_FAILS = 3
const HEALTH_CHECK_INTERVAL = 10000

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
  }, HEALTH_CHECK_INTERVAL)
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
            dialog.showMessageBox(mainWindow as any, {
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
            restartBackend(true)
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
            dialog.showMessageBox(mainWindow as any, {
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
let pythonRestartTimer: ReturnType<typeof setTimeout> | null = null
const MAX_PYTHON_RESTARTS = 5
const PYTHON_RESTART_RESET_INTERVAL = 60000
// AGENTS.md improvement: getPidDir() is resolved lazily via getPidDir().
// app.getPath('home') is more correct than os.homedir() in sandboxed
// environments, but only safe to call after app is ready. The helpers
// below call getPidDir() at use-time, not at module load time.
function getPidDir(): string {
  try {
    return path.join(app.getPath('home'), '.lianghua', 'pids')
  } catch {
    return path.join(os.homedir(), '.lianghua', 'pids')
  }
}

/**
 * Write a PID file (and a sibling .ts file with the write epoch in ms)
 * to track the spawned backend/electron process. The timestamp allows
 * the next launch to detect a race where two instances started <1s
 * apart — in that case, the second instance is allowed to skip the
 * kill step on the first instance's PID (it might be its own process).
 */
function writePidFile(name: string, pid: number): void {
  try {
    fs.mkdirSync(getPidDir(), { recursive: true })
    const dir = getPidDir()
    fs.writeFileSync(path.join(dir, `${name}.pid`), String(pid))
    fs.writeFileSync(path.join(dir, `${name}.ts`), String(Date.now()))
  } catch (e) {
    console.error(`[Electron] Failed to write ${name}.pid:`, (e as Error).message)
  }
}

/**
 * Read the timestamp of a PID file (when it was last written).
 * Returns 0 if the file is missing or unreadable.
 */
function readPidTimestamp(name: string): number {
  try {
    return parseInt(fs.readFileSync(path.join(getPidDir(), `${name}.ts`), 'utf-8').trim(), 10) || 0
  } catch {
    return 0
  }
}

/**
 * Read a previously-written PID file. Returns null if file doesn't exist
 * or the process is no longer alive.
 */
function readPidFile(name: string): number | null {
  try {
    const pidStr = fs.readFileSync(path.join(getPidDir(), `${name}.pid`), 'utf-8').trim()
    const pid = parseInt(pidStr, 10)
    if (!Number.isFinite(pid) || pid <= 0) return null
    // Check if process is alive
    try {
      process.kill(pid, 0)
      return pid
    } catch {
      // ESRCH = no such process
      return null
    }
  } catch {
    return null
  }
}

/**
 * Remove stale PID file. Safe to call even if file doesn't exist.
 */
function removePidFile(name: string): void {
  try {
    fs.unlinkSync(path.join(getPidDir(), `${name}.pid`))
  } catch {
    // Ignore ENOENT
  }
}

/**
 * Kill any stale lianghua process (Electron or backend) referenced by PID files.
 * Called at startup so rebuilds don't leave zombie daemons holding the
 * backend port or DuckDB lock (root cause of "打不开" incidents).
 */
function killStaleInstances(): void {
  const candidates: Array<{ name: string; pid: number }> = []
  const now = Date.now()
  // Race protection: if a candidate was written <1000ms ago, the
  // owning process might still be starting up — or it might be us.
  // Skip the kill to avoid killing ourselves.
  const RACE_GRACE_MS = 1000
  for (const name of ['backend', 'desktop']) {
    const pid = readPidFile(name)
    if (pid === null) continue
    const ts = readPidTimestamp(name)
    if (ts > 0 && (now - ts) < RACE_GRACE_MS) {
      console.log(`[Electron] Skipping ${name} (PID ${pid}) — written ${now - ts}ms ago, within race grace`)
      continue
    }
    candidates.push({ name, pid })
  }
  for (const { name, pid } of candidates) {
    try {
      // Negative pid = process group (Unix). The original spawn used
      // detached: true, so the backend owns its own group.
      process.kill(-pid, 'SIGTERM')
      console.log(`[Electron] Killed stale ${name} (PID ${pid}) via SIGTERM`)
    } catch (e: any) {
      if (e.code === 'ESRCH') {
        console.log(`[Electron] Stale ${name}.pid pointed at dead PID ${pid}; cleaning up`)
      } else if (e.code === 'EPERM') {
        console.warn(`[Electron] No permission to kill stale ${name} (PID ${pid})`)
        continue
      } else {
        console.error(`[Electron] Failed to kill stale ${name} (PID ${pid}):`, e.message)
        continue
      }
    }
    removePidFile(name)
  }
  // Belt-and-suspenders: if 8765 is still occupied after PID-file sweep
  // (e.g. user launched manually), try to identify via lsof and kill.
  // Hard 2s timeout — lsof can hang on certain kernel states.
  // ENOENT (lsof missing) is silently ignored (pure dev/CI edge case).
  try {
    const { execFileSync } = require('child_process') as typeof import('child_process')
    const out = execFileSync('lsof', ['-ti', `tcp:${BACKEND_PORT}`, '-sTCP:LISTEN'], {
      stdio: ['ignore', 'pipe', 'ignore'],
      timeout: 2000,
      killSignal: 'SIGKILL',
    }).toString().trim()
    if (out) {
      const pids = out.split('\n').map(s => parseInt(s, 10)).filter(Number.isFinite)
      for (const pid of pids) {
        try {
          process.kill(pid, 'SIGTERM')
          console.log(`[Electron] Killed orphaned port ${BACKEND_PORT} holder (PID ${pid})`)
        } catch {}
      }
    }
  } catch (e: any) {
    if (e?.code === 'ENOENT') {
      console.warn('[Electron] lsof not found; skipping port-occupant cleanup')
    } else if (e?.signal === 'SIGKILL' || e?.killed) {
      console.warn('[Electron] lsof timed out (>2s); skipping port-occupant cleanup')
    }
    // Other errors (no listener, etc.) are silent.
  }
  // Retry: after killing processes, wait for the port to be released
  // macOS TIME_WAIT can keep a port busy for 1-2 s after the process dies
  try {
    const { execFileSync } = require('child_process') as typeof import('child_process')
    const deadline = Date.now() + 5000
    while (Date.now() < deadline) {
      const stillHeld = execFileSync('lsof', ['-ti', `tcp:${BACKEND_PORT}`, '-sTCP:LISTEN'], {
        stdio: ['ignore', 'pipe', 'ignore'],
        timeout: 1500,
        killSignal: 'SIGKILL',
      }).toString().trim()
      if (!stillHeld) break
      console.log(`[Electron] Port ${BACKEND_PORT} still held; waiting...`)
      const pids = stillHeld.split('\n').map(s => parseInt(s, 10)).filter(Number.isFinite)
      for (const pid of pids) {
        try { process.kill(pid, 'SIGKILL') } catch {}
      }
      require('child_process').execFileSync('sleep', ['0.5'])
    }
  } catch {}
}

function getBackendDir(): string {
  // Production: use process.resourcesPath directly (backend is in extraResources, NOT in asar)
  // This avoids Electron's asar interception which breaks spawn()
  if (!isDev) {
    return path.join(process.resourcesPath, 'backend')
  }
  return path.join(__dirname, '..', 'backend')
}

function getPythonCmd(backendDir: string): { cmd: string; envPath?: string } {
  const pyinstallerBin = path.join(backendDir, 'lianghua-backend')
  if (fs.existsSync(pyinstallerBin) && !fs.statSync(pyinstallerBin).isDirectory()) return { cmd: pyinstallerBin }
  const pyinstallerOnedir = path.join(backendDir, 'dist', 'lianghua-backend', 'lianghua-backend')
  if (fs.existsSync(pyinstallerOnedir)) return { cmd: pyinstallerOnedir }
  if (isDev) {
    const venvPython = path.join(backendDir, '.venv', 'bin', 'python')
    if (fs.existsSync(venvPython)) return { cmd: venvPython }
  }
  // Resolve python3 absolute path (macOS sandbox restricts PATH-based lookup)
  const candidates = [
    '/usr/local/bin/python3',
    '/opt/homebrew/bin/python3',
    '/usr/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/3.11/bin/python3',
    '/Library/Frameworks/Python.framework/Versions/3.10/bin/python3',
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return { cmd: c }
  }
  // Fall back to PATH lookup (may fail in sandbox)
  const extraPaths = ['/usr/local/bin', '/opt/homebrew/bin', '/usr/bin']
  const currentPath = process.env.PATH || '/usr/bin:/bin:/usr/sbin:/sbin'
  const fullPath = [...extraPaths.filter(p => !currentPath.includes(p)), currentPath].join(':')
  return { cmd: 'python3', envPath: fullPath }
}

function getSSLCertEnv(): Record<string, string> {
  // PyInstaller 打包的后端找不到系统 SSL 证书，需要显式传入
  const certPaths = [
    '/opt/homebrew/etc/openssl@3/cert.pem',
    '/etc/ssl/cert.pem',
    '/usr/local/etc/openssl@3/cert.pem',
    '/usr/local/etc/openssl/cert.pem',
  ]
  for (const certPath of certPaths) {
    if (fs.existsSync(certPath)) {
      return { SSL_CERT_FILE: certPath, REQUESTS_CA_BUNDLE: certPath }
    }
  }
  return {}
}

function killPythonProcessGroup(child: import('child_process').ChildProcess): void {
  if (!child || child.killed || child.pid === undefined) return
  if (process.platform === 'win32') {
    try {
      require('child_process').execFileSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' })
    } catch (e) {
      console.error('[Electron] taskkill failed:', (e as Error).message)
      try { child.kill('SIGKILL') } catch {}
    }
  } else {
    try {
      process.kill(-child.pid, 'SIGTERM')
    } catch {
      try { child.kill('SIGTERM') } catch {}
    }
    // Hard kill after grace period
    const pid = child.pid
    setTimeout(() => {
      try { process.kill(-pid, 'SIGKILL') } catch {}
      try { process.kill(pid, 'SIGKILL') } catch {}
    }, 1500).unref()
  }
}

function startPythonBackend() {
  if (_backendStarting) {
    console.log('[Electron] startPythonBackend already in progress, ignoring')
    return
  }
  _backendStarting = true
  const backendDir = getBackendDir()
  const { cmd: pythonCmd, envPath } = getPythonCmd(backendDir)

  const isPyinstaller = pythonCmd.endsWith('lianghua-backend')
  const pyinstallerCwd = isPyinstaller ? path.dirname(pythonCmd) : backendDir
  const args = isPyinstaller
    ? ['--host', BACKEND_HOST, '--port', String(BACKEND_PORT)]
    : [path.join(backendDir, 'run_app.py'), '--host', BACKEND_HOST, '--port', String(BACKEND_PORT)]

  const sslEnv = getSSLCertEnv()
  const spawnEnv = { ...process.env, ...(envPath ? { PATH: envPath } : {}), ...sslEnv }

  console.log(`[Electron] startPythonBackend: cmd=${pythonCmd}, args=${JSON.stringify(args)}, cwd=${pyinstallerCwd}`)
  pythonProcess = spawn(pythonCmd, args, {
    cwd: pyinstallerCwd,
    stdio: ['ignore', 'pipe', 'pipe'],
    env: spawnEnv,
    // detached: true lets us kill the entire process group (workers, children)
    // on Unix. On Windows, taskkill /T is used in killPythonProcessGroup.
    detached: process.platform !== 'win32',
    windowsHide: true,
  })

  if (pythonProcess.pid !== undefined) {
    writePidFile('backend', pythonProcess.pid)
  }
  // NOTE: _backendStarting is cleared inside waitForBackend().then() to prevent
  // duplicate spawn during the 60s readiness check window (AGENTS.md #17).

  pythonProcess.stdout?.on('data', (data: Buffer) => {
    console.log('[Python] ' + data.toString().trim())
  })
  pythonProcess.stderr?.on('data', (data: Buffer) => {
    const stderrText = data.toString()
    console.log('[Python] ' + stderrText.trim())
    // 检测端口占用（EADDRINUSE 由 Python 进程内部输出，不是 spawn error）
    if (stderrText.includes('EADDRINUSE') || stderrText.includes('Address already in use')) {
      console.error(`[Electron] Port ${BACKEND_PORT} is already in use by another process`)
      mainWindow?.webContents.send('backend-error', {
        code: 'EADDRINUSE',
        title: '端口占用',
        message: `端口 ${BACKEND_PORT} 已被其他进程占用`,
        details: '请关闭占用该端口的程序，或在设置中更换端口'
      })
    }
  })

  pythonProcess.on('exit', (code: number | null, signal: NodeJS.Signals | null) => {
    removePidFile('backend')
    _backendStarting = false
    console.log('[Electron] Python process exited with code ' + code)
    if (!isQuitting && code !== 0 && !restartInFlight) {
      recordCrash('backend', `Python backend exited with code ${code}`)
      setTimeout(() => {
        if (isQuitting || restartInFlight) return
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
    // Notify the renderer immediately so the user is not staring at a loading
    // screen for the full 60s waitForBackend timeout.
    mainWindow?.webContents.send('backend-error', {
      title: '后端启动失败',
      message: `Python 后端进程启动失败: ${err.message}`,
      details: '请检查 Python 解释器路径与依赖',
    })
    // Fallback EADDRINUSE detection — primary detection is in stderr handler above
    const errnoErr = err as NodeJS.ErrnoException
    if (errnoErr.code === 'EADDRINUSE') {
      console.error(`[Electron] Port ${BACKEND_PORT} is already in use by another process (fallback detection)`)
      mainWindow?.webContents.send('backend-error', { code: 'EADDRINUSE', message: `Port ${BACKEND_PORT} is in use` })
    }
  })

  // Wait for backend and signal readiness
  // _backendStarting is cleared here (not before waitForBackend) to prevent
  // duplicate spawn during the 60s readiness check window.
  waitForBackend().then((ready) => {
    _backendStarting = false
    if (ready) {
      console.log('[Electron] Backend is ready, notifying renderer')
      mainWindow?.webContents.send('backend-ready')
      startHealthMonitor()
      // Prefetch market data for first-screen optimization
      prefetchMarketData()
    } else {
      console.error('[Electron] Backend did not become ready in time')
      mainWindow?.webContents.send('backend-error', {
        title: '后端启动超时',
        message: 'Python 后端未能在 60 秒内就绪',
        details: '请检查后端日志并手动重启'
      })
    }
  }).catch((err) => {
    _backendStarting = false
    console.error('[Electron] waitForBackend threw:', err)
    mainWindow?.webContents.send('backend-error', {
      title: '后端启动异常',
      message: `后端就绪检查异常: ${err.message}`,
      details: err.stack || ''
    })
  })

  if (pythonRestartTimer) clearTimeout(pythonRestartTimer)
  pythonRestartTimer = setTimeout(() => { pythonRestartCount = 0 }, PYTHON_RESTART_RESET_INTERVAL)
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
      click: () => restartBackend(true),
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
      if (
        Number.isFinite(state.width) && state.width >= 1024 && state.width <= 10000 &&
        Number.isFinite(state.height) && state.height >= 680 && state.height <= 10000
      ) {
        const result: { width: number; height: number; x?: number; y?: number; isMaximized?: boolean } = {
          width: Math.floor(state.width),
          height: Math.floor(state.height),
        }
        // Validate x/y against currently connected displays
        if (Number.isFinite(state.x) && Number.isFinite(state.y)) {
          const displays = screen.getAllDisplays()
          const onScreen = displays.some(d => {
            const b = d.bounds
            return state.x >= b.x - 50 && state.x <= b.x + b.width - 50 &&
                   state.y >= b.y - 50 && state.y <= b.y + b.height - 50
          })
          if (onScreen) {
            result.x = Math.floor(state.x)
            result.y = Math.floor(state.y)
          }
        }
        if (state.isMaximized === true) {
          result.isMaximized = true
        }
        return result
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

// Debounced window state saver — throttles resize/move (300ms interval)
let _saveStateTimer: ReturnType<typeof setTimeout> | null = null
function debouncedSaveWindowState() {
  if (_saveStateTimer) return
  _saveStateTimer = setTimeout(() => {
    _saveStateTimer = null
    saveWindowState()
  }, 300)
}

// ---- Create main window ----
async function createWindow() {
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
      // 开发模式通过 file:// 协议加载时需要禁用 webSecurity 以允许跨域请求
      // 生产环境使用 http://127.0.0.1:8766 加载，保持 webSecurity 启用
      webSecurity: isDev ? false : true,
    },
  })

  // Restore maximized state
  if (savedState.isMaximized) {
    mainWindow.maximize()
  }

  // Safety timeout: show window even if ready-to-show doesn't fire
  // macOS 上 ready-to-show 有时不会触发或触发过晚，导致用户看到黑屏
  const readyShowTimeout = setTimeout(() => {
    if (mainWindow && !mainWindow.isVisible()) {
      console.warn('[Electron] window.show() failed, forcing show (3s timeout)')
      mainWindow.show()
      mainWindow.focus()
    }
  }, 3000)
  readyShowTimeout.unref()

  mainWindow.once('ready-to-show', () => {
    clearTimeout(readyShowTimeout)
    mainWindow?.show()
    mainWindow?.focus()
    perfMetrics.frontendLoadTime = Date.now()
    if (isDev) {
      mainWindow?.webContents.openDevTools()
    }
  })

  // Start local HTTP server for frontend static files (enables code splitting)
  // Fall back to file:// if server fails to start
  try {
    actualFrontendPort = await startFrontendServer()
    const frontendUrl = `http://127.0.0.1:${actualFrontendPort}`
    console.log(`[Electron] Loading frontend from ${frontendUrl}`)
    try {
      await mainWindow.loadURL(frontendUrl)
      console.log('[Electron] Frontend URL loaded successfully')
    } catch (loadErr) {
      console.error(`[Electron] loadURL failed: ${loadErr}, falling back to file://`)
      const frontendPath = getFrontendIndexPath()
      if (frontendPath.startsWith('http')) {
        await mainWindow.loadURL(frontendPath)
      } else {
        await mainWindow.loadFile(frontendPath)
      }
    }
  } catch (e) {
    console.warn(`[Electron] Frontend server failed, falling back to file://: ${e}`)
    const frontendPath = getFrontendIndexPath()
    try {
      if (frontendPath.startsWith('http')) {
        await mainWindow.loadURL(frontendPath)
      } else {
        await mainWindow.loadFile(frontendPath)
      }
    } catch (fallbackErr) {
      console.error(`[Electron] Fallback load also failed: ${fallbackErr}`)
      // Ultimate fallback: show a basic error page
      const errorHtml = `data:text/html;charset=utf-8,${encodeURIComponent(`<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="background:#f5f5f5;color:#333;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;font-family:sans-serif;margin:0"><h1 style="color:#e74c3c">✨ 页面加载失败</h1><p style="color:#666;margin:8px 0">无法加载应用页面</p><button onclick="window.location.reload()" style="margin-top:16px;padding:8px 24px;background:#3498db;color:#fff;border:none;border-radius:4px;cursor:pointer">重试</button></body></html>`)}`
      mainWindow?.loadURL(errorHtml)
    }
  }

  // Log when page finishes loading (for debugging)
  mainWindow.webContents.on('did-finish-load', () => {
    console.log('[Electron] Page did-finish-load')
  })

  // Handle frontend loading errors
  mainWindow.webContents.on('did-fail-load', (event: any, errorCode: number, errorDescription: string, validatedURL: string) => {
    // Only handle main-frame failures — sub-resource failures (images, scripts,
    // stylesheets) should not wipe the whole app.
    if (!event.isMainFrame) {
      console.warn(`[Electron] Sub-resource failed: ${validatedURL} (${errorCode})`)
      return
    }
    console.error(`[Electron] Failed to load: ${validatedURL}, error: ${errorCode} - ${errorDescription}`)
    if (!isDev) {
      // Retry button uses IPC (retry-frontend-load) instead of location.reload()
      // because reload() would re-load the data: URL of this error page itself.
      const errorHtml = `data:text/html;charset=utf-8,${encodeURIComponent(`<!DOCTYPE html><html><head><meta charset="utf-8"></head><body style="background:#f5f5f5;color:#333;display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;font-family:sans-serif;margin:0"><h1 style="color:#e74c3c">✨ 页面加载失败</h1><p style="color:#666;margin:8px 0">无法加载应用页面 (错误码: ${errorCode})</p><p style="margin-top:20px"><button id="retry" style="padding:10px 24px;background:#1890ff;color:#fff;border:none;border-radius:6px;cursor:pointer;font-size:14px">重新加载</button></p><script>document.getElementById('retry').onclick=()=>window.electronAPI.retryFrontendLoad();</script></body></html>`)}`
      mainWindow?.loadURL(errorHtml)
    }
  })

  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url).catch((err: Error) =>
      console.warn('[Electron] Failed to open external URL:', url, err.message)
    )
    return { action: 'deny' }
  })

  // Save window state on resize/move (debounced 300ms)
  mainWindow.on('resize', debouncedSaveWindowState)
  mainWindow.on('move', debouncedSaveWindowState)
  mainWindow.on('maximize', debouncedSaveWindowState)
  mainWindow.on('unmaximize', debouncedSaveWindowState)

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
    const allowedTypes: ReadonlySet<CrashReport['type']> = new Set(['renderer', 'main', 'backend', 'gpu'])
    const t: string = details?.type
    const mapped: CrashReport['type'] = allowedTypes.has(t as CrashReport['type'])
      ? (t as CrashReport['type'])
      : 'main'  // utility / plugin / sandbox / service-worker / etc. → 'main'
    recordCrash(mapped, `Child process gone: ${t} - ${details?.reason ?? 'unknown'}`)
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
    // Cap on total WS connections to prevent renderer-driven fd/memory leaks
    if (wsConnections.size >= MAX_WS_CONNECTIONS && !wsConnections.has(wsId)) {
      return { ok: false, state: 'error', error: `WS connection limit reached (${MAX_WS_CONNECTIONS})` }
    }
    // Close existing connection for this wsId
    // 清理旧连接时必须同时清理心跳定时器，否则旧的 setInterval 会持续运行
    const existing = wsConnections.get(wsId)
    if (existing) {
      _cleanupWsConnection(wsId)
    }

    const ws = new WebSocket(url)

    // 状态值必须与 shared/types.ts WsIpcState 保持一致
    // 注意：ws.on('open') 必须在 IPC Promise 的 openHandler 之后注册
    // 这样 IPC Promise 先 resolve，renderer 端先处理结果，再收到 ws-state 事件
    let ipcResolved = false
    let wsAccepted = false
    ws.on('open', () => {
      if (ipcResolved) {
        mainWindow?.webContents.send('ws-state', wsId, 'connected')
      }
      // 如果 IPC Promise 尚未 resolve，由 openHandler 触发后发送
    })

    ws.on('message', (data: WebSocket.Data, isBinary: boolean) => {
      const payload = isBinary ? (data as Buffer).toString('base64') : data.toString()
      mainWindow?.webContents.send('ws-message', wsId, payload, isBinary)
    })

    ws.on('close', (code: number, reason: Buffer) => {
      wsConnections.delete(wsId)
      mainWindow?.webContents.send('ws-state', wsId, 'disconnected', code, reason.toString())
      // 清理心跳定时器
      const timer = wsHeartbeatTimers.get(wsId)
      if (timer) {
        clearTimeout(timer)
        wsHeartbeatTimers.delete(wsId)
      }
    })

    ws.on('error', (err: Error) => {
      console.error(`[WS ${wsId}] Error:`, err.message)
      mainWindow?.webContents.send('ws-state', wsId, 'error', 0, err.message)
    })

    wsConnections.set(wsId, ws)

    // Wait for connection to open or error
    return new Promise((resolve) => {
      const finalizeResolve = (result: { ok: boolean; state: string; error?: string }) => {
        cleanup()
        ipcResolved = true
        resolve(result)
      }
      const openHandler = () => {
        wsAccepted = true
        finalizeResolve({ ok: true, state: 'connected' })
        // 改进 (2025-06-20): 连接成功后启动心跳
        _startWsHeartbeat(wsId)
        // IPC Promise resolve 后再发送 ws-state 事件，确保 renderer 端先处理 IPC 结果
        mainWindow?.webContents.send('ws-state', wsId, 'connected')
      }
      const errorHandler = (err: Error) => {
        finalizeResolve({ ok: false, state: 'error', error: err.message })
      }
      const timeoutId = setTimeout(() => {
        // If the WS still opens after the timeout, the persistent 'open'
        // listener at the top of this scope will not send ws-state:connected
        // (because ipcResolved=true, wsAccepted=false). Force-send it here so
        // the renderer can recover from a late connection.
        finalizeResolve({ ok: false, state: 'timeout', error: 'Connection timeout' })
        try {
          if (ws.readyState === WebSocket.OPEN) {
            wsAccepted = true
            mainWindow?.webContents.send('ws-state', wsId, 'connected')
          }
        } catch {}
      }, 5000)

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
  if (typeof message !== 'string') {
    return { ok: false, error: 'Message must be a string' }
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
    [WebSocket.OPEN]: 'connected',
    [WebSocket.CLOSING]: 'closing',
    [WebSocket.CLOSED]: 'disconnected',
  }
  return { state: stateMap[ws.readyState] || 'unknown' }
})

// ---- Frontend reload (used by did-fail-load error page retry button) ----
ipcMain.handle('retry-frontend-load', async () => {
  if (!mainWindow) return false
  // Prefer local HTTP server if running, otherwise fall back to file://
  try {
    if (frontendServer) {
      await mainWindow.loadURL(`http://127.0.0.1:${actualFrontendPort}`)
    } else {
      const frontendPath = getFrontendIndexPath()
      if (frontendPath.startsWith('http')) {
        await mainWindow.loadURL(frontendPath)
      } else {
        await mainWindow.loadFile(frontendPath)
      }
    }
  } catch (e) {
    console.error('[Electron] retry-frontend-load failed:', e)
    return false
  }
  return true
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

// ---- WebSocket auth token ----
ipcMain.handle('get-ws-token', () => {
  const tokenPaths = [
    path.join(app.getPath('home'), '.lianghua', '.ws_token'),
    path.join(process.resourcesPath, 'backend', 'data', '.ws_token'),
  ]
  for (const p of tokenPaths) {
    try {
      if (fs.existsSync(p)) {
        const token = fs.readFileSync(p, 'utf-8').trim()
        if (token) return token
      }
    } catch { /* ignore */ }
  }
  return ''
})

// ---- Safe storage (encryption) ----
// Refuse to silently write plaintext disguised as ciphertext when no OS-level
// encryption is available. The caller should treat this as a hard error and
// fall back to a different persistence strategy.
ipcMain.handle('encrypt-string', (_event, plainText: string) => {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Encryption unavailable: OS keychain/credential manager is not accessible. Refusing to store plaintext.')
  }
  return safeStorage.encryptString(plainText).toString('base64')
})

ipcMain.handle('decrypt-string', (_event, cipherText: string) => {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('Encryption unavailable: cannot decrypt previously stored values')
  }
  return safeStorage.decryptString(Buffer.from(cipherText, 'base64'))
})

// ---- Restart backend ----
restartBackend = (isManualRestart = false) => {
  if (isQuitting) return
  if (restartInFlight) {
    console.log('[Electron] restartBackend already in flight, ignoring')
    return
  }
  restartInFlight = true
  stopHealthMonitor()
  healthFailCount = 0
  if (isManualRestart) pythonRestartCount = 0
  for (const wsId of [...wsConnections.keys()]) {
    const ws = wsConnections.get(wsId)
    if (ws) {
      ws.close()
    }
    wsConnections.delete(wsId)
  }
  const pendingTimeout = setTimeout(() => {
    if (isQuitting) {
      restartInFlight = false
      return
    }
    console.warn('[Electron] restartBackend fallback timeout firing')
    startPythonBackend()
    restartInFlight = false
  }, 8000)
  pendingTimeout.unref()
  if (pythonProcess) {
    const oldProcess = pythonProcess
    pythonProcess = null
    oldProcess.removeAllListeners('exit')
    oldProcess.once('exit', () => {
      clearTimeout(pendingTimeout)
      if (isQuitting) {
        restartInFlight = false
        return
      }
      startPythonBackend()
      restartInFlight = false
    })
    killPythonProcessGroup(oldProcess)
  } else {
    clearTimeout(pendingTimeout)
    startPythonBackend()
    restartInFlight = false
  }
}

ipcMain.handle('restart-backend', async () => {
  restartBackend(true)
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
  shell.openExternal(url).catch((err: Error) =>
    console.warn('[Electron] Failed to open external URL (IPC):', url, err.message)
  )
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

  if (isDev || frontendServer) {
    const baseUrl = frontendServer ? `http://127.0.0.1:${actualFrontendPort}` : getFrontendIndexPath()
    if (baseUrl.startsWith('http')) {
      win.loadURL(`${baseUrl}#/chart/${bondCode}`)
    } else {
      win.loadFile(baseUrl, { hash: `/chart/${bondCode}` })
    }
  } else {
    win.loadFile(getFrontendIndexPath(), {
      hash: `/chart/${bondCode}`,
    })
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

  if (isDev || frontendServer) {
    const baseUrl = frontendServer ? `http://127.0.0.1:${actualFrontendPort}` : getFrontendIndexPath()
    if (baseUrl.startsWith('http')) {
      win.loadURL(`${baseUrl}#/detail/${bondCode}`)
    } else {
      win.loadFile(baseUrl, { hash: `/detail/${bondCode}` })
    }
  } else {
    win.loadFile(getFrontendIndexPath(), {
      hash: `/detail/${bondCode}`,
    })
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

const BROADCAST_CHANNELS = new Set([
  'refresh-data', 'navigate', 'export-report', 'backend-ready',
  'backend-error', 'ws-state', 'ws-message', 'resource-updated',
  'update-status', 'window-focus', 'prefetched-market-data'
])

ipcMain.on('broadcast', (_event, channel: string, data: unknown) => {
  if (!BROADCAST_CHANNELS.has(channel)) return
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

  // Skip auto-update when no real release server is configured.
  // The default publish config points to a non-existent GitHub repo
  // (lianghua/lianghua-app), which causes noisy 404 errors and unhandled
  // promise rejections on every launch. Set LH_DISABLE_UPDATER=0 to force
  // it on, or override app-builder publish with a real provider.
  if (process.env.LH_DISABLE_UPDATER !== '0') {
    console.log('[AutoUpdater] Disabled (no release server configured)')
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
      dialog.showMessageBox(mainWindow as any, {
        type: 'info',
        title: '发现新版本',
        message: `发现新版本 ${info.version}`,
        detail: '是否立即下载更新？',
        buttons: ['下载', '稍后'],
        defaultId: 0,
      }).then((result: any) => {
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
      dialog.showMessageBox(mainWindow as any, {
        type: 'question',
        title: '更新已下载',
        message: `新版本 ${info.version} 已准备就绪`,
        detail: '是否立即安装更新？应用将重新启动。',
        buttons: ['立即安装', '稍后安装'],
        defaultId: 0,
      }).then((result: any) => {
        if (result.response === 0) {
          autoUpdater.quitAndInstall()
        }
      })
    }
  })

  // Check for updates on startup (wrapped to handle missing/private GitHub repo)
  try {
    autoUpdater.checkForUpdates().catch((err: any) => {
      console.log('[AutoUpdater] checkForUpdates failed (non-fatal):', err?.message || err)
    })
  } catch (err: any) {
    console.log('[AutoUpdater] checkForUpdates sync error (non-fatal):', err?.message || err)
  }
}

function checkForUpdates() {
  if (isDev) {
    dialog.showMessageBox(mainWindow as any, {
      type: 'info',
      title: '检查更新',
      message: '开发模式',
      detail: '自动更新功能在开发模式下不可用。',
      buttons: ['确定'],
    })
    return
  }
  if (!autoUpdater) {
    dialog.showMessageBox(mainWindow as any, {
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

ipcMain.handle('get-prefetched-market-data', () => {
  return prefetchedMarketData
})

ipcMain.handle('check-for-updates', async () => {
  if (isDev || !autoUpdater) {
    return { available: false, error: isDev ? 'Dev mode' : 'Updater not available' }
  }
  try {
    const result = await autoUpdater.checkForUpdates()
    return {
      available: !!(result?.updateInfo && result.updateInfo.version !== app.getVersion()),
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
  // NOTE: do not register any other lifecycle hooks or run startup code in the
  // second instance. The original instance handles `second-instance` below.
} else {
  app.on('second-instance', () => {
    if (mainWindow) {
      if (mainWindow.isMinimized()) mainWindow.restore()
      mainWindow.show()
      mainWindow.focus()
    }
  })

  // ---- GPU acceleration ----
  // NOTE: Both app.disableHardwareAcceleration() and --disable-gpu have been
  // shown to cause black/blank screens on Apple Silicon Macs (the window is
  // created but never paints). Rely on Electron's default GPU acceleration
  // which works reliably on modern hardware. If GPU crashes occur, handle
  // them via Electron's built-in GPU process crash handling instead.

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

  app.whenReady().then(async () => {
    // ---- Startup banner ----
    // AGENTS.md improvement #5: print asar path, port, resource paths so user
    // can immediately tell which .app instance and which port is being used
    // (when multiple builds coexist on disk).
    const asarPath = app.isPackaged
      ? path.join(process.resourcesPath, 'app.asar')
      : path.join(__dirname, '..', 'app.asar')
    console.log('============================================')
    console.log(`[LiangHua] Version:      ${APP_VERSION}`)
    console.log(`[LiangHua] Mode:         ${app.isPackaged ? 'PRODUCTION' : 'DEVELOPMENT'}`)
    console.log(`[LiangHua] CWD:          ${process.cwd()}`)
    console.log(`[LiangHua] asar path:    ${asarPath}`)
    console.log(`[LiangHua] Resources:    ${process.resourcesPath}`)
    console.log(`[LiangHua] Backend port: ${BACKEND_PORT}`)
    console.log(`[LiangHua] Frontend port:${FRONTEND_PORT}`)
    console.log(`[LiangHua] Backend URL:  ${BACKEND_URL}`)
    console.log(`[LiangHua] Frontend:     ${getFrontendIndexPath()}`)
    console.log(`[LiangHua] UserData:     ${app.getPath('userData')}`)
    console.log(`[LiangHua] PID (Electron): ${process.pid}`)
    console.log('============================================')

    // AGENTS.md improvement #1: kill any zombie lianghua daemons before
    // claiming the port. This is the root cause of the recurring
    // "打不开" reports — the previous .app's backend was still running
    // on 8766 holding the DuckDB lock.
    killStaleInstances()
    // Write our own desktop PID so the NEXT launch can find us.
    writePidFile('desktop', process.pid)

    // AGENTS.md improvement: first-run Gatekeeper guidance.
    // On macOS, the user must manually allow unsigned apps in
    // System Settings → Privacy & Security. Detect the marker file
    // and show a one-time dialog explaining how to bypass the warning.
    if (app.isPackaged && process.platform === 'darwin') {
      try {
        const firstRunFlag = path.join(app.getPath('userData'), '.first_run_done')
        if (!fs.existsSync(firstRunFlag)) {
          const result: any = await dialog.showMessageBox({
            type: 'info',
            title: '首次启动 — Gatekeeper 提示',
            message: '如果系统弹出 "无法打开，因为它来自身份不明的开发者"',
            detail: '请按以下步骤放行：\n' +
                    '1. 打开 "系统设置 → 隐私与安全性"\n' +
                    '2. 向下滚动找到 "仍要打开" 按钮并点击\n' +
                    '3. 再次双击 LiangHua 即可\n\n' +
                    '本应用使用 ad-hoc 签名（非 Apple Developer ID），属于开发构建。',
            buttons: ['我知道了', '不再提示'],
            defaultId: 0,
            cancelId: 1,
          })
          if (result.response === 0) {
            try { fs.writeFileSync(firstRunFlag, new Date().toISOString()) } catch {}
          } else {
            try { fs.writeFileSync(firstRunFlag, 'dismissed-' + new Date().toISOString()) } catch {}
          }
        }
      } catch (e) {
        console.error('[Electron] first-run check failed:', (e as Error).message)
      }
    }

    startPythonBackend()
    createApplicationMenu()
    createTrayIcon()
    // await createWindow so errors loading the frontend page are caught
    try {
      await createWindow()
    } catch (winErr) {
      console.error('[Electron] createWindow failed:', winErr)
    }
    registerGlobalShortcuts()
    setupAutoUpdater()

    app.on('activate', () => {
      if (mainWindow) {
        mainWindow.show()
        mainWindow.moveTop()
        mainWindow.focus()
      } else if (!creatingWindow && BrowserWindow.getAllWindows().length === 0) {
        creatingWindow = true
        createWindow().catch((err: any) => console.error('[Electron] activate createWindow failed:', err)).finally(() => {
          creatingWindow = false
        })
      }
    })
  })

  app.on('will-quit', () => {
    globalShortcut.unregisterAll()
    stopHealthMonitor()
    // Close frontend HTTP server
    if (frontendServer) {
      frontendServer.close()
      frontendServer = null
    }
    // Close all WebSocket connections
    for (const wsId of [...wsConnections.keys()]) {
      const ws = wsConnections.get(wsId)
      if (ws) ws.close()
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
    if (pythonRestartTimer) {
      clearTimeout(pythonRestartTimer)
      pythonRestartTimer = null
    }
    // AGENTS.md improvement #1: clean up our PID files so the next launch
    // doesn't try to kill us thinking we're a stale instance.
    removePidFile('desktop')
    if (pythonProcess) {
      removePidFile('backend')
    }
    // Persist crash reports
    try {
      const crashPath = path.join(app.getPath('userData'), 'crash-reports.json')
      fs.writeFileSync(crashPath, JSON.stringify(crashReports.slice(0, 20), null, 2))
    } catch {}
    for (const [id, win] of childWindows) {
      try { win.close() } catch {}
    }
    if (pythonProcess) {
      killPythonProcessGroup(pythonProcess)
      pythonProcess = null
    }
  })
}
