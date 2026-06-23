/**
 * 请求缓存层
 * 内存 + IndexedDB 双层缓存
 */

interface CacheEntry<T> {
  data: T
  timestamp: number
  expiry: number
  etag?: string
  lastModified?: string
}

interface CacheConfig {
  ttl: number // 缓存时间（毫秒）
  maxSize: number // 最大缓存条目数
  persistToIndexedDB: boolean
}

const defaultConfig: CacheConfig = {
  ttl: 300000, // 5分钟
  maxSize: 1000,
  persistToIndexedDB: true,
}

class RequestCache {
  private memoryCache: Map<string, CacheEntry<unknown>> = new Map()
  private config: CacheConfig
  private pendingRequests: Map<string, Promise<unknown>> = new Map()
  private dbName = 'lianghua-request-cache'
  private db: IDBDatabase | null = null
  private initPromise: Promise<void> | null = null

  constructor(config: Partial<CacheConfig> = {}) {
    this.config = { ...defaultConfig, ...config }
    this.initPromise = this.initDB()
  }

  /**
   * 初始化 IndexedDB
   */
  private async initDB(): Promise<void> {
    if (!this.config.persistToIndexedDB) return
    if (typeof indexedDB === 'undefined') return

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, 1)

      request.onerror = () => reject(request.error)
      request.onsuccess = () => {
        this.db = request.result
        resolve()
      }

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        if (!db.objectStoreNames.contains('cache')) {
          const store = db.createObjectStore('cache', { keyPath: 'key' })
          store.createIndex('by-expiry', 'expiry')
        }
      }
    })
  }

  /**
   * 生成缓存键
   */
  private generateKey(url: string, options?: RequestInit): string {
    const method = options?.method || 'GET'
    const body = options?.body ? JSON.stringify(options.body) : ''
    return `${method}:${url}:${body}`
  }

  /**
   * 检查缓存是否有效
   */
  private isValid(entry: CacheEntry<unknown>): boolean {
    return Date.now() < entry.expiry
  }

  /**
   * 从内存获取
   */
  private getFromMemory<T>(key: string): T | null {
    const entry = this.memoryCache.get(key) as CacheEntry<T> | undefined
    if (entry && this.isValid(entry)) {
      return entry.data
    }
    if (entry) {
      this.memoryCache.delete(key)
    }
    return null
  }

  /**
   * 从 IndexedDB 获取
   */
  private async getFromIndexedDB<T>(key: string): Promise<T | null> {
    await this.initPromise

    if (!this.db) return null

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction('cache', 'readonly')
      const store = transaction.objectStore('cache')
      const request = store.get(key)

      request.onsuccess = () => {
        const entry = request.result as CacheEntry<T> | undefined
        if (entry && this.isValid(entry)) {
          // 提升到内存缓存
          this.memoryCache.set(key, entry)
          resolve(entry.data)
        } else {
          if (entry) {
            // 删除过期缓存
            this.deleteFromIndexedDB(key)
          }
          resolve(null)
        }
      }
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 保存到内存
   */
  private setToMemory<T>(key: string, data: T, ttl: number): void {
    // 检查缓存大小
    if (this.memoryCache.size >= this.config.maxSize) {
      this.evictOldest()
    }

    this.memoryCache.set(key, {
      data,
      timestamp: Date.now(),
      expiry: Date.now() + ttl,
    })
  }

  /**
   * 保存到 IndexedDB
   */
  private async setToIndexedDB<T>(key: string, data: T, ttl: number): Promise<void> {
    await this.initPromise

    if (!this.db) return

    const entry: CacheEntry<T> & { key: string } = {
      key,
      data,
      timestamp: Date.now(),
      expiry: Date.now() + ttl,
    }

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction('cache', 'readwrite')
      const store = transaction.objectStore('cache')
      const request = store.put(entry)

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 删除 IndexedDB 缓存
   */
  private async deleteFromIndexedDB(key: string): Promise<void> {
    await this.initPromise

    if (!this.db) return

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction('cache', 'readwrite')
      const store = transaction.objectStore('cache')
      const request = store.delete(key)

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 驱逐最旧的缓存
   */
  private evictOldest(): void {
    let oldestKey: string | null = null
    let oldestTime = Infinity

    for (const [key, entry] of this.memoryCache) {
      if (entry.timestamp < oldestTime) {
        oldestTime = entry.timestamp
        oldestKey = key
      }
    }

    if (oldestKey) {
      this.memoryCache.delete(oldestKey)
    }
  }

  /**
   * 获取缓存
   */
  async get<T>(url: string, options?: RequestInit): Promise<T | null> {
    const key = this.generateKey(url, options)

    // 先查内存
    const memoryResult = this.getFromMemory<T>(key)
    if (memoryResult !== null) {
      return memoryResult
    }

    // 再查 IndexedDB
    return this.getFromIndexedDB<T>(key)
  }

  /**
   * 设置缓存
   */
  async set<T>(url: string, data: T, ttl?: number, options?: RequestInit): Promise<void> {
    const key = this.generateKey(url, options)
    const actualTtl = ttl || this.config.ttl

    this.setToMemory(key, data, actualTtl)
    await this.setToIndexedDB(key, data, actualTtl)
  }

  /**
   * 带缓存的请求（自动去重）
   */
  async fetch<T>(
    url: string,
    options?: RequestInit,
    config?: { ttl?: number; forceRefresh?: boolean }
  ): Promise<T> {
    const { ttl, forceRefresh = false } = config || {}
    const key = this.generateKey(url, options)

    // 强制刷新或检查缓存
    if (!forceRefresh) {
      const cached = await this.get<T>(url, options)
      if (cached !== null) {
        return cached
      }
    }

    // 检查是否有相同的请求正在进行
    const pending = this.pendingRequests.get(key)
    if (pending) {
      return pending as Promise<T>
    }

    // 发起新请求
    const requestPromise = (async () => {
      try {
        const response = await fetch(url, options)

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }

        const data = await response.json() as T

        // 缓存结果
        await this.set(url, data, ttl, options)

        return data
      } finally {
        this.pendingRequests.delete(key)
      }
    })()

    this.pendingRequests.set(key, requestPromise)
    return requestPromise
  }

  /**
   * 批量请求合并
   */
  async fetchBatch<T>(
    urls: string[],
    options?: RequestInit,
    config?: { ttl?: number; batchSize?: number }
  ): Promise<Map<string, T>> {
    const { ttl, batchSize = 5 } = config || {}
    const results = new Map<string, T>()

    // 分批处理
    for (let i = 0; i < urls.length; i += batchSize) {
      const batch = urls.slice(i, i + batchSize)
      const batchResults = await Promise.all(
        batch.map(url => this.fetch<T>(url, options, { ttl }).then(data => [url, data] as const))
      )

      for (const [url, data] of batchResults) {
        results.set(url, data)
      }
    }

    return results
  }

  /**
   * 清除缓存
   */
  async clear(urlPattern?: RegExp): Promise<void> {
    // 清除内存缓存
    if (urlPattern) {
      for (const key of this.memoryCache.keys()) {
        if (urlPattern.test(key)) {
          this.memoryCache.delete(key)
        }
      }
    } else {
      this.memoryCache.clear()
    }

    // 清除 IndexedDB 缓存
    await this.initPromise
    if (!this.db) return

    return new Promise((resolve, reject) => {
      const transaction = this.db!.transaction('cache', 'readwrite')
      const store = transaction.objectStore('cache')

      if (urlPattern) {
        const request = store.openCursor()
        request.onsuccess = (event) => {
          const cursor = (event.target as IDBRequest<IDBCursorWithValue>).result
          if (cursor) {
            if (urlPattern.test(cursor.value.key)) {
              cursor.delete()
            }
            cursor.continue()
          } else {
            resolve()
          }
        }
        request.onerror = () => reject(request.error)
      } else {
        const request = store.clear()
        request.onsuccess = () => resolve()
        request.onerror = () => reject(request.error)
      }
    })
  }

  /**
   * 获取缓存统计
   */
  getStats(): {
    memorySize: number
    pendingRequests: number
  } {
    return {
      memorySize: this.memoryCache.size,
      pendingRequests: this.pendingRequests.size,
    }
  }
}

// 导出单例
export const requestCache = new RequestCache()

/**
 * 销毁请求缓存单例（清理内存缓存、挂起请求和关闭 IndexedDB）
 */
export function destroyRequestCache(): void {
  // 清理内存缓存
  requestCache['memoryCache'].clear()
  // 清理挂起请求
  requestCache['pendingRequests'].clear()
  // 关闭 IndexedDB 连接
  const db = requestCache['db'] as IDBDatabase | null
  if (db) {
    try { db.close() } catch { /* ignore */ }
    requestCache['db'] = null
  }
  requestCache['initPromise'] = null
}

/**
 * 便捷方法
 */
export const cachedFetch = <T>(url: string, options?: RequestInit, ttl?: number) =>
  requestCache.fetch<T>(url, options, { ttl })

export default requestCache
