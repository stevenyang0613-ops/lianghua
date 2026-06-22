import type { ElectronAPI } from './types/electron'

declare global {
  interface Window {
    electronAPI?: ElectronAPI
    /** 在 Electron main 进程通过 preload 注入的 API base URL */
    __API_BASE__?: string
  }

  interface Navigator {
    /** IE / 老浏览器语言字段 */
    userLanguage?: string
    /** Network Information API (Chrome only) */
    connection?: {
      effectiveType?: '2g' | '3g' | '4g' | 'slow-2g'
      downlink?: number
      rtt?: number
      saveData?: boolean
      addEventListener?: (type: string, listener: () => void) => void
      removeEventListener?: (type: string, listener: () => void) => void
    }
    mozConnection?: Navigator['connection']
    webkitConnection?: Navigator['connection']
  }

  interface Performance {
    /** Chrome only: memory info */
    memory?: {
      usedJSHeapSize: number
      totalJSHeapSize: number
      jsHeapSizeLimit: number
    }
  }

  interface PerformanceEntry {
    /** Layout-Shift-only: whether the shift was user-input driven */
    hadRecentInput?: boolean
    /** Layout-Shift-only: shift value */
    value?: number
  }

  interface Window {
    /** Chrome DevTools: force GC */
    gc?: () => void
    /** Safari webkit audio context */
    webkitAudioContext?: typeof AudioContext
  }
}

export {}
