/**
 * Type definitions for Electron API
 * Shared between main and renderer processes
 */

export interface ElectronAPI {
  /** Indicates if running in Electron environment */
  readonly isElectron: boolean

  /** Current platform */
  readonly platform: string

  /** Version information */
  readonly versions: {
    electron: string
    node: string
    chrome: string
  }

  /**
   * Show a native notification
   * @param title - Notification title
   * @param body - Notification body text
   */
  showNotification(title: string, body: string): Promise<void>

  /**
   * Get application information
   */
  getAppInfo(): Promise<{
    version: string
    electronVersion: string
    nodeVersion: string
    platform: string
    arch: string
    isDev: boolean
  }>

  /**
   * Restart the Python backend service
   */
  restartBackend(): Promise<void>

  /**
   * Minimize the window
   */
  minimizeWindow(): void

  /**
   * Maximize/unmaximize the window
   */
  maximizeWindow(): void

  /**
   * Close the window (hides to tray)
   */
  closeWindow(): void

  /**
   * Check if window is maximized
   */
  isMaximized(): Promise<boolean>

  /**
   * Listen for navigation events from menu
   * @param callback - Called when menu navigation occurs
   * @returns Unsubscribe function
   */
  onNavigate(callback: (route: string) => void): () => void

  /**
   * Listen for refresh data events
   * @param callback - Called when refresh is requested
   * @returns Unsubscribe function
   */
  onRefreshData(callback: () => void): () => void

  /**
   * Listen for export report events
   * @param callback - Called when export is requested
   * @returns Unsubscribe function
   */
  onExportReport(callback: () => void): () => void

  /**
   * Listen for window focus events
   * @param callback - Called when window focus changes
   * @returns Unsubscribe function
   */
  onWindowFocus(callback: (focused: boolean) => void): () => void

  /**
   * Open URL in external browser
   * @param url - URL to open
   */
  openExternal(url: string): void
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
