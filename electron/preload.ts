import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron'
import type { ElectronAPI, UpdateStatus, CrashReport } from '../shared/types/electron'

// Event listeners storage for cleanup — each registration gets a unique key
let listenerCounter = 0
const listeners: Map<string, (...args: any[]) => void> = new Map()

const api: ElectronAPI = {
  isElectron: true,
  platform: process.platform,
  versions: {
    electron: process.versions.electron,
    node: process.versions.node,
    chrome: process.versions.chrome,
  },

  // Notifications
  showNotification: (title: string, body: string) =>
    ipcRenderer.invoke('show-notification', { title, body }),

  // Safe storage (encryption)
  encryptString: (plainText: string) => ipcRenderer.invoke('encrypt-string', plainText),
  decryptString: (cipherText: string) => ipcRenderer.invoke('decrypt-string', cipherText),

  // App info
  getAppInfo: () => ipcRenderer.invoke('get-app-info'),

  // WebSocket auth token
  getWsToken: () => ipcRenderer.invoke('get-ws-token'),

  // Backend
  restartBackend: () => ipcRenderer.invoke('restart-backend'),

  // HTTP proxy for API requests (bypasses CORS/webSecurity)
  httpGet: (url: string) => ipcRenderer.invoke('http-get', url),
  httpPost: (url: string, body: any) => ipcRenderer.invoke('http-post', url, body),
  httpRequest: (method: string, url: string, body?: any) => ipcRenderer.invoke('http-request', method, url, body),

  // Frontend reload
  retryFrontendLoad: () => ipcRenderer.invoke('retry-frontend-load'),

  // Backend ready event
  onBackendReady: (callback: (data?: any) => void) => {
    const key = `backend-ready-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, data?: any) => callback(data)
    ipcRenderer.on('backend-ready', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('backend-ready', listener)
      listeners.delete(key)
    }
  },

  // Performance monitoring
  getPerformanceMetrics: () => ipcRenderer.invoke('get-performance-metrics'),

  // Crash reports
  getCrashReports: (limit?: number) => ipcRenderer.invoke('get-crash-reports', limit),
  clearCrashReports: () => ipcRenderer.invoke('clear-crash-reports'),
  exportDiagnosticLogs: () => ipcRenderer.invoke('export-diagnostic-logs'),

  // Resource updates
  onResourceUpdated: (callback: (info: { file: string; oldHash: string; newHash: string; timestamp: number }) => void) => {
    const key = `resource-updated-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, info: { file: string; oldHash: string; newHash: string; timestamp: number }) => callback(info)
    ipcRenderer.on('resource-updated', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('resource-updated', listener)
      listeners.delete(key)
    }
  },

  // Window control
  minimizeWindow: () => ipcRenderer.send('window-minimize'),
  maximizeWindow: () => ipcRenderer.send('window-maximize'),
  closeWindow: () => ipcRenderer.send('window-close'),
  isMaximized: () => ipcRenderer.invoke('window-is-maximized'),

  // Navigation events
  onNavigate: (callback: (route: string) => void) => {
    const key = `navigate-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, route: string) => callback(route)
    ipcRenderer.on('navigate', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('navigate', listener)
      listeners.delete(key)
    }
  },

  onRefreshData: (callback: () => void) => {
    const key = `refresh-data-${listenerCounter++}`
    const listener = () => callback()
    ipcRenderer.on('refresh-data', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('refresh-data', listener)
      listeners.delete(key)
    }
  },

  onExportReport: (callback: () => void) => {
    const key = `export-report-${listenerCounter++}`
    const listener = () => callback()
    ipcRenderer.on('export-report', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('export-report', listener)
      listeners.delete(key)
    }
  },

  onWindowFocus: (callback: (focused: boolean) => void) => {
    const key = `window-focus-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, focused: boolean) => callback(focused)
    ipcRenderer.on('window-focus', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('window-focus', listener)
      listeners.delete(key)
    }
  },

  // Auto-update
  checkForUpdates: () => ipcRenderer.invoke('check-for-updates'),

  onUpdateStatus: (callback: (status: UpdateStatus) => void) => {
    const key = `update-status-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, status: UpdateStatus) => callback(status)
    ipcRenderer.on('update-status', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('update-status', listener)
      listeners.delete(key)
    }
  },

  // System
  openExternal: (url: string) => ipcRenderer.send('open-external', url),

  // Multi-window
  getWindows: () => ipcRenderer.invoke('get-windows'),
  createChartWindow: (bondCode: string, bondName: string) => ipcRenderer.invoke('create-chart-window', bondCode, bondName),
  createDetailWindow: (bondCode: string, bondName: string) => ipcRenderer.invoke('create-detail-window', bondCode, bondName),
  closeChildWindow: (windowId: number) => ipcRenderer.invoke('close-window', windowId),
  focusWindow: (windowId: number) => ipcRenderer.invoke('focus-window', windowId),
  sendToWindow: (windowId: number, channel: string, data: unknown) => ipcRenderer.invoke('send-to-window', windowId, channel, data),
  broadcast: (channel: string, data: unknown) => ipcRenderer.send('broadcast', channel, data),
  onBroadcast: (callback: (channel: string, data: unknown) => void) => {
    const key = `broadcast-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, channel: string, data: unknown) => callback(channel, data)
    ipcRenderer.on('broadcast', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('broadcast', listener)
      listeners.delete(key)
    }
  },

  // WebSocket IPC proxy
  wsConnect: (wsId: string, url: string) => ipcRenderer.invoke('ws-connect', wsId, url),
  wsSend: (wsId: string, message: string) => ipcRenderer.invoke('ws-send', wsId, message),
  wsClose: (wsId: string) => ipcRenderer.invoke('ws-close', wsId),
  wsState: (wsId: string) => ipcRenderer.invoke('ws-state', wsId),
  onWsState: (callback: (wsId: string, state: string, code?: number, reason?: string) => void) => {
    const key = `ws-state-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, wsId: string, state: string, code?: number, reason?: string) => callback(wsId, state, code, reason)
    ipcRenderer.on('ws-state', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('ws-state', listener)
      listeners.delete(key)
    }
  },
  onWsMessage: (callback: (wsId: string, data: string, isBinary: boolean) => void) => {
    const key = `ws-message-${listenerCounter++}`
    const listener = (_event: IpcRendererEvent, wsId: string, data: string, isBinary: boolean) => callback(wsId, data, isBinary)
    ipcRenderer.on('ws-message', listener)
    listeners.set(key, listener)
    return () => {
      ipcRenderer.removeListener('ws-message', listener)
      listeners.delete(key)
    }
  },

  // Prefetched data from main process
  getPrefetchedMarketData: () => ipcRenderer.invoke('get-prefetched-market-data'),
}

contextBridge.exposeInMainWorld('electronAPI', api)

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}
