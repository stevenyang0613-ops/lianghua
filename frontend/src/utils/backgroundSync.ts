/**
 * 后台数据同步服务
 * 定期同步数据保持缓存新鲜度
 */

import { fetchAllQuotes } from '../services/api'

const SYNC_INTERVAL_KEY = 'sync_interval'
const AUTO_SYNC_KEY = 'auto_sync'
const LAST_SYNC_KEY = 'last_sync_time'

let syncTimer: ReturnType<typeof setInterval> | null = null
let visibilityHandler: (() => void) | null = null

export interface SyncStatus {
  lastSyncTime: string | null
  nextSyncTime: string | null
  isRunning: boolean
  error: string | null
}

const syncStatus: SyncStatus = {
  lastSyncTime: (() => { try { return localStorage.getItem(LAST_SYNC_KEY) } catch { return null } })(),
  nextSyncTime: null,
  isRunning: false,
  error: null,
}

const listeners: Set<(status: SyncStatus) => void> = new Set()

function notifyListeners() {
  listeners.forEach(listener => listener({ ...syncStatus }))
}

export function subscribeToSyncStatus(listener: (status: SyncStatus) => void): () => void {
  listeners.add(listener)
  listener({ ...syncStatus })
  return () => listeners.delete(listener)
}

export function getSyncStatus(): SyncStatus {
  return { ...syncStatus }
}

export function getSyncInterval(): number {
  let saved: string | null = null
  try { saved = localStorage.getItem(SYNC_INTERVAL_KEY) } catch { /* localStorage unavailable */ }
  const parsed = saved ? parseInt(saved, 10) : 5 * 60 * 1000
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 5 * 60 * 1000
}

export function setSyncInterval(intervalMs: number): void {
  try { localStorage.setItem(SYNC_INTERVAL_KEY, String(intervalMs)) } catch { /* silent fail */ }
  if (syncTimer) {
    stopBackgroundSync()
    startBackgroundSync()
  }
}

export function isAutoSyncEnabled(): boolean {
  try { return localStorage.getItem(AUTO_SYNC_KEY) === 'true' } catch { return false }
}

async function performSync(): Promise<void> {
  if (syncStatus.isRunning) return

  syncStatus.isRunning = true
  syncStatus.error = null
  notifyListeners()

  try {
    await fetchAllQuotes()
    const now = new Date().toLocaleString('zh-CN')
    try {
      localStorage.setItem(LAST_SYNC_KEY, now)
      localStorage.setItem('cache_time', now)
    } catch { /* localStorage unavailable, sync status kept in memory */ }

    syncStatus.lastSyncTime = now
    syncStatus.error = null
  } catch (err) {
    syncStatus.error = err instanceof Error ? err.message : String(err)
    console.error('[BackgroundSync] Sync failed:', err)
  } finally {
    syncStatus.isRunning = false
    syncStatus.nextSyncTime = new Date(Date.now() + getSyncInterval()).toLocaleString('zh-CN')
    notifyListeners()
  }
}

export function startBackgroundSync(): void {
  if (syncTimer) return
  if (!isAutoSyncEnabled()) return

  console.log('[BackgroundSync] Starting background sync, interval:', getSyncInterval() / 1000, 'seconds')

  // 首次同步
  performSync()

  // 定时同步
  syncTimer = setInterval(performSync, getSyncInterval())

  syncStatus.nextSyncTime = new Date(Date.now() + getSyncInterval()).toLocaleString('zh-CN')
  notifyListeners()
}

export function stopBackgroundSync(): void {
  if (syncTimer) {
    clearInterval(syncTimer)
    syncTimer = null
    console.log('[BackgroundSync] Stopped')
  }
  syncStatus.nextSyncTime = null
  notifyListeners()
}

export function triggerManualSync(): Promise<void> {
  return performSync()
}

export function initBackgroundSync(): void {
  if (isAutoSyncEnabled()) {
    startBackgroundSync()
  }
  // Register visibilitychange listener inside init to avoid duplicate registration on re-import
  if (typeof document !== 'undefined' && !visibilityHandler) {
    visibilityHandler = () => {
      if (document.visibilityState === 'visible' && isAutoSyncEnabled()) {
        const lastSync = localStorage.getItem(LAST_SYNC_KEY)
        if (lastSync) {
          const lastSyncTime = new Date(lastSync).getTime()
          const now = Date.now()
          const interval = getSyncInterval()
          // 如果上次同步时间超过一个周期，触发同步
          if (now - lastSyncTime > interval) {
            console.log('[BackgroundSync] Triggering sync due to page visibility change')
            performSync()
          }
        }
      }
    }
    document.addEventListener('visibilitychange', visibilityHandler)
  }
}

// 页面可见性变化时触发同步
// NOTE: moved into initBackgroundSync() to avoid duplicate registration on re-import

export function cleanupBackgroundSync(): void {
  stopBackgroundSync()
  if (visibilityHandler && typeof document !== 'undefined') {
    document.removeEventListener('visibilitychange', visibilityHandler)
    visibilityHandler = null
  }
}

export default {
  startBackgroundSync,
  stopBackgroundSync,
  triggerManualSync,
  getSyncStatus,
  subscribeToSyncStatus,
  getSyncInterval,
  setSyncInterval,
  isAutoSyncEnabled,
  initBackgroundSync,
  cleanupBackgroundSync,
}
