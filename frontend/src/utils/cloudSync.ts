/**
 * 多设备同步服务
 * 通过云端同步用户设置和自选股
 */

interface SyncData {
  settings: Record<string, unknown>
  watchlist: string[]
  shortcuts: Record<string, string>
  lastSyncTime: number
  deviceId: string
}

export interface SyncResult {
  success: boolean
  message: string
  data?: SyncData
  conflicts?: string[]
}

const DEVICE_ID_KEY = 'device_id'
const LAST_SYNC_KEY = 'last_sync_time'

// 获取设备ID
function getDeviceId(): string {
  let deviceId = localStorage.getItem(DEVICE_ID_KEY)
  if (!deviceId) {
    deviceId = `device_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
    localStorage.setItem(DEVICE_ID_KEY, deviceId)
  }
  return deviceId
}

// 获取本地数据
function getLocalData(): SyncData {
  const settings: Record<string, unknown> = {}
  const settingKeys = ['theme', 'signal_min_confidence', 'signal_max_signals', 'auto_sync', 'offline_mode', 'preload_data']

  settingKeys.forEach(key => {
    const value = localStorage.getItem(key)
    if (value !== null) {
      try {
        settings[key] = JSON.parse(value)
      } catch {
        settings[key] = value
      }
    }
  })

  // 自选股
  const watchlistStr = localStorage.getItem('watchlist')
  const watchlist = watchlistStr ? JSON.parse(watchlistStr) : []

  // 快捷键
  const shortcutsStr = localStorage.getItem('shortcuts')
  const shortcuts = shortcutsStr ? JSON.parse(shortcutsStr) : {}

  return {
    settings,
    watchlist,
    shortcuts,
    lastSyncTime: Date.now(),
    deviceId: getDeviceId(),
  }
}

// 应用远程数据
function applyRemoteData(data: SyncData): string[] {
  const conflicts: string[] = []

  // 应用设置
  for (const [key, value] of Object.entries(data.settings)) {
    const localValue = localStorage.getItem(key)
    const remoteValue = JSON.stringify(value)

    if (localValue !== null && localValue !== remoteValue) {
      conflicts.push(key)
    }

    localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value))
  }

  // 应用自选股
  localStorage.setItem('watchlist', JSON.stringify(data.watchlist))

  // 应用快捷键
  localStorage.setItem('shortcuts', JSON.stringify(data.shortcuts))

  localStorage.setItem(LAST_SYNC_KEY, String(Date.now()))

  return conflicts
}

// 模拟云端存储（实际应用中替换为真实API）
const cloudStorage = {
  data: null as SyncData | null,

  async upload(data: SyncData): Promise<void> {
    // 模拟网络延迟
    await new Promise(resolve => setTimeout(resolve, 500))
    this.data = data
  },

  async download(): Promise<SyncData | null> {
    await new Promise(resolve => setTimeout(resolve, 300))
    return this.data
  },
}

// 上传到云端
export async function uploadToCloud(): Promise<SyncResult> {
  try {
    const data = getLocalData()
    await cloudStorage.upload(data)

    localStorage.setItem(LAST_SYNC_KEY, String(Date.now()))

    return {
      success: true,
      message: '数据已上传到云端',
      data,
    }
  } catch (error) {
    return {
      success: false,
      message: `上传失败: ${String(error)}`,
    }
  }
}

// 从云端下载
export async function downloadFromCloud(): Promise<SyncResult> {
  try {
    const remoteData = await cloudStorage.download()

    if (!remoteData) {
      return {
        success: false,
        message: '云端暂无数据',
      }
    }

    const conflicts = applyRemoteData(remoteData)

    return {
      success: true,
      message: conflicts.length > 0 ? `数据已同步，有 ${conflicts.length} 个冲突已自动解决` : '数据已同步',
      data: remoteData,
      conflicts,
    }
  } catch (error) {
    return {
      success: false,
      message: `下载失败: ${String(error)}`,
    }
  }
}

// 完整同步
export async function fullSync(): Promise<SyncResult> {
  try {
    // 先上传本地数据
    const localData = getLocalData()
    await cloudStorage.upload(localData)

    // 再下载云端数据
    const remoteData = await cloudStorage.download()

    if (remoteData) {
      // 合并数据
      const conflicts = applyRemoteData(remoteData)
      return {
        success: true,
        message: conflicts.length > 0 ? `同步完成，解决 ${conflicts.length} 个冲突` : '同步完成',
        conflicts,
      }
    }

    return {
      success: true,
      message: '数据已上传，云端暂无数据',
      data: localData,
    }
  } catch (error) {
    return {
      success: false,
      message: `同步失败: ${String(error)}`,
    }
  }
}

// 获取同步状态
export function getSyncStatus(): {
  lastSyncTime: string | null
  deviceId: string
  hasLocalChanges: boolean
} {
  const lastSync = localStorage.getItem(LAST_SYNC_KEY)
  const lastSyncTime = lastSync ? new Date(parseInt(lastSync)).toLocaleString('zh-CN') : null

  // 简单检测是否有未同步的更改
  const localData = getLocalData()
  const hasLocalChanges = localData.lastSyncTime > (lastSync ? parseInt(lastSync) : 0)

  return {
    lastSyncTime,
    deviceId: getDeviceId(),
    hasLocalChanges,
  }
}

// 导出数据为文件
export function exportData(): void {
  const data = getLocalData()
  const json = JSON.stringify(data, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = `lianghua-backup-${new Date().toISOString().slice(0, 10)}.json`
  a.click()

  URL.revokeObjectURL(url)
}

// 从文件导入数据
export async function importData(file: File): Promise<SyncResult> {
  return new Promise((resolve) => {
    const reader = new FileReader()

    reader.onload = (e) => {
      try {
        const data = JSON.parse(e.target?.result as string) as SyncData

        if (!data.settings || !data.deviceId) {
          resolve({ success: false, message: '无效的备份文件' })
          return
        }

        const conflicts = applyRemoteData(data)
        resolve({
          success: true,
          message: `导入成功，解决了 ${conflicts.length} 个冲突`,
          conflicts,
        })
      } catch (error) {
        resolve({ success: false, message: `导入失败: ${String(error)}` })
      }
    }

    reader.onerror = () => {
      resolve({ success: false, message: '文件读取失败' })
    }

    reader.readAsText(file)
  })
}

export default {
  uploadToCloud,
  downloadFromCloud,
  fullSync,
  getSyncStatus,
  exportData,
  importData,
}
