/**
 * 增量更新服务
 * 只更新变化的数据，减少网络传输
 */

export interface DiffResult<T> {
  added: T[]
  removed: T[]
  updated: Array<{ old: T; new: T }>
  unchanged: T[]
}

export interface IncrementalConfig {
  keyField: string
  compareFields: string[]
  maxBatchSize: number
}

/**
 * 计算两个数组之间的差异
 */
export function calculateDiff<T extends Record<string, unknown>>(
  oldData: T[],
  newData: T[],
  config: IncrementalConfig
): DiffResult<T> {
  const { keyField, compareFields } = config

  const oldMap = new Map<unknown, T>()
  const newMap = new Map<unknown, T>()

  oldData.forEach(item => oldMap.set(item[keyField], item))
  newData.forEach(item => newMap.set(item[keyField], item))

  const added: T[] = []
  const removed: T[] = []
  const updated: Array<{ old: T; new: T }> = []
  const unchanged: T[] = []

  // 检查新增和更新
  for (const [key, newItem] of newMap) {
    const oldItem = oldMap.get(key)

    if (!oldItem) {
      added.push(newItem)
    } else {
      // 检查是否有变化
      const hasChanges = compareFields.some(field => oldItem[field] !== newItem[field])

      if (hasChanges) {
        updated.push({ old: oldItem, new: newItem })
      } else {
        unchanged.push(newItem)
      }
    }
  }

  // 检查删除
  for (const [key, oldItem] of oldMap) {
    if (!newMap.has(key)) {
      removed.push(oldItem)
    }
  }

  return { added, removed, updated, unchanged }
}

/**
 * 应用增量更新
 */
export function applyIncrementalUpdate<T extends Record<string, unknown>>(
  currentData: T[],
  diff: DiffResult<T>,
  config: IncrementalConfig
): T[] {
  const { keyField } = config
  const dataMap = new Map<unknown, T>()

  // 添加当前数据
  currentData.forEach(item => dataMap.set(item[keyField], item))

  // 删除已移除的项
  diff.removed.forEach(item => dataMap.delete(item[keyField]))

  // 添加新项
  diff.added.forEach(item => dataMap.set(item[keyField], item))

  // 更新已有项
  diff.updated.forEach(({ new: newItem }) => {
    dataMap.set(newItem[keyField], newItem)
  })

  return Array.from(dataMap.values())
}

/**
 * 增量同步管理器
 */
export class IncrementalSyncManager<T extends Record<string, unknown>> {
  private config: IncrementalConfig
  private lastSyncTime: number = 0
  private pendingUpdates: Array<{ timestamp: number; data: DiffResult<T> }> = []
  private version: number = 0

  constructor(config: IncrementalConfig) {
    this.config = config
  }

  /**
   * 创建增量更新
   */
  createIncremental(oldData: T[], newData: T[]): DiffResult<T> {
    const diff = calculateDiff(oldData, newData, this.config)

    // 记录版本信息
    this.version++
    this.lastSyncTime = Date.now()

    // 保存待处理更新
    this.pendingUpdates.push({
      timestamp: this.lastSyncTime,
      data: diff,
    })

    // 限制历史记录数量
    if (this.pendingUpdates.length > 10) {
      this.pendingUpdates.shift()
    }

    return diff
  }

  /**
   * 获取增量更新摘要
   */
  getSummary(): {
    version: number
    lastSyncTime: number
    pendingCount: number
  } {
    return {
      version: this.version,
      lastSyncTime: this.lastSyncTime,
      pendingCount: this.pendingUpdates.length,
    }
  }

  /**
   * 批量处理更新
   */
  processBatch(currentData: T[], updates: DiffResult<T>[]): T[] {
    let result = [...currentData]

    for (const update of updates) {
      result = applyIncrementalUpdate(result, update, this.config)
    }

    return result
  }

  /**
   * 清理已处理的更新
   */
  clearProcessed(): void {
    this.pendingUpdates = []
  }
}

/**
 * 数据补丁生成
 */
export function createPatch<T extends Record<string, unknown>>(
  oldObj: T,
  newObj: T,
  fields: string[]
): Partial<T> {
  const patch: Record<string, unknown> = {}

  for (const field of fields) {
    if ((oldObj as Record<string, unknown>)[field] !== (newObj as Record<string, unknown>)[field]) {
      patch[field] = (newObj as Record<string, unknown>)[field]
    }
  }

  return patch as Partial<T>
}

/**
 * 应用补丁
 */
export function applyPatch<T extends Record<string, unknown>>(
  obj: T,
  patch: Partial<T>
): T {
  return { ...obj, ...patch }
}

/**
 * 批量补丁操作
 */
export function applyPatches<T extends Record<string, unknown>>(
  data: T[],
  patches: Array<{ key: unknown; patch: Partial<T> }>,
  keyField: string
): T[] {
  const dataMap = new Map<unknown, T>()
  data.forEach(item => dataMap.set(item[keyField], item))

  for (const { key, patch } of patches) {
    const item = dataMap.get(key)
    if (item) {
      dataMap.set(key, { ...item, ...patch })
    }
  }

  return Array.from(dataMap.values())
}

/**
 * 压缩差异（减少传输大小）
 */
export function compressDiff<T extends Record<string, unknown>>(
  diff: DiffResult<T>,
  config: IncrementalConfig
): {
  added: Partial<T>[]
  removed: unknown[]
  updated: Array<{ key: unknown; changes: Partial<T> }>
} {
  const { keyField, compareFields } = config

  return {
    added: diff.added.map(item => {
      const compressed: Record<string, unknown> = {}
      compressed[keyField] = (item as Record<string, unknown>)[keyField]
      compareFields.forEach(f => compressed[f] = (item as Record<string, unknown>)[f])
      return compressed as Partial<T>
    }),
    removed: diff.removed.map(item => item[keyField]),
    updated: diff.updated.map(({ old: oldItem, new: newItem }) => ({
      key: newItem[keyField],
      changes: createPatch(oldItem, newItem, compareFields),
    })),
  }
}

/**
 * 解压差异
 */
export function decompressDiff<T extends Record<string, unknown>>(
  compressed: {
    added: Partial<T>[]
    removed: unknown[]
    updated: Array<{ key: unknown; changes: Partial<T> }>
  },
  currentData: T[],
  config: IncrementalConfig
): DiffResult<T> {
  const { keyField } = config
  const dataMap = new Map<unknown, T>()
  currentData.forEach(item => dataMap.set(item[keyField], item))

  const added = compressed.added as T[]
  const removed = currentData.filter(item => compressed.removed.includes(item[keyField]))
  const updated = compressed.updated.map(({ key, changes }) => {
    const oldItem = dataMap.get(key)!
    return {
      old: oldItem,
      new: { ...oldItem, ...changes } as T,
    }
  })

  const unchangedKeys = new Set([
    ...currentData.map(item => item[keyField]),
    ...added.map(item => item[keyField]),
  ])
  compressed.removed.forEach(k => unchangedKeys.delete(k))

  const unchanged = currentData.filter(
    item => unchangedKeys.has(item[keyField]) && !updated.some(u => u.old[keyField] === item[keyField])
  )

  return { added, removed, updated, unchanged }
}

// 创建默认实例
export const bondSyncManager = new IncrementalSyncManager({
  keyField: 'code',
  compareFields: ['price', 'ytm', 'premium', 'volume', 'amount'],
  maxBatchSize: 100,
})

export default {
  calculateDiff,
  applyIncrementalUpdate,
  IncrementalSyncManager,
  createPatch,
  applyPatch,
  applyPatches,
  compressDiff,
  decompressDiff,
  bondSyncManager,
}
