/**
 * Electron API 全局类型声明
 * 统一定义 window.electronAPI 的类型
 */

export interface UpdateStatus {
  status: 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'
  version?: string
  percent?: number
  transferred?: number
  total?: number
  error?: string
}

export interface ElectronAPI {
  readonly isElectron: boolean
  readonly platform: NodeJS.Platform
  readonly versions: {
    electron: string
    node: string
    chrome: string
  }
  showNotification(title: string, body: string): Promise<void>
  encryptString(plainText: string): Promise<string>
  decryptString(cipherText: string): Promise<string>
  getAppInfo(): Promise<{
    version: string
    electronVersion: string
    nodeVersion: string
    platform: string
    arch: string
    isDev: boolean
  }>
  restartBackend(): Promise<void>
  // HTTP proxy for API requests (bypasses CORS/webSecurity)
  httpGet(url: string): Promise<{ ok: boolean; status: number; data: any; error?: string }>
  httpPost(url: string, body: any): Promise<{ ok: boolean; status: number; data: any; error?: string }>
  httpRequest(method: string, url: string, body?: any): Promise<{ ok: boolean; status: number; data: any; error?: string }>
  onBackendReady(callback: () => void): () => void
  // Performance metrics
  getPerformanceMetrics(): Promise<{
    startupTime: number
    backendReadyTime: number
    frontendLoadTime: number
    memoryUsage: { rss: number; heapTotal: number; heapUsed: number; external: number }
    cpuUsage: { user: number; system: number }
    crashCount: number
    lastCrashTime: number | null
    uptime: number
  }>
  // Crash reports
  getCrashReports(limit?: number): Promise<Array<{
    timestamp: number
    type: string
    message: string
    stack?: string
    appVersion: string
    electronVersion: string
    platform: string
    arch: string
    memoryUsage: { rss: number; heapTotal: number; heapUsed: number }
    uptime: number
  }>>
  clearCrashReports(): Promise<{ success: boolean }>
  exportDiagnosticLogs(): Promise<{ path: string }>
  // Resource updates
  onResourceUpdated(callback: (info: { file: string; oldHash: string; newHash: string; timestamp: number }) => void): () => void
  minimizeWindow(): void
  maximizeWindow(): void
  closeWindow(): void
  isMaximized(): Promise<boolean>
  onNavigate(callback: (route: string) => void): () => void
  onRefreshData(callback: () => void): () => void
  onExportReport(callback: () => void): () => void
  onWindowFocus(callback: (focused: boolean) => void): () => void
  openExternal(url: string): void
  checkForUpdates(): Promise<{ available: boolean; version?: string; error?: string }>
  onUpdateStatus(callback: (status: UpdateStatus) => void): () => void
  // WebSocket IPC proxy
  wsConnect(wsId: string, url: string): Promise<{ ok: boolean; state: string; error?: string }>
  wsSend(wsId: string, message: string): Promise<{ ok: boolean; error?: string }>
  wsClose(wsId: string): Promise<{ ok: boolean }>
  wsState(wsId: string): Promise<{ state: string }>
  onWsState(callback: (wsId: string, state: string, code?: number, reason?: string) => void): () => void
  onWsMessage(callback: (wsId: string, data: string, isBinary: boolean) => void): () => void
  // Multi-window
  getWindows(): Promise<Array<{ id: number; type: string; title: string; bondCode?: string }>>
  createChartWindow(bondCode: string, bondName: string): Promise<{ id: number } | null>
  createDetailWindow(bondCode: string, bondName: string): Promise<{ id: number } | null>
  closeChildWindow(windowId: number): Promise<boolean>
  focusWindow(windowId: number): Promise<boolean>
  sendToWindow(windowId: number, channel: string, data: unknown): Promise<boolean>
  broadcast(channel: string, data: unknown): void
  onBroadcast(callback: (channel: string, data: unknown) => void): () => void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
