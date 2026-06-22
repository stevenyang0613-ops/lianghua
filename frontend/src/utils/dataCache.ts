/**
 * 数据缓存管理
 * 使用 IndexedDB 存储历史数据，支持离线访问
 * 支持智能离线模式、后台同步、数据预加载
 */

const DB_NAME = 'lianghua_cache'
const DB_VERSION = 2

interface CacheEntry {
  key: string
  data: unknown
  timestamp: number
  expiresAt: number
  // 新增字段
  version?: number
  tags?: string[]
  compressed?: boolean
}

// 离线模式状态
interface OfflineState {
  enabled: boolean
  lastSync: number | null
  pendingSync: string[]
  syncInProgress: boolean
}

const offlineState: OfflineState = {
  enabled: false,
  lastSync: null,
  pendingSync: [],
  syncInProgress: false,
}

let db: IDBDatabase | null = null

// 打开数据库
function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (db) {
      resolve(db)
      return
    }

    const request = indexedDB.open(DB_NAME, DB_VERSION)

    request.onerror = () => {
      console.error('[DataCache] IndexedDB open failed:', request.error)
      reject(request.error)
    }
    request.onsuccess = () => {
      db = request.result
      // 清理旧 localStorage 缓存条目
      migrateLocalStorageCache()
      resolve(db)
    }

    request.onupgradeneeded = (event) => {
      const database = (event.target as IDBOpenDBRequest).result

      // 缓存存储
      if (!database.objectStoreNames.contains('cache')) {
        const cacheStore = database.createObjectStore('cache', { keyPath: 'key' })
        cacheStore.createIndex('expiresAt', 'expiresAt', { unique: false })
        cacheStore.createIndex('tags', 'tags', { unique: false, multiEntry: true })
      }

      // 离线队列存储
      if (!database.objectStoreNames.contains('offline_queue')) {
        database.createObjectStore('offline_queue', { keyPath: 'id', autoIncrement: true })
      }

      // 同步状态存储
      if (!database.objectStoreNames.contains('sync_status')) {
        database.createObjectStore('sync_status', { keyPath: 'key' })
      }
    }
  })
}

// ========== 离线模式管理 ==========

// 启用离线模式
export function enableOfflineMode(): void {
  offlineState.enabled = true
  localStorage.setItem('offline_mode', 'true')
  console.log('[Offline] Mode enabled')
}

// 禁用离线模式
export function disableOfflineMode(): void {
  offlineState.enabled = false
  localStorage.setItem('offline_mode', 'false')
  console.log('[Offline] Mode disabled')
}

// 检查是否处于离线模式
export function isOfflineMode(): boolean {
  // Electron 环境下忽略 navigator.onLine（可能误判），只看显式设置
  if (window.electronAPI?.httpRequest) {
    return offlineState.enabled || localStorage.getItem('offline_mode') === 'true'
  }
  return offlineState.enabled || localStorage.getItem('offline_mode') === 'true' || !navigator.onLine
}

// 检查网络状态
export function checkNetworkStatus(): { online: boolean; effectiveType?: string } {
  const connection = (navigator as any).connection
  return {
    online: navigator.onLine,
    effectiveType: connection?.effectiveType,
  }
}

// 监听网络状态变化
export function onNetworkChange(callback: (online: boolean) => void): () => void {
  const handleOnline = () => callback(true)
  const handleOffline = () => callback(false)

  window.addEventListener('online', handleOnline)
  window.addEventListener('offline', handleOffline)

  return () => {
    window.removeEventListener('online', handleOnline)
    window.removeEventListener('offline', handleOffline)
  }
}

// ========== 离线队列管理 ==========

interface OfflineQueueItem {
  id?: number
  url: string
  method: string
  body?: string
  headers?: Record<string, string>
  timestamp: number
  retryCount: number
}

// 添加请求到离线队列
export async function addToOfflineQueue(item: Omit<OfflineQueueItem, 'id' | 'timestamp' | 'retryCount'>): Promise<void> {
  try {
    const database = await openDB()
    const tx = database.transaction('offline_queue', 'readwrite')
    const store = tx.objectStore('offline_queue')

    const queueItem: OfflineQueueItem = {
      ...item,
      timestamp: Date.now(),
      retryCount: 0,
    }

    store.add(queueItem)
    offlineState.pendingSync.push(item.url)
    console.log('[Offline] Added to queue:', item.url)
  } catch (error) {
    console.error('[Offline] Failed to add to queue:', error)
  }
}

// 获取离线队列
export async function getOfflineQueue(): Promise<OfflineQueueItem[]> {
  try {
    const database = await openDB()
    const tx = database.transaction('offline_queue', 'readonly')
    const store = tx.objectStore('offline_queue')
    const request = store.getAll()

    return new Promise((resolve) => {
      request.onsuccess = () => resolve(request.result || [])
      request.onerror = () => resolve([])
    })
  } catch {
    return []
  }
}

// 同步离线队列
export async function syncOfflineQueue(baseUrl: string): Promise<{ success: number; failed: number; errors: string[] }> {
  if (offlineState.syncInProgress) {
    return { success: 0, failed: 0, errors: ['Sync already in progress'] }
  }

  offlineState.syncInProgress = true
  const result = { success: 0, failed: 0, errors: [] as string[] }

  try {
    const queue = await getOfflineQueue()
    const database = await openDB()

    for (const item of queue) {
      try {
        let ok = false
        if (window.electronAPI?.httpRequest) {
          const body = item.body ? JSON.parse(item.body) : undefined
          const result = await window.electronAPI.httpRequest(item.method || 'POST', `${baseUrl}${item.url}`, body)
          ok = result.ok
        } else {
          const fetchResponse = await fetch(`${baseUrl}${item.url}`, {
            method: item.method,
            body: item.body,
            headers: item.headers,
          })
          ok = fetchResponse.ok
        }

        if (ok) {
          // 从队列中移除
          const tx = database.transaction('offline_queue', 'readwrite')
          const store = tx.objectStore('offline_queue')
          store.delete(item.id!)
          result.success++
        } else {
          result.failed++
          result.errors.push(`${item.url}: HTTP error`)
        }
      } catch (err) {
        result.failed++
        result.errors.push(`${item.url}: ${String(err)}`)
      }
    }

    offlineState.lastSync = Date.now()
    offlineState.pendingSync = []
  } finally {
    offlineState.syncInProgress = false
  }

  return result
}

// 清空离线队列
export async function clearOfflineQueue(): Promise<void> {
  try {
    const database = await openDB()
    const tx = database.transaction('offline_queue', 'readwrite')
    const store = tx.objectStore('offline_queue')
    store.clear()
    offlineState.pendingSync = []
  } catch (error) {
    console.error('[Offline] Failed to clear queue:', error)
  }
}

// ========== 智能数据预加载 ==========

interface PreloadConfig {
  enabled: boolean
  interval: number
  keys: string[]
  onPreload?: (key: string) => Promise<unknown>
}

const preloadConfig: PreloadConfig = {
  enabled: false,
  interval: 60000,
  keys: [],
}

let preloadTimer: ReturnType<typeof setInterval> | null = null

// 启动数据预加载
export function startPreload(config: Partial<PreloadConfig>): void {
  Object.assign(preloadConfig, config)
  preloadConfig.enabled = true

  if (preloadTimer) {
    clearInterval(preloadTimer)
  }

  // 立即执行一次
  executePreload()

  // 定期执行
  preloadTimer = setInterval(executePreload, preloadConfig.interval)
  console.log('[Preload] Started with interval:', preloadConfig.interval)
}

// 停止数据预加载
export function stopPreload(): void {
  if (preloadTimer) {
    clearInterval(preloadTimer)
    preloadTimer = null
  }
  preloadConfig.enabled = false
  console.log('[Preload] Stopped')
}

// 执行预加载
async function executePreload(): Promise<void> {
  if (!preloadConfig.onPreload || !navigator.onLine) return

  for (const key of preloadConfig.keys) {
    try {
      const data = await preloadConfig.onPreload(key)
      if (data !== undefined) {
        await saveToCache(key, data)
        console.log('[Preload] Loaded:', key)
      }
    } catch (err) {
      console.error('[Preload] Failed for', key, ':', err)
    }
  }
}

// 保存数据到缓存
export async function saveToCache(key: string, data: unknown, ttlMs: number = 24 * 60 * 60 * 1000): Promise<void> {
  try {
    const database = await openDB()
    const tx = database.transaction('cache', 'readwrite')
    const store = tx.objectStore('cache')

    const entry: CacheEntry = {
      key,
      data,
      timestamp: Date.now(),
      expiresAt: Date.now() + ttlMs,
    }

    store.put(entry)

    // 同时保存到 localStorage 作为备份
    try {
      localStorage.setItem(`cache_${key}`, JSON.stringify(entry))
      localStorage.setItem('cache_time', new Date().toLocaleString('zh-CN'))
    } catch {
      // localStorage 可能满了
    }
  } catch (error) {
    console.error('[Cache] Failed to save:', error)
  }
}

// 从缓存读取数据
export async function getFromCache<T>(key: string): Promise<T | null> {
  try {
    const database = await openDB()
    const tx = database.transaction('cache', 'readonly')
    const store = tx.objectStore('cache')
    const request = store.get(key)

    return new Promise((resolve) => {
      request.onsuccess = () => {
        const entry = request.result as CacheEntry | undefined
        if (entry && entry.expiresAt > Date.now()) {
          resolve(entry.data as T)
        } else {
          resolve(null)
        }
      }
      request.onerror = () => resolve(null)
    })
  } catch {
    return null
  }
}

// 获取原始缓存条目（含过期信息，供 getCacheStatus 使用）
export async function getCacheEntry(key: string): Promise<{ timestamp: number; expiresAt: number } | null> {
  try {
    const database = await openDB()
    const tx = database.transaction('cache', 'readonly')
    const store = tx.objectStore('cache')
    const request = store.get(key)

    return new Promise((resolve) => {
      request.onsuccess = () => {
        const entry = request.result as CacheEntry | undefined
        if (entry) {
          resolve({ timestamp: entry.timestamp, expiresAt: entry.expiresAt })
        } else {
          resolve(null)
        }
      }
      request.onerror = () => resolve(null)
    })
  } catch {
    return null
  }
}

// 迁移并清理旧 localStorage 缓存条目
export async function migrateLocalStorageCache(): Promise<void> {
  const keysToRemove: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const key = localStorage.key(i)
    if (key?.startsWith('cache_')) {
      keysToRemove.push(key)
    }
  }
  keysToRemove.forEach(key => localStorage.removeItem(key))
  if (keysToRemove.length > 0) {
    console.log(`[Cache] Migrated ${keysToRemove.length} localStorage cache entries to IndexedDB`)
  }
}

// 清除过期缓存
export async function clearExpiredCache(): Promise<void> {
  try {
    const database = await openDB()
    const tx = database.transaction('cache', 'readwrite')
    const store = tx.objectStore('cache')
    const request = store.openCursor()

    request.onsuccess = (event) => {
      const cursor = (event.target as IDBRequest).result
      if (cursor) {
        const entry = cursor.value as CacheEntry
        if (entry.expiresAt <= Date.now()) {
          cursor.delete()
        }
        cursor.continue()
      }
    }
  } catch (error) {
    console.error('[Cache] Failed to clear expired:', error)
  }
}

// 获取缓存统计信息
export async function getCacheStats(): Promise<{ count: number; oldestTime: string | null }> {
  try {
    const database = await openDB()
    const tx = database.transaction('cache', 'readonly')
    const store = tx.objectStore('cache')
    const countRequest = store.count()

    return new Promise((resolve) => {
      countRequest.onsuccess = () => {
        const count = countRequest.result
        const oldestTime = localStorage.getItem('cache_time')
        resolve({ count, oldestTime })
      }
      countRequest.onerror = () => resolve({ count: 0, oldestTime: null })
    })
  } catch {
    return { count: 0, oldestTime: localStorage.getItem('cache_time') }
  }
}

// 清除所有缓存
export async function clearAllCache(): Promise<void> {
  try {
    const database = await openDB()
    const tx = database.transaction('cache', 'readwrite')
    const store = tx.objectStore('cache')
    store.clear()

    // 清除 localStorage 缓存
    const keysToRemove: string[] = []
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i)
      if (key?.startsWith('cache_')) {
        keysToRemove.push(key)
      }
    }
    keysToRemove.forEach(key => localStorage.removeItem(key))
    localStorage.removeItem('cache_time')
  } catch (error) {
    console.error('[Cache] Failed to clear all:', error)
  }
}

// 获取所有缓存数据
export async function getAllCacheData(): Promise<{ key: string; data: unknown; timestamp: number; expiresAt: number }[]> {
  try {
    const database = await openDB()
    const tx = database.transaction('cache', 'readonly')
    const store = tx.objectStore('cache')
    const request = store.getAll()

    return new Promise((resolve) => {
      request.onsuccess = () => {
        const entries = request.result as CacheEntry[]
        resolve(entries.map(e => ({ key: e.key, data: e.data, timestamp: e.timestamp, expiresAt: e.expiresAt })))
      }
      request.onerror = () => resolve([])
    })
  } catch {
    return []
  }
}

// 导出缓存为JSON
export async function exportCacheAsJSON(): Promise<string> {
  const data = await getAllCacheData()
  return JSON.stringify(data, null, 2)
}

// 导出缓存为CSV
export async function exportCacheAsCSV(): Promise<string> {
  const data = await getAllCacheData()
  if (data.length === 0) return ''

  const headers = ['key', 'timestamp', 'expiresAt', 'dataType']
  const rows = data.map(entry => {
    const dataType = Array.isArray(entry.data) ? 'array' : typeof entry.data
    return [entry.key, new Date(entry.timestamp).toISOString(), new Date(entry.expiresAt).toISOString(), dataType]
  })

  return [headers.join(','), ...rows.map(r => r.join(','))].join('\n')
}

// 获取缓存数据的过期状态
export function getCacheExpiryStatus(expiresAt: number): { isExpired: boolean; remainingTime: string; expiredAgo: string } {
  const now = Date.now()
  const diff = expiresAt - now

  if (diff <= 0) {
    const expiredMs = Math.abs(diff)
    if (expiredMs < 60000) return { isExpired: true, remainingTime: '', expiredAgo: `${Math.floor(expiredMs / 1000)}秒前过期` }
    if (expiredMs < 3600000) return { isExpired: true, remainingTime: '', expiredAgo: `${Math.floor(expiredMs / 60000)}分钟前过期` }
    if (expiredMs < 86400000) return { isExpired: true, remainingTime: '', expiredAgo: `${Math.floor(expiredMs / 3600000)}小时前过期` }
    return { isExpired: true, remainingTime: '', expiredAgo: `${Math.floor(expiredMs / 86400000)}天前过期` }
  }

  if (diff < 60000) return { isExpired: false, remainingTime: `${Math.floor(diff / 1000)}秒`, expiredAgo: '' }
  if (diff < 3600000) return { isExpired: false, remainingTime: `${Math.floor(diff / 60000)}分钟`, expiredAgo: '' }
  if (diff < 86400000) return { isExpired: false, remainingTime: `${Math.floor(diff / 3600000)}小时`, expiredAgo: '' }
  return { isExpired: false, remainingTime: `${Math.floor(diff / 86400000)}天`, expiredAgo: '' }
}

// 缓存预热 - 加载常用数据
export async function warmupCache(): Promise<{ success: boolean; loadedKeys: string[]; errors: string[] }> {
  const result = { success: true, loadedKeys: [] as string[], errors: [] as string[] }

  // 检查是否启用预热
  if (localStorage.getItem('preload_data') !== 'true') {
    return result
  }

  // 常用缓存键列表
  const keysToWarmup = [
    'market_quotes',
    'analysis_dual-low-ranking',
    'analysis_forced-redemption',
    'analysis_pulse-scan',
  ]

  for (const key of keysToWarmup) {
    try {
      const cached = await getFromCache(key)
      if (cached) {
        result.loadedKeys.push(key)
      }
    } catch (err) {
      result.errors.push(`${key}: ${String(err)}`)
    }
  }

  return result
}

export default {
  saveToCache,
  getFromCache,
  clearExpiredCache,
  getCacheStats,
  clearAllCache,
  getAllCacheData,
  exportCacheAsJSON,
  exportCacheAsCSV,
  getCacheExpiryStatus,
  warmupCache,
  // 离线模式功能
  enableOfflineMode,
  disableOfflineMode,
  isOfflineMode,
  checkNetworkStatus,
  onNetworkChange,
  addToOfflineQueue,
  getOfflineQueue,
  syncOfflineQueue,
  clearOfflineQueue,
  startPreload,
  stopPreload,
}
