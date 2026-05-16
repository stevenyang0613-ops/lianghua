export {}

declare global {
  interface UpdateStatus {
    status: 'checking' | 'available' | 'not-available' | 'downloading' | 'downloaded' | 'error'
    version?: string
    percent?: number
    transferred?: number
    total?: number
    error?: string
  }

  interface ElectronAPI {
    readonly isElectron: boolean
    readonly platform: string
    readonly versions: { electron: string; node: string; chrome: string }
    showNotification(title: string, body: string): Promise<void>
    encryptString(plainText: string): Promise<string>
    decryptString(cipherText: string): Promise<string>
    getAppInfo(): Promise<{ version: string; electronVersion: string; nodeVersion: string; platform: string; arch: string; isDev: boolean }>
    restartBackend(): Promise<void>
    httpGet(url: string): Promise<{ ok: boolean; status: number; data: any; error?: string }>
    httpPost(url: string, body: any): Promise<{ ok: boolean; status: number; data: any; error?: string }>
    httpRequest(method: string, url: string, body?: any): Promise<{ ok: boolean; status: number; data: any; error?: string }>
    onBackendReady(callback: () => void): () => void
    getPerformanceMetrics(): Promise<{ startupTime: number; backendReadyTime: number; frontendLoadTime: number; memoryUsage: any; cpuUsage: any; crashCount: number; lastCrashTime: number | null; uptime: number }>
    getCrashReports(limit?: number): Promise<any[]>
    clearCrashReports(): Promise<{ success: boolean }>
    exportDiagnosticLogs(): Promise<{ path: string }>
    onResourceUpdated(callback: (info: any) => void): () => void
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
    wsConnect(wsId: string, url: string): Promise<{ ok: boolean; state: string; error?: string }>
    wsSend(wsId: string, message: string): Promise<{ ok: boolean; error?: string }>
    wsClose(wsId: string): Promise<{ ok: boolean }>
    wsState(wsId: string): Promise<{ state: string }>
    onWsState(callback: (wsId: string, state: string, code?: number, reason?: string) => void): () => void
    onWsMessage(callback: (wsId: string, data: string, isBinary: boolean) => void): () => void
    getWindows(): Promise<Array<{ id: number; type: string; title: string; bondCode?: string }>>
    createChartWindow(bondCode: string, bondName: string): Promise<{ id: number } | null>
    createDetailWindow(bondCode: string, bondName: string): Promise<{ id: number } | null>
    closeChildWindow(windowId: number): Promise<boolean>
    focusWindow(windowId: number): Promise<boolean>
    sendToWindow(windowId: number, channel: string, data: unknown): Promise<boolean>
    broadcast(channel: string, data: unknown): void
    onBroadcast(callback: (channel: string, data: unknown) => void): () => void
  }

  interface Window {
    electronAPI?: ElectronAPI
  }
}