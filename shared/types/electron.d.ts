/**
 * Canonical ElectronAPI type definition — shared between electron/preload.ts and frontend.
 * BOTH sides import from here to prevent interface drift.
 *
 * See AGENTS.md #28: "keep the interface in sync with the implementation"
 */

export interface UpdateStatus {
  status: 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'
  version?: string
  percent?: number
  transferred?: number
  total?: number
  error?: string
}

export interface CrashReport {
  timestamp: number
  type: 'renderer' | 'main' | 'backend' | 'gpu'
  message: string
  stack?: string
  appVersion: string
  electronVersion: string
  platform: string
  arch: string
  memoryUsage: { rss: number; heapUsed: number; heapTotal: number; external: number; arrayBuffers: number }
  uptime: number
}

export interface ElectronAPI {
  isElectron: boolean
  platform: string
  versions: { electron: string; node: string; chrome: string }

  // Notifications
  showNotification(title: string, body: string): Promise<void>

  // Safe storage (encryption)
  encryptString(plainText: string): Promise<string>
  decryptString(cipherText: string): Promise<string>

  // App info
  getAppInfo(): Promise<{
    version: string; electronVersion: string; nodeVersion: string
    platform: string; arch: string; isDev: boolean
  }>

  // WebSocket auth token
  getWsToken(): Promise<string>

  // Backend
  restartBackend(): Promise<void>
  onBackendReady(callback: (data?: any) => void): () => void

  // Frontend reload (used by did-fail-load error page retry button)
  retryFrontendLoad(): Promise<boolean>

  // HTTP proxy for API requests (bypasses CORS/webSecurity)
  httpGet(url: string): Promise<{ ok: boolean; status: number; data: any; error?: string }>
  httpPost(url: string, body: any): Promise<{ ok: boolean; status: number; data: any; error?: string }>
  httpRequest(method: string, url: string, body?: any): Promise<{ ok: boolean; status: number; data: any; error?: string }>

  // Performance monitoring
  getPerformanceMetrics(): Promise<{
    startupTime: number; backendReadyTime: number; frontendLoadTime: number
    memoryUsage: { rss: number; heapUsed: number; heapTotal: number; external: number; arrayBuffers: number }
    cpuUsage: { user: number; system: number }
    crashCount: number; lastCrashTime: number | null; uptime: number
  }>

  // Crash reports
  getCrashReports(limit?: number): Promise<CrashReport[]>
  clearCrashReports(): Promise<{ success: boolean }>
  exportDiagnosticLogs(): Promise<{ path: string }>

  // Resource updates
  onResourceUpdated(callback: (info: { file: string; oldHash: string; newHash: string; timestamp: number }) => void): () => void

  // Window control
  minimizeWindow(): void
  maximizeWindow(): void
  closeWindow(): void
  isMaximized(): Promise<boolean>

  // Navigation
  onNavigate(callback: (route: string) => void): () => void
  onRefreshData(callback: () => void): () => void
  onExportReport(callback: () => void): () => void
  onWindowFocus(callback: (focused: boolean) => void): () => void

  // Auto-update
  checkForUpdates(): Promise<{ available: boolean; version?: string; error?: string }>
  onUpdateStatus(callback: (status: UpdateStatus) => void): () => void

  // System
  openExternal(url: string): void

  // Multi-window
  getWindows(): Promise<Array<{ id: number; type: string; title: string; bondCode?: string }>>
  createChartWindow(bondCode: string, bondName: string): Promise<{ id: number } | null>
  createDetailWindow(bondCode: string, bondName: string): Promise<{ id: number } | null>
  closeChildWindow(windowId: number): Promise<boolean>
  focusWindow(windowId: number): Promise<boolean>
  sendToWindow(windowId: number, channel: string, data: unknown): Promise<boolean>
  broadcast(channel: string, data: unknown): void
  onBroadcast(callback: (channel: string, data: unknown) => void): () => void

  // WebSocket IPC proxy
  wsConnect(wsId: string, url: string): Promise<{ ok: boolean; state: string; error?: string }>
  wsSend(wsId: string, message: string): Promise<{ ok: boolean; error?: string }>
  wsClose(wsId: string): Promise<{ ok: boolean }>
  wsState(wsId: string): Promise<{ state: string }>
  onWsState(callback: (wsId: string, state: string, code?: number, reason?: string) => void): () => void
  onWsMessage(callback: (wsId: string, data: string, isBinary: boolean) => void): () => void

  // Prefetched data from main process
  getPrefetchedMarketData(): Promise<any>
}
