/**
 * 数据同步冲突解决服务
 * 处理离线编辑与在线数据的合并
 */

import { safeJsonParse } from './safeJson'

interface ConflictItem<T> {
  key: string
  local: T
  remote: T
  localTimestamp: number
  remoteTimestamp: number
  type: 'update' | 'delete' | 'create'
}

interface ConflictResolution<T> {
  strategy: 'local' | 'remote' | 'merge' | 'manual'
  result: T
  conflicts: string[]
}

// 检测冲突
export function detectConflict<T>(
  key: string,
  local: T | null,
  remote: T | null,
  localTimestamp: number,
  remoteTimestamp: number
): ConflictItem<T> | null {
  // 两边都没变化
  if (!local && !remote) return null

  // 只有本地变化
  if (local && !remote) {
    return { key, local, remote: null as T, localTimestamp, remoteTimestamp, type: 'create' }
  }

  // 只有远程变化
  if (!local && remote) {
    return { key, local: null as T, remote, localTimestamp, remoteTimestamp, type: 'create' }
  }

  // 两边都有变化，检查时间戳
  if (localTimestamp !== remoteTimestamp) {
    return { key, local: local as T, remote: remote as T, localTimestamp, remoteTimestamp, type: 'update' }
  }

  return null
}

// 自动解决策略
export function autoResolve<T>(conflict: ConflictItem<T>): ConflictResolution<T> {
  const conflicts: string[] = []

  // 策略1: 最新优先
  if (conflict.localTimestamp > conflict.remoteTimestamp) {
    return { strategy: 'local', result: conflict.local, conflicts }
  }

  if (conflict.remoteTimestamp > conflict.localTimestamp) {
    return { strategy: 'remote', result: conflict.remote, conflicts }
  }

  // 时间戳相同，尝试合并
  if (conflict.type === 'update') {
    const merged = deepMerge(conflict.local, conflict.remote)
    conflicts.push('时间戳相同，已自动合并')
    return { strategy: 'merge', result: merged, conflicts }
  }

  // 默认使用远程数据
  return { strategy: 'remote', result: conflict.remote, conflicts }
}

// 深度合并对象
function deepMerge<T>(local: T, remote: T): T {
  if (typeof local !== 'object' || local === null) return remote
  if (typeof remote !== 'object' || remote === null) return local

  const result = { ...remote } as T

  for (const key of Object.keys(local as object)) {
    const localValue = (local as any)[key]
    const remoteValue = (remote as any)[key]

    if (localValue !== undefined && remoteValue === undefined) {
      (result as any)[key] = localValue
    } else if (typeof localValue === 'object' && typeof remoteValue === 'object') {
      (result as any)[key] = deepMerge(localValue, remoteValue)
    }
  }

  return result
}

// 批量解决冲突
export function resolveConflicts<T>(
  conflicts: ConflictItem<T>[],
  strategy: 'auto' | 'local' | 'remote' = 'auto'
): Map<string, ConflictResolution<T>> {
  const results = new Map<string, ConflictResolution<T>>()

  for (const conflict of conflicts) {
    if (strategy === 'auto') {
      results.set(conflict.key, autoResolve(conflict))
    } else if (strategy === 'local') {
      results.set(conflict.key, {
        strategy: 'local',
        result: conflict.local,
        conflicts: [],
      })
    } else {
      results.set(conflict.key, {
        strategy: 'remote',
        result: conflict.remote,
        conflicts: [],
      })
    }
  }

  return results
}

// 同步队列管理
interface SyncQueueItem {
  key: string
  data: unknown
  timestamp: number
  operation: 'create' | 'update' | 'delete'
}

const SYNC_QUEUE_KEY = 'sync_queue'

export function addToSyncQueue(key: string, data: unknown, operation: 'create' | 'update' | 'delete'): void {
  const queue = getSyncQueue()
  const existingIndex = queue.findIndex(item => item.key === key)

  const newItem: SyncQueueItem = {
    key,
    data,
    timestamp: Date.now(),
    operation,
  }

  if (existingIndex >= 0) {
    queue[existingIndex] = newItem
  } else {
    queue.push(newItem)
  }

  localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(queue))
}

export function getSyncQueue(): SyncQueueItem[] {
  const saved = localStorage.getItem(SYNC_QUEUE_KEY)
  return savedJsonParse<SyncQueueItem[]>(saved, [])
}

export function clearSyncQueue(): void {
  localStorage.removeItem(SYNC_QUEUE_KEY)
}

export function removeSyncQueueItem(key: string): void {
  const queue = getSyncQueue().filter(item => item.key !== key)
  localStorage.setItem(SYNC_QUEUE_KEY, JSON.stringify(queue))
}

// 执行同步队列
export async function processSyncQueue(
  syncFn: (item: SyncQueueItem) => Promise<boolean>
): Promise<{ success: number; failed: number; errors: string[] }> {
  const queue = getSyncQueue()
  const result = { success: 0, failed: 0, errors: [] as string[] }

  for (const item of queue) {
    try {
      const success = await syncFn(item)
      if (success) {
        removeSyncQueueItem(item.key)
        result.success++
      } else {
        result.failed++
        result.errors.push(`${item.key}: 同步失败`)
      }
    } catch (err) {
      result.failed++
      result.errors.push(`${item.key}: ${String(err)}`)
    }
  }

  return result
}

// 冲突日志
export function logConflict(conflict: ConflictItem<unknown>, resolution: ConflictResolution<unknown>): void {
  const logKey = 'conflict_log'
  const log = safeJsonParse<unknown[]>(localStorage.getItem(logKey), [])

  log.push({
    timestamp: Date.now(),
    conflict,
    resolution,
  })

  // 只保留最近100条
  localStorage.setItem(logKey, JSON.stringify(log.slice(-100)))
}

export default {
  detectConflict,
  autoResolve,
  resolveConflicts,
  addToSyncQueue,
  getSyncQueue,
  clearSyncQueue,
  removeSyncQueueItem,
  processSyncQueue,
  logConflict,
}
