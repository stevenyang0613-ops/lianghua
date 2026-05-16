import type { ElectronAPI, UpdateStatus } from '../types/electron'

export type { ElectronAPI, UpdateStatus }

const getAPI = (): ElectronAPI | undefined => window.electronAPI as ElectronAPI | undefined

export function isElectron(): boolean {
  return typeof window !== 'undefined' && window.electronAPI?.isElectron === true
}

export function isMacOS(): boolean {
  return getAPI()?.platform === 'darwin'
}

export function isWindows(): boolean {
  return getAPI()?.platform === 'win32'
}

export function isLinux(): boolean {
  return getAPI()?.platform === 'linux'
}

export async function showNativeNotification(title: string, body: string): Promise<void> {
  const api = getAPI()
  if (api?.showNotification) {
    await api.showNotification(title, body)
  } else if ('Notification' in window) {
    if (Notification.permission === 'granted') {
      new Notification(title, { body })
    } else if (Notification.permission !== 'denied') {
      const permission = await Notification.requestPermission()
      if (permission === 'granted') {
        new Notification(title, { body })
      }
    }
  }
}

export async function requestNotificationPermission(): Promise<boolean> {
  if (isElectron()) return true
  if (!('Notification' in window)) return false
  const permission = await Notification.requestPermission()
  return permission === 'granted'
}

export async function getAppInfo() {
  return getAPI()?.getAppInfo?.() ?? null
}

export function openExternalURL(url: string): void {
  const api = getAPI()
  if (api?.openExternal) {
    api.openExternal(url)
  } else {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

export async function restartBackend(): Promise<void> {
  const api = getAPI()
  if (api?.restartBackend) {
    await api.restartBackend()
  } else {
    throw new Error('仅在桌面端可用')
  }
}

export async function checkForUpdates(): Promise<{ available: boolean; version?: string; error?: string }> {
  const api = getAPI()
  if (api?.checkForUpdates) {
    return await api.checkForUpdates()
  }
  return { available: false, error: '仅在桌面端可用' }
}

export function onUpdateStatus(callback: (status: UpdateStatus) => void): () => void {
  const api = getAPI()
  if (api?.onUpdateStatus) {
    return api.onUpdateStatus(callback)
  }
  return () => {}
}
