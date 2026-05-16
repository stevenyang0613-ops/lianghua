/**
 * Electron 环境检测工具
 */

// 重新导出类型供其他模块使用
export type { ElectronAPI } from '../types/electron.d'

/**
 * 检查是否运行在 Electron 环境
 */
export function isElectron(): boolean {
  return typeof window !== 'undefined' && window.electronAPI?.isElectron === true
}

/**
 * 获取 Electron API
 */
export function getElectronAPI() {
  return window.electronAPI
}

/**
 * 检查是否为 macOS
 */
export function isMacOS(): boolean {
  return window.electronAPI?.platform === 'darwin'
}

/**
 * 检查是否为 Windows
 */
export function isWindows(): boolean {
  return window.electronAPI?.platform === 'win32'
}

/**
 * 检查是否为 Linux
 */
export function isLinux(): boolean {
  return window.electronAPI?.platform === 'linux'
}

/**
 * 显示原生通知
 */
export async function showNativeNotification(title: string, body: string): Promise<void> {
  const api = window.electronAPI
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

/**
 * 请求通知权限
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (isElectron()) {
    return true
  }
  if (!('Notification' in window)) {
    return false
  }
  const permission = await Notification.requestPermission()
  return permission === 'granted'
}

/**
 * 获取应用信息
 */
export async function getAppInfo() {
  const api = window.electronAPI
  if (api?.getAppInfo) {
    return await api.getAppInfo()
  }
  return null
}

/**
 * 在默认浏览器中打开外部链接
 */
export function openExternalURL(url: string): void {
  const api = window.electronAPI
  if (api?.openExternal) {
    api.openExternal(url)
  } else {
    window.open(url, '_blank', 'noopener,noreferrer')
  }
}

/**
 * 重启后端服务
 */
export async function restartBackend(): Promise<void> {
  const api = window.electronAPI
  if (api?.restartBackend) {
    await api.restartBackend()
  } else {
    throw new Error('后端重启功能仅在桌面端可用')
  }
}

/**
 * 检查应用更新
 */
export async function checkForUpdates(): Promise<{ available: boolean; version?: string; error?: string }> {
  const api = window.electronAPI
  if (api?.checkForUpdates) {
    return await api.checkForUpdates()
  }
  return { available: false, error: '此功能仅在桌面端可用' }
}

/**
 * 监听更新状态变化
 */
export function onUpdateStatus(callback: (status: import('../types/electron').UpdateStatus) => void): () => void {
  const api = window.electronAPI
  if (api?.onUpdateStatus) {
    return api.onUpdateStatus(callback)
  }
  return () => {}
}
