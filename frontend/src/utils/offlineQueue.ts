/**
 * 离线操作队列
 * 离线时存储操作，恢复在线后自动同步
 */

interface QueuedOperation {
  id: string
  type: 'create' | 'update' | 'delete' | 'sync'
  entity: string
  data: Record<string, unknown>
  timestamp: number
  retries: number
  lastError?: string
}

type OperationHandler = (operation: QueuedOperation) => Promise<boolean>

class OfflineQueueManager {
  private dbName = 'lianghua-offline-queue'
  private dbVersion = 1
  private db: IDBDatabase | null = null
  private handlers: Map<string, OperationHandler> = new Map()
  private isOnline: boolean = navigator.onLine
  private isProcessing: boolean = false
  private maxRetries: number = 3
  private processingInterval: ReturnType<typeof setInterval> | null = null

  /**
   * 初始化
   */
  async init(): Promise<void> {
    this.db = await this.openDB()

    // 监听网络状态
    window.addEventListener('online', () => {
      this.isOnline = true
      this.processQueue()
    })
    window.addEventListener('offline', () => {
      this.isOnline = false
    })

    // 定期检查队列
    this.processingInterval = setInterval(() => {
      if (this.isOnline && !this.isProcessing) {
        this.processQueue()
      }
    }, 30000) // 每30秒检查一次
  }

  /**
   * 打开数据库
   */
  private openDB(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.dbVersion)

      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve(request.result)

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        if (!db.objectStoreNames.contains('operations')) {
          const store = db.createObjectStore('operations', { keyPath: 'id' })
          store.createIndex('by-entity', 'entity', { unique: false })
          store.createIndex('by-timestamp', 'timestamp', { unique: false })
        }
      }
    })
  }

  /**
   * 注册操作处理器
   */
  registerHandler(entity: string, handler: OperationHandler): void {
    this.handlers.set(entity, handler)
  }

  /**
   * 添加操作到队列
   */
  async enqueue(
    type: QueuedOperation['type'],
    entity: string,
    data: Record<string, unknown>
  ): Promise<string> {
    const operation: QueuedOperation = {
      id: `${entity}_${type}_${Date.now()}_${Math.random().toString(36).slice(2)}`,
      type,
      entity,
      data,
      timestamp: Date.now(),
      retries: 0,
    }

    if (this.db) {
      await this.saveOperation(operation)
    }

    // 如果在线，立即尝试处理
    if (this.isOnline) {
      this.processQueue()
    }

    return operation.id
  }

  /**
   * 保存操作
   */
  private saveOperation(operation: QueuedOperation): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        resolve()
        return
      }

      const transaction = this.db.transaction('operations', 'readwrite')
      const store = transaction.objectStore('operations')
      const request = store.put(operation)

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 批量添加操作
   */
  async enqueueBatch(
    operations: Array<{
      type: QueuedOperation['type']
      entity: string
      data: Record<string, unknown>
    }>
  ): Promise<string[]> {
    const ids: string[] = []

    for (const op of operations) {
      const id = await this.enqueue(op.type, op.entity, op.data)
      ids.push(id)
    }

    return ids
  }

  /**
   * 获取所有操作
   */
  private getAllOperations(): Promise<QueuedOperation[]> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        resolve([])
        return
      }

      const transaction = this.db.transaction('operations', 'readonly')
      const store = transaction.objectStore('operations')
      const index = store.index('by-timestamp')
      const request = index.getAll()

      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 删除操作
   */
  private deleteOperation(id: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        resolve()
        return
      }

      const transaction = this.db.transaction('operations', 'readwrite')
      const store = transaction.objectStore('operations')
      const request = store.delete(id)

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 处理队列
   */
  async processQueue(): Promise<void> {
    if (!this.db || this.isProcessing || !this.isOnline) return

    this.isProcessing = true

    try {
      const operations = await this.getAllOperations()

      for (const operation of operations) {
        const handler = this.handlers.get(operation.entity)

        if (!handler) {
          console.warn(`[OfflineQueue] No handler for entity: ${operation.entity}`)
          continue
        }

        try {
          const success = await handler(operation)

          if (success) {
            await this.deleteOperation(operation.id)
            console.log(`[OfflineQueue] Operation processed: ${operation.id}`)
          } else {
            await this.handleFailure(operation, 'Handler returned false')
          }
        } catch (error) {
          await this.handleFailure(operation, String(error))
        }
      }
    } finally {
      this.isProcessing = false
    }
  }

  /**
   * 处理失败
   */
  private async handleFailure(operation: QueuedOperation, error: string): Promise<void> {
    if (!this.db) return

    operation.retries++
    operation.lastError = error

    if (operation.retries >= this.maxRetries) {
      // 超过最大重试次数，删除操作
      await this.deleteOperation(operation.id)
      console.error(`[OfflineQueue] Operation failed after ${operation.retries} retries:`, operation)

      // 触发失败事件
      window.dispatchEvent(new CustomEvent('offline-queue-failed', {
        detail: { operation, error }
      }))
    } else {
      // 更新重试次数
      await this.saveOperation(operation)
      console.warn(`[OfflineQueue] Operation retry ${operation.retries}/${this.maxRetries}:`, operation.id)
    }
  }

  /**
   * 获取队列状态
   */
  async getStatus(): Promise<{
    pendingCount: number
    entities: Record<string, number>
    oldestTimestamp: number | null
  }> {
    if (!this.db) {
      return { pendingCount: 0, entities: {}, oldestTimestamp: null }
    }

    const operations = await this.getAllOperations()
    const entities: Record<string, number> = {}

    for (const op of operations) {
      entities[op.entity] = (entities[op.entity] || 0) + 1
    }

    return {
      pendingCount: operations.length,
      entities,
      oldestTimestamp: operations.length > 0 ? operations[0].timestamp : null,
    }
  }

  /**
   * 获取所有待处理操作
   */
  async getPendingOperations(): Promise<QueuedOperation[]> {
    return this.getAllOperations()
  }

  /**
   * 删除操作
   */
  async removeOperation(id: string): Promise<void> {
    await this.deleteOperation(id)
  }

  /**
   * 清空队列
   */
  async clearQueue(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.db) {
        resolve()
        return
      }

      const transaction = this.db.transaction('operations', 'readwrite')
      const store = transaction.objectStore('operations')
      const request = store.clear()

      request.onsuccess = () => resolve()
      request.onerror = () => reject(request.error)
    })
  }

  /**
   * 销毁
   */
  destroy(): void {
    if (this.processingInterval) {
      clearInterval(this.processingInterval)
      this.processingInterval = null
    }
  }
}

export function destroyOfflineQueue(): void {
  offlineQueue.destroy()
}

// 导出单例
export const offlineQueue = new OfflineQueueManager()

// 初始化函数
export async function initOfflineQueue(): Promise<void> {
  await offlineQueue.init()

  // 注册默认处理器
  offlineQueue.registerHandler('watchlist', async (op) => {
    // 这里可以调用实际的 API
    console.log('[OfflineQueue] Processing watchlist operation:', op)
    return true
  })

  offlineQueue.registerHandler('settings', async (op) => {
    console.log('[OfflineQueue] Processing settings operation:', op)
    return true
  })

  offlineQueue.registerHandler('alerts', async (op) => {
    console.log('[OfflineQueue] Processing alerts operation:', op)
    return true
  })
}

export default offlineQueue
