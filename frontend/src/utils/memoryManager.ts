/**
 * 内存管理服务
 * 大数据集分片加载，避免内存溢出
 */

export interface ChunkConfig {
  chunkSize: number
  maxChunks: number
  evictionPolicy: 'lru' | 'fifo' | 'none'
}

const defaultConfig: ChunkConfig = {
  chunkSize: 1000,
  maxChunks: 10,
  evictionPolicy: 'lru',
}

/**
 * 分片数据管理器
 */
export class ChunkedDataManager<T> {
  private config: ChunkConfig
  private chunks: Map<number, T[]> = new Map()
  private accessOrder: number[] = []
  private totalCount: number = 0
  private chunkCount: number = 0

  constructor(config: Partial<ChunkConfig> = {}) {
    this.config = { ...defaultConfig, ...config }
  }

  /**
   * 加载数据（分片）
   */
  loadAll(data: T[]): void {
    this.clear()
    this.totalCount = data.length
    this.chunkCount = Math.ceil(data.length / this.config.chunkSize)

    // 只加载前几个分片
    const initialChunks = Math.min(3, this.chunkCount)
    for (let i = 0; i < initialChunks; i++) {
      const start = i * this.config.chunkSize
      const end = Math.min(start + this.config.chunkSize, data.length)
      this.chunks.set(i, data.slice(start, end))
      this.updateAccessOrder(i)
    }
  }

  /**
   * 获取分片
   */
  getChunk(index: number): T[] | null {
    if (index < 0 || index >= this.chunkCount) return null

    const chunk = this.chunks.get(index)
    if (chunk) {
      this.updateAccessOrder(index)
      return chunk
    }

    // 分片未加载，返回空数组或触发加载
    return null
  }

  /**
   * 加载指定分片
   */
  loadChunk(index: number, data: T[]): void {
    if (index < 0 || index >= this.chunkCount) return

    const start = index * this.config.chunkSize
    const end = Math.min(start + this.config.chunkSize, data.length)

    // 检查是否需要驱逐
    this.evictIfNeeded()

    this.chunks.set(index, data.slice(start, end))
    this.updateAccessOrder(index)
  }

  /**
   * 获取指定索引的数据
   */
  get(index: number): T | null {
    const chunkIndex = Math.floor(index / this.config.chunkSize)
    const chunk = this.getChunk(chunkIndex)

    if (!chunk) return null

    const localIndex = index % this.config.chunkSize
    return chunk[localIndex] || null
  }

  /**
   * 获取已加载的数据范围
   */
  getLoadedRanges(): Array<{ start: number; end: number }> {
    const ranges: Array<{ start: number; end: number }> = []

    for (const [index] of this.chunks) {
      ranges.push({
        start: index * this.config.chunkSize,
        end: Math.min((index + 1) * this.config.chunkSize, this.totalCount),
      })
    }

    return ranges.sort((a, b) => a.start - b.start)
  }

  /**
   * 预加载分片
   */
  preloadChunks(indices: number[], data: T[]): void {
    indices.forEach(index => {
      if (!this.chunks.has(index)) {
        this.loadChunk(index, data)
      }
    })
  }

  /**
   * 更新访问顺序
   */
  private updateAccessOrder(index: number): void {
    const existingIndex = this.accessOrder.indexOf(index)
    if (existingIndex > -1) {
      this.accessOrder.splice(existingIndex, 1)
    }
    this.accessOrder.push(index)
  }

  /**
   * 驱逐分片
   */
  private evictIfNeeded(): void {
    if (this.chunks.size >= this.config.maxChunks && this.config.evictionPolicy !== 'none') {
      let toEvict: number

      switch (this.config.evictionPolicy) {
        case 'lru':
          toEvict = this.accessOrder.shift()!
          break
        case 'fifo':
          toEvict = this.chunks.keys().next().value as number
          break
        default:
          return
      }

      this.chunks.delete(toEvict)
    }
  }

  /**
   * 清除所有数据
   */
  clear(): void {
    this.chunks.clear()
    this.accessOrder = []
    this.totalCount = 0
    this.chunkCount = 0
  }

  /**
   * 获取统计信息
   */
  getStats(): {
    totalItems: number
    chunkCount: number
    loadedChunks: number
    loadedItems: number
    memoryEstimate: number
  } {
    let loadedItems = 0
    for (const chunk of this.chunks.values()) {
      loadedItems += chunk.length
    }

    return {
      totalItems: this.totalCount,
      chunkCount: this.chunkCount,
      loadedChunks: this.chunks.size,
      loadedItems,
      memoryEstimate: loadedItems * 100, // 粗略估算，每项约 100 字节
    }
  }
}

/**
 * 对象池 - 复用对象，减少 GC 压力
 */
export class ObjectPool<T> {
  private factory: () => T
  private reset: (obj: T) => void
  private pool: T[] = []
  private maxSize: number

  constructor(factory: () => T, reset: (obj: T) => void, maxSize = 100) {
    this.factory = factory
    this.reset = reset
    this.maxSize = maxSize
  }

  acquire(): T {
    if (this.pool.length > 0) {
      return this.pool.pop()!
    }
    return this.factory()
  }

  release(obj: T): void {
    if (this.pool.length < this.maxSize) {
      this.reset(obj)
      this.pool.push(obj)
    }
  }

  clear(): void {
    this.pool = []
  }

  get size(): number {
    return this.pool.length
  }
}

/**
 * 内存监控
 */
export class MemoryMonitor {
  private samples: Array<{ timestamp: number; used: number; total: number }> = []
  private maxSamples = 100

  /**
   * 记录内存快照
   */
  record(): { used: number; total: number } | null {
    if ('memory' in performance && performance.memory) {
      const memory = performance.memory
      const sample = {
        timestamp: Date.now(),
        used: memory.usedJSHeapSize,
        total: memory.totalJSHeapSize,
      }

      this.samples.push(sample)

      if (this.samples.length > this.maxSamples) {
        this.samples.shift()
      }

      return { used: sample.used, total: sample.total }
    }

    return null
  }

  /**
   * 获取内存使用趋势
   */
  getTrend(): {
    current: { used: number; total: number } | null
    average: number
    peak: number
    trend: 'increasing' | 'decreasing' | 'stable'
  } {
    if (this.samples.length === 0) {
      return { current: null, average: 0, peak: 0, trend: 'stable' }
    }

    const current = this.samples[this.samples.length - 1]
    const values = this.samples.map(s => s.used)
    const average = values.reduce((a, b) => a + b, 0) / values.length
    const peak = Math.max(...values)

    // 计算趋势
    const recentSamples = this.samples.slice(-10)
    const oldAvg = recentSamples.slice(0, 5).reduce((a, s) => a + s.used, 0) / 5
    const newAvg = recentSamples.slice(-5).reduce((a, s) => a + s.used, 0) / 5

    const changeRatio = (newAvg - oldAvg) / oldAvg
    let trend: 'increasing' | 'decreasing' | 'stable' = 'stable'
    if (changeRatio > 0.1) trend = 'increasing'
    else if (changeRatio < -0.1) trend = 'decreasing'

    return {
      current: { used: current.used, total: current.total },
      average,
      peak,
      trend,
    }
  }

  /**
   * 检查内存压力
   */
  getPressure(): 'low' | 'medium' | 'high' {
    const trend = this.getTrend()

    if (!trend.current) return 'low'

    const usedMB = trend.current.used / (1024 * 1024)
    const totalMB = trend.current.total / (1024 * 1024)
    const usageRatio = usedMB / totalMB

    if (usageRatio > 0.9 || (trend.trend === 'increasing' && usedMB > 500)) {
      return 'high'
    } else if (usageRatio > 0.7 || usedMB > 300) {
      return 'medium'
    }

    return 'low'
  }

  /**
   * 清除历史记录
   */
  clear(): void {
    this.samples = []
  }
}

/**
 * 懒加载数据源
 */
export class LazyDataSource<T> {
  private fetcher: (offset: number, limit: number) => Promise<T[]>
  private chunkSize: number
  private cache: Map<number, T[]> = new Map()
  private loading: Set<number> = new Set()
  private totalOffset: number | null = null

  constructor(
    fetcher: (offset: number, limit: number) => Promise<T[]>,
    chunkSize = 100
  ) {
    this.fetcher = fetcher
    this.chunkSize = chunkSize
  }

  /**
   * 获取指定范围的数据
   */
  async getRange(start: number, end: number): Promise<T[]> {
    const startChunk = Math.floor(start / this.chunkSize)
    const endChunk = Math.floor(end / this.chunkSize)

    // 触发加载
    const loadPromises: Promise<void>[] = []
    for (let i = startChunk; i <= endChunk; i++) {
      if (!this.cache.has(i) && !this.loading.has(i)) {
        loadPromises.push(this.loadChunk(i))
      }
    }

    await Promise.all(loadPromises)

    // 组装结果
    const result: T[] = []
    for (let i = start; i < end; i++) {
      const chunkIndex = Math.floor(i / this.chunkSize)
      const chunk = this.cache.get(chunkIndex)
      if (chunk) {
        const localIndex = i % this.chunkSize
        result.push(chunk[localIndex])
      }
    }

    return result
  }

  /**
   * 加载分片
   */
  private async loadChunk(index: number): Promise<void> {
    if (this.loading.has(index)) return

    this.loading.add(index)

    try {
      const offset = index * this.chunkSize
      const data = await this.fetcher(offset, this.chunkSize)
      this.cache.set(index, data)

      if (data.length < this.chunkSize) {
        this.totalOffset = offset + data.length
      }
    } finally {
      this.loading.delete(index)
    }
  }

  /**
   * 预加载
   */
  async prefetch(indices: number[]): Promise<void> {
    await Promise.all(indices.map(i => this.loadChunk(i)))
  }

  /**
   * 清除缓存
   */
  clearCache(): void {
    this.cache.clear()
    this.totalOffset = null
  }

  get loadedOffset(): number | null {
    return this.totalOffset
  }
}

// 默认实例
export const memoryMonitor = new MemoryMonitor()
export const chunkedDataManager = new ChunkedDataManager()

export default {
  ChunkedDataManager,
  ObjectPool,
  MemoryMonitor,
  LazyDataSource,
  memoryMonitor,
  chunkedDataManager,
}
