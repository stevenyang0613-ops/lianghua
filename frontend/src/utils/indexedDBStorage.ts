/**
 * IndexedDB 数据持久化服务
 * 用于大数据量本地存储
 */

const DB_NAME = 'lianghua_db'
const DB_VERSION = 1

interface DBSchema {
  bonds: { key: string; value: { code: string; data: unknown; timestamp: number } }
  quotes: { key: string; value: { code: string; quotes: unknown[]; timestamp: number } }
  signals: { key: string; value: { id: string; signal: unknown; timestamp: number } }
  kline: { key: string; value: { code: string; period: string; data: unknown[]; timestamp: number } }
  cache: { key: string; value: { key: string; data: unknown; expiry: number } }
}

type StoreNames = keyof DBSchema

class IndexedDBStorage {
  private db: IDBDatabase | null = null
  private initPromise: Promise<IDBDatabase> | null = null

  async init(): Promise<IDBDatabase> {
    if (this.db) return this.db
    if (this.initPromise) return this.initPromise

    this.initPromise = new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION)

      request.onerror = () => reject(request.error)
      request.onsuccess = () => { this.db = request.result; resolve(this.db) }

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        if (!db.objectStoreNames.contains('bonds')) {
          db.createObjectStore('bonds', { keyPath: 'code' })
        }
        if (!db.objectStoreNames.contains('quotes')) {
          db.createObjectStore('quotes', { keyPath: 'code' })
        }
        if (!db.objectStoreNames.contains('signals')) {
          db.createObjectStore('signals', { keyPath: 'id' })
        }
        if (!db.objectStoreNames.contains('kline')) {
          db.createObjectStore('kline', { keyPath: ['code', 'period'] })
        }
        if (!db.objectStoreNames.contains('cache')) {
          const cacheStore = db.createObjectStore('cache', { keyPath: 'key' })
          cacheStore.createIndex('by-expiry', 'expiry', { unique: false })
        }
      }
    })

    return this.initPromise
  }

  async save<K extends StoreNames>(storeName: K, data: DBSchema[K]['value']): Promise<void> {
    const db = await this.init()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readwrite')
      const request = transaction.objectStore(storeName).put(data)
      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  async saveBatch<K extends StoreNames>(storeName: K, dataList: DBSchema[K]['value'][]): Promise<void> {
    const db = await this.init()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readwrite')
      const store = transaction.objectStore(storeName)
      dataList.forEach(data => store.put(data))
      transaction.oncomplete = () => resolve()
      transaction.onerror = () => reject(transaction.error)
    })
  }

  async get<K extends StoreNames>(storeName: K, key: IDBValidKey): Promise<DBSchema[K]['value'] | undefined> {
    const db = await this.init()
    return new Promise((resolve, reject) => {
      const request = db.transaction(storeName, 'readonly').objectStore(storeName).get(key)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  }

  async getAll<K extends StoreNames>(storeName: K): Promise<DBSchema[K]['value'][]> {
    const db = await this.init()
    return new Promise((resolve, reject) => {
      const request = db.transaction(storeName, 'readonly').objectStore(storeName).getAll()
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  }

  async delete<K extends StoreNames>(storeName: K, key: IDBValidKey): Promise<void> {
    const db = await this.init()
    return new Promise((resolve, reject) => {
      const request = db.transaction(storeName, 'readwrite').objectStore(storeName).delete(key)
      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  async clear<K extends StoreNames>(storeName: K): Promise<void> {
    const db = await this.init()
    return new Promise((resolve, reject) => {
      const request = db.transaction(storeName, 'readwrite').objectStore(storeName).clear()
      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  async setCache(key: string, data: unknown, ttlMs = 3600000): Promise<void> {
    await this.save('cache', { key, data, expiry: Date.now() + ttlMs })
  }

  async getCache<T>(key: string): Promise<T | null> {
    const cached = await this.get('cache', key)
    if (!cached) return null
    if (cached.expiry < Date.now()) {
      await this.delete('cache', key)
      return null
    }
    return cached.data as T
  }

  async cleanExpiredCache(): Promise<number> {
    const db = await this.init()
    let deleted = 0
    return new Promise((resolve, reject) => {
      const transaction = db.transaction('cache', 'readwrite')
      const index = transaction.objectStore('cache').index('by-expiry')
      const request = index.openCursor(IDBKeyRange.upperBound(Date.now()))
      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result
        if (cursor) { cursor.delete(); deleted++; cursor.continue() }
        else resolve(deleted)
      }
      request.onerror = () => reject(request.error)
    })
  }

  async getStorageEstimate(): Promise<{ usage: number; quota: number }> {
    if ('storage' in navigator && 'estimate' in navigator.storage) {
      const estimate = await navigator.storage.estimate()
      return { usage: estimate.usage || 0, quota: estimate.quota || 0 }
    }
    return { usage: 0, quota: 0 }
  }

  async saveKlineData(code: string, period: string, data: unknown[]): Promise<void> {
    await this.save('kline', { code, period, data, timestamp: Date.now() })
  }

  async getKlineData(code: string, period: string): Promise<unknown[] | null> {
    const result = await this.get('kline', [code, period] as unknown as IDBValidKey)
    return result?.data || null
  }

  async saveBonds(bonds: Array<{ code: string; data: unknown }>): Promise<void> {
    await this.saveBatch('bonds', bonds.map(b => ({ code: b.code, data: b.data, timestamp: Date.now() })))
  }

  async getBond(code: string): Promise<unknown | null> {
    const result = await this.get('bonds', code)
    return result?.data || null
  }

  /**
   * 自动清理策略配置
   */
  private cleanupConfig = {
    enabled: true,
    interval: 3600000, // 1小时清理一次
    maxAge: {
      bonds: 86400000,      // 1天
      quotes: 300000,       // 5分钟
      signals: 604800000,   // 7天
      kline: 2592000000,    // 30天
      cache: 3600000,       // 1小时
    },
    maxRecords: {
      bonds: 500,
      quotes: 1000,
      signals: 10000,
      kline: 500,
      cache: 1000,
    },
  }

  private cleanupTimer: ReturnType<typeof setInterval> | null = null

  /**
   * 启动自动清理
   */
  startAutoCleanup(): void {
    if (this.cleanupTimer) return

    this.cleanupTimer = setInterval(() => {
      this.runCleanup()
    }, this.cleanupConfig.interval)

    // 启动时也运行一次
    setTimeout(() => this.runCleanup(), 10000)
  }

  /**
   * 停止自动清理
   */
  stopAutoCleanup(): void {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer)
      this.cleanupTimer = null
    }
  }

  /**
   * 执行清理
   */
  async runCleanup(): Promise<{
    expired: number
    overflow: number
    freed: number
  }> {
    if (!this.cleanupConfig.enabled) {
      return { expired: 0, overflow: 0, freed: 0 }
    }

    let expired = 0
    let overflow = 0

    try {
      // 清理过期缓存
      expired = await this.cleanExpiredCache()

      // 清理超出数量限制的数据
      for (const storeName of Object.keys(this.cleanupConfig.maxRecords) as StoreNames[]) {
        const maxRecords = this.cleanupConfig.maxRecords[storeName]
        const count = await this.getStoreCount(storeName)

        if (count > maxRecords) {
          const removed = await this.removeOldestRecords(storeName, count - maxRecords)
          overflow += removed
        }
      }

      // 清理过期的带时间戳数据
      for (const storeName of ['bonds', 'quotes', 'signals', 'kline'] as StoreNames[]) {
        const maxAge = this.cleanupConfig.maxAge[storeName]
        if (maxAge) {
          const removed = await this.cleanExpiredByTimestamp(storeName, Date.now() - maxAge)
          expired += removed
        }
      }

      // 强制 GC（如果可用）
      if ('gc' in window) {
        (window as any).gc()
      }

      console.log(`[IndexedDB] Cleanup completed: expired=${expired}, overflow=${overflow}`)
    } catch (error) {
      console.error('[IndexedDB] Cleanup error:', error)
    }

    return { expired, overflow, freed: expired + overflow }
  }

  /**
   * 获取存储记录数量
   */
  async getStoreCount(storeName: StoreNames): Promise<number> {
    const db = await this.init()
    return new Promise((resolve, reject) => {
      const request = db.transaction(storeName, 'readonly').objectStore(storeName).count()
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 删除最旧的记录
   */
  private async removeOldestRecords(storeName: StoreNames, count: number): Promise<number> {
    const db = await this.init()
    let removed = 0

    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readwrite')
      const store = transaction.objectStore(storeName)

      // 如果有时间戳索引，按时间排序
      const request = store.openCursor()

      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result
        if (cursor && removed < count) {
          cursor.delete()
          removed++
          cursor.continue()
        } else {
          resolve(removed)
        }
      }
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 清理过期的带时间戳数据
   */
  private async cleanExpiredByTimestamp(storeName: StoreNames, cutoffTime: number): Promise<number> {
    const db = await this.init()
    let removed = 0

    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readwrite')
      const store = transaction.objectStore(storeName)
      const request = store.openCursor()

      request.onsuccess = (event) => {
        const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result
        if (cursor) {
          const record = cursor.value
          if (record.timestamp && record.timestamp < cutoffTime) {
            cursor.delete()
            removed++
          }
          cursor.continue()
        } else {
          resolve(removed)
        }
      }
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 获取数据库统计信息
   */
  async getStats(): Promise<{
    stores: Array<{ name: string; count: number; size: number }>
    totalRecords: number
    estimatedSize: number
  }> {
    await this.init()
    const stores: Array<{ name: string; count: number; size: number }> = []
    let totalRecords = 0
    let estimatedSize = 0

    for (const storeName of ['bonds', 'quotes', 'signals', 'kline', 'cache'] as StoreNames[]) {
      const count = await this.getStoreCount(storeName)
      const avgSize = 500 // 估算每条记录 500 字节
      const size = count * avgSize

      stores.push({ name: storeName, count, size })
      totalRecords += count
      estimatedSize += size
    }

    return { stores, totalRecords, estimatedSize }
  }

  /**
   * 设置清理配置
   */
  setCleanupConfig(config: Partial<typeof IndexedDBStorage.prototype.cleanupConfig>): void {
    this.cleanupConfig = { ...this.cleanupConfig, ...config }
  }
}

export const indexedDBStorage = new IndexedDBStorage()
export const initDB = () => indexedDBStorage.init()
export const saveToDB = <K extends StoreNames>(store: K, data: DBSchema[K]['value']) => indexedDBStorage.save(store, data)
export const getFromDB = <K extends StoreNames>(store: K, key: IDBValidKey) => indexedDBStorage.get(store, key)
export const setCache = (key: string, data: unknown, ttl?: number) => indexedDBStorage.setCache(key, data, ttl)
export const getCache = <T>(key: string) => indexedDBStorage.getCache<T>(key)
export default indexedDBStorage
