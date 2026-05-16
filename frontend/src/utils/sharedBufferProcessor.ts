/**
 * SharedArrayBuffer 多线程数据处理
 * 用于大规模数据并行计算
 */

// 数据类型定义
type DataType = 'float64' | 'int32' | 'uint8'

interface SharedBufferConfig {
  size: number
  type: DataType
}

interface WorkerTask {
  id: string
  type: 'process' | 'aggregate' | 'transform'
  data: SharedArrayBuffer
  config: Record<string, unknown>
  resolve: (result: unknown) => void
  reject: (error: Error) => void
}

/**
 * 共享缓冲区管理器
 */
export class SharedBufferManager {
  private buffers: Map<string, SharedArrayBuffer> = new Map()
  private views: Map<string, Float64Array | Int32Array | Uint8Array> = new Map()

  /**
   * 创建共享缓冲区
   */
  createBuffer(id: string, config: SharedBufferConfig): SharedArrayBuffer {
    const byteLength = this.calculateByteLength(config.size, config.type)
    const buffer = new SharedArrayBuffer(byteLength)

    this.buffers.set(id, buffer)
    this.views.set(id, this.createView(buffer, config.type))

    return buffer
  }

  /**
   * 计算字节长度
   */
  private calculateByteLength(size: number, type: DataType): number {
    const bytesPerElement = {
      float64: 8,
      int32: 4,
      uint8: 1,
    }
    return size * bytesPerElement[type]
  }

  /**
   * 创建视图
   */
  private createView(
    buffer: SharedArrayBuffer,
    type: DataType
  ): Float64Array | Int32Array | Uint8Array {
    switch (type) {
      case 'float64':
        return new Float64Array(buffer)
      case 'int32':
        return new Int32Array(buffer)
      case 'uint8':
        return new Uint8Array(buffer)
    }
  }

  /**
   * 获取缓冲区
   */
  getBuffer(id: string): SharedArrayBuffer | undefined {
    return this.buffers.get(id)
  }

  /**
   * 获取视图
   */
  getView<T extends Float64Array | Int32Array | Uint8Array>(id: string): T | undefined {
    return this.views.get(id) as T | undefined
  }

  /**
   * 写入数据
   */
  writeData(id: string, data: number[], offset = 0): void {
    const view = this.views.get(id) as Float64Array
    if (!view) throw new Error(`Buffer ${id} not found`)

    for (let i = 0; i < data.length; i++) {
      view[offset + i] = data[i]
    }
  }

  /**
   * 读取数据
   */
  readData(id: string, start = 0, length?: number): number[] {
    const view = this.views.get(id) as Float64Array
    if (!view) throw new Error(`Buffer ${id} not found`)

    const end = length ? start + length : view.length
    return Array.from(view.slice(start, end))
  }

  /**
   * 删除缓冲区
   */
  deleteBuffer(id: string): boolean {
    const result = this.buffers.delete(id)
    this.views.delete(id)
    return result
  }

  /**
   * 清空所有缓冲区
   */
  clear(): void {
    this.buffers.clear()
    this.views.clear()
  }

  /**
   * 获取内存使用统计
   */
  getStats(): { bufferCount: number; totalBytes: number } {
    let totalBytes = 0
    for (const buffer of this.buffers.values()) {
      totalBytes += buffer.byteLength
    }
    return {
      bufferCount: this.buffers.size,
      totalBytes,
    }
  }
}

/**
 * 并行计算处理器
 */
export class ParallelProcessor {
  private workers: Worker[] = []
  private taskQueue: WorkerTask[] = []
  private maxWorkers: number
  private activeWorkers: number = 0
  private bufferManager: SharedBufferManager

  constructor(maxWorkers = navigator.hardwareConcurrency || 4) {
    this.maxWorkers = maxWorkers
    this.bufferManager = new SharedBufferManager()
  }

  /**
   * 初始化 Worker 池
   */
  async init(): Promise<void> {
    // 创建 Worker 池
    for (let i = 0; i < this.maxWorkers; i++) {
      const worker = this.createWorker()
      this.workers.push(worker)
    }
  }

  /**
   * 创建 Worker
   */
  private createWorker(): Worker {
    // 内联 Worker 代码
    const workerCode = `
      self.onmessage = function(e) {
        const { id, type, data, config } = e.data

        try {
          let result

          switch (type) {
            case 'process':
              result = processData(data, config)
              break
            case 'aggregate':
              result = aggregateData(data, config)
              break
            case 'transform':
              result = transformData(data, config)
              break
            default:
              throw new Error('Unknown task type: ' + type)
          }

          self.postMessage({ id, success: true, result })
        } catch (error) {
          self.postMessage({ id, success: false, error: error.message })
        }
      }

      function processData(data, config) {
        const { operation, params } = config
        const view = new Float64Array(data)

        switch (operation) {
          case 'normalize':
            return normalize(view)
          case 'smooth':
            return smooth(view, params.window || 5)
          case 'difference':
            return difference(view, params.order || 1)
          default:
            return Array.from(view)
        }
      }

      function normalize(data) {
        let min = Infinity, max = -Infinity
        for (let i = 0; i < data.length; i++) {
          min = Math.min(min, data[i])
          max = Math.max(max, data[i])
        }
        const range = max - min || 1
        const result = new Float64Array(data.length)
        for (let i = 0; i < data.length; i++) {
          result[i] = (data[i] - min) / range
        }
        return Array.from(result)
      }

      function smooth(data, window) {
        const result = new Float64Array(data.length)
        const half = Math.floor(window / 2)
        for (let i = 0; i < data.length; i++) {
          let sum = 0, count = 0
          for (let j = Math.max(0, i - half); j <= Math.min(data.length - 1, i + half); j++) {
            sum += data[j]
            count++
          }
          result[i] = sum / count
        }
        return Array.from(result)
      }

      function difference(data, order) {
        let result = Array.from(data)
        for (let o = 0; o < order; o++) {
          const temp = []
          for (let i = 1; i < result.length; i++) {
            temp.push(result[i] - result[i - 1])
          }
          result = temp
        }
        return result
      }

      function aggregateData(data, config) {
        const { operation } = config
        const view = new Float64Array(data)

        switch (operation) {
          case 'sum':
            return view.reduce((a, b) => a + b, 0)
          case 'mean':
            return view.reduce((a, b) => a + b, 0) / view.length
          case 'min':
            return Math.min(...view)
          case 'max':
            return Math.max(...view)
          case 'std':
            const mean = view.reduce((a, b) => a + b, 0) / view.length
            const variance = view.reduce((sum, v) => sum + (v - mean) ** 2, 0) / view.length
            return Math.sqrt(variance)
          default:
            return null
        }
      }

      function transformData(data, config) {
        const { operation, params } = config
        const view = new Float64Array(data)

        switch (operation) {
          case 'scale':
            return Array.from(view.map(v => v * (params.factor || 1)))
          case 'offset':
            return Array.from(view.map(v => v + (params.value || 0)))
          case 'clip':
            const min = params.min ?? -Infinity
            const max = params.max ?? Infinity
            return Array.from(view.map(v => Math.max(min, Math.min(max, v))))
          case 'log':
            return Array.from(view.map(v => Math.log(v + (params.epsilon || 1))))
          default:
            return Array.from(view)
        }
      }
    `

    const blob = new Blob([workerCode], { type: 'application/javascript' })
    const worker = new Worker(URL.createObjectURL(blob))

    worker.onmessage = (e) => {
      const { id, success, result, error } = e.data
      const task = this.taskQueue.find(t => t.id === id)

      if (task) {
        if (success) {
          task.resolve(result)
        } else {
          task.reject(new Error(error))
        }
        this.taskQueue = this.taskQueue.filter(t => t.id !== id)
        this.activeWorkers--
        this.processQueue()
      }
    }

    return worker
  }

  /**
   * 提交任务
   */
  submitTask(
    data: SharedArrayBuffer,
    type: 'transform' | 'process' | 'aggregate',
    config: Record<string, unknown>
  ): Promise<unknown> {
    return new Promise((resolve, reject) => {
      const task: WorkerTask = {
        id: `task_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
        type,
        data,
        config,
        resolve,
        reject,
      }

      this.taskQueue.push(task)
      this.processQueue()
    })
  }

  /**
   * 处理任务队列
   */
  private processQueue(): void {
    while (this.activeWorkers < this.maxWorkers && this.taskQueue.length > 0) {
      const task = this.taskQueue.shift()!
      const worker = this.workers[this.activeWorkers % this.workers.length]

      worker.postMessage({
        id: task.id,
        type: task.type,
        data: task.data,
        config: task.config,
      })

      this.activeWorkers++
    }
  }

  /**
   * 并行处理数据块
   */
  async parallelProcess(
    data: number[],
    operation: 'normalize' | 'smooth' | 'difference',
    params: Record<string, unknown> = {}
  ): Promise<number[]> {
    // 创建共享缓冲区
    const bufferId = `temp_${Date.now()}`
    const buffer = this.bufferManager.createBuffer(bufferId, {
      size: data.length,
      type: 'float64',
    })

    // 写入数据
    this.bufferManager.writeData(bufferId, data)

    // 提交任务
    const result = await this.submitTask(buffer, 'process', { operation, params })

    // 清理
    this.bufferManager.deleteBuffer(bufferId)

    return result as number[]
  }

  /**
   * 并行聚合
   */
  async parallelAggregate(
    data: number[],
    operation: 'sum' | 'mean' | 'min' | 'max' | 'std'
  ): Promise<number> {
    const bufferId = `agg_${Date.now()}`
    const buffer = this.bufferManager.createBuffer(bufferId, {
      size: data.length,
      type: 'float64',
    })

    this.bufferManager.writeData(bufferId, data)

    const result = await this.submitTask(buffer, 'aggregate', { operation })

    this.bufferManager.deleteBuffer(bufferId)

    return result as number
  }

  /**
   * 批量并行计算
   */
  async batchProcess(
    datasets: number[][],
    operation: 'normalize' | 'smooth' | 'difference',
    params: Record<string, unknown> = {}
  ): Promise<number[][]> {
    const promises = datasets.map(data =>
      this.parallelProcess(data, operation, params)
    )
    return Promise.all(promises)
  }

  /**
   * 分块并行计算（用于超大数据集）
   */
  async chunkedProcess(
    data: number[],
    operation: 'normalize' | 'smooth',
    chunkSize: number = 10000,
    params: Record<string, unknown> = {}
  ): Promise<number[]> {
    const chunks: number[][] = []
    for (let i = 0; i < data.length; i += chunkSize) {
      chunks.push(data.slice(i, i + chunkSize))
    }

    const results = await this.batchProcess(chunks, operation, params)
    return results.flat()
  }

  /**
   * 销毁
   */
  destroy(): void {
    this.workers.forEach(w => w.terminate())
    this.workers = []
    this.taskQueue = []
    this.bufferManager.clear()
  }
}

/**
 * 原子操作计数器（基于 SharedArrayBuffer）
 */
export class AtomicCounter {
  private buffer: SharedArrayBuffer
  private view: Int32Array

  constructor(initialValue = 0) {
    this.buffer = new SharedArrayBuffer(4)
    this.view = new Int32Array(this.buffer)
    this.view[0] = initialValue
  }

  increment(): number {
    return Atomics.add(this.view, 0, 1) + 1
  }

  decrement(): number {
    return Atomics.sub(this.view, 0, 1) - 1
  }

  get(): number {
    return Atomics.load(this.view, 0)
  }

  set(value: number): void {
    Atomics.store(this.view, 0, value)
  }

  compareAndSwap(expected: number, replacement: number): boolean {
    return Atomics.compareExchange(this.view, 0, expected, replacement) === expected
  }
}

/**
 * 并行数据流处理器
 */
export class ParallelStreamProcessor {
  private processor: ParallelProcessor
  private queue: Array<{ data: number[]; callback: (result: number[]) => void }> = []
  private processing = false

  constructor() {
    this.processor = new ParallelProcessor(2)
  }

  async init(): Promise<void> {
    await this.processor.init()
  }

  /**
   * 添加数据到流
   */
  enqueue(data: number[], callback: (result: number[]) => void): void {
    this.queue.push({ data, callback })
    this.process()
  }

  /**
   * 处理队列
   */
  private async process(): Promise<void> {
    if (this.processing || this.queue.length === 0) return

    this.processing = true

    while (this.queue.length > 0) {
      const item = this.queue.shift()!
      try {
        const result = await this.processor.parallelProcess(item.data, 'smooth', { window: 5 })
        item.callback(result)
      } catch (error) {
        console.error('[StreamProcessor] Error:', error)
      }
    }

    this.processing = false
  }

  /**
   * 销毁
   */
  destroy(): void {
    this.processor.destroy()
    this.queue = []
  }
}

// 导出单例
export const sharedBufferManager = new SharedBufferManager()
export const parallelProcessor = new ParallelProcessor()

export default {
  SharedBufferManager,
  ParallelProcessor,
  AtomicCounter,
  ParallelStreamProcessor,
}
