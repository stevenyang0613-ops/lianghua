/// <reference types="vite/client" />

interface Window {
  electronAPI?: {
    isElectron: boolean
    showNotification: (title: string, body: string) => Promise<void>
    getAppInfo: () => Promise<{
      version: string
      electronVersion: string
      nodeVersion: string
      platform: string
      arch: string
      isDev: boolean
    }>
    restartBackend: () => Promise<void>
  }
}