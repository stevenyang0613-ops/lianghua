/**
 * 智能同步策略服务
 * 根据网络状况自动调整同步间隔
 */

interface NetworkStatus {
  isOnline: boolean
  effectiveType: '4g' | '3g' | '2g' | 'slow-2g' | 'unknown'
  downlink: number // Mbps
  rtt: number // ms
}

interface SyncStrategy {
  interval: number // ms
  reason: string
}

const DEFAULT_INTERVAL = 5 * 60 * 1000 // 5分钟
const MIN_INTERVAL = 1 * 60 * 1000 // 1分钟
const MAX_INTERVAL = 30 * 60 * 1000 // 30分钟

let currentInterval = DEFAULT_INTERVAL
const listeners: Set<(strategy: SyncStrategy) => void> = new Set()
let onlineHandler: (() => void) | null = null
let offlineHandler: (() => void) | null = null
let connectionChangeHandler: (() => void) | null = null

// 获取网络状态
function getNetworkStatus(): NetworkStatus {
  const connection = (navigator as any).connection || (navigator as any).mozConnection || (navigator as any).webkitConnection

  return {
    isOnline: navigator.onLine,
    effectiveType: connection?.effectiveType || 'unknown',
    downlink: connection?.downlink || 0,
    rtt: connection?.rtt || 0,
  }
}

// 根据网络状况计算最佳同步间隔
function calculateOptimalInterval(status: NetworkStatus): SyncStrategy {
  if (!status.isOnline) {
    return { interval: MAX_INTERVAL, reason: '离线状态，延长同步间隔' }
  }

  switch (status.effectiveType) {
    case '4g':
      if (status.downlink > 10) {
        return { interval: 1 * 60 * 1000, reason: '高速网络，频繁同步' }
      }
      return { interval: 3 * 60 * 1000, reason: '4G网络，适度同步' }

    case '3g':
      return { interval: 5 * 60 * 1000, reason: '3G网络，标准同步' }

    case '2g':
      return { interval: 10 * 60 * 1000, reason: '2G网络，减少同步' }

    case 'slow-2g':
      return { interval: 20 * 60 * 1000, reason: '慢速网络，延长同步' }

    default:
      return { interval: DEFAULT_INTERVAL, reason: '未知网络，使用默认间隔' }
  }
}

// 根据API响应时间动态调整
function adjustByResponseTime(baseInterval: number, avgResponseTime: number): number {
  if (avgResponseTime < 200) {
    return Math.max(MIN_INTERVAL, baseInterval * 0.8)
  } else if (avgResponseTime > 2000) {
    return Math.min(MAX_INTERVAL, baseInterval * 1.5)
  }
  return baseInterval
}

// 更新同步策略
export function updateSyncStrategy(avgResponseTime?: number): SyncStrategy {
  const networkStatus = getNetworkStatus()
  const strategy = calculateOptimalInterval(networkStatus)

  // 根据响应时间微调
  if (avgResponseTime && avgResponseTime > 0) {
    strategy.interval = adjustByResponseTime(strategy.interval, avgResponseTime)
  }

  // 确保在允许范围内
  strategy.interval = Math.max(MIN_INTERVAL, Math.min(MAX_INTERVAL, strategy.interval))

  // 如果间隔有变化，通知监听器
  if (strategy.interval !== currentInterval) {
    currentInterval = strategy.interval
    listeners.forEach(listener => listener(strategy))
  }

  return strategy
}

// 获取当前同步间隔
export function getCurrentInterval(): number {
  return currentInterval
}

// 订阅策略变化
export function subscribeToStrategyChanges(callback: (strategy: SyncStrategy) => void): () => void {
  listeners.add(callback)
  return () => listeners.delete(callback)
}

// 初始化网络监听
export function initNetworkMonitor(): void {
  // 监听网络状态变化
  onlineHandler = () => {
    console.log('[SmartSync] Network online')
    updateSyncStrategy()
  }
  offlineHandler = () => {
    console.log('[SmartSync] Network offline')
    updateSyncStrategy()
  }

  window.addEventListener('online', onlineHandler)
  window.addEventListener('offline', offlineHandler)

  // 监听网络连接信息变化
  const connection = (navigator as any).connection
  if (connection) {
    connectionChangeHandler = () => {
      console.log('[SmartSync] Connection changed:', connection.effectiveType)
      updateSyncStrategy()
    }
    connection.addEventListener('change', connectionChangeHandler)
  }

  // 初始计算
  updateSyncStrategy()
}

// 清理网络监听
export function cleanupNetworkMonitor(): void {
  if (onlineHandler) {
    window.removeEventListener('online', onlineHandler)
    onlineHandler = null
  }
  if (offlineHandler) {
    window.removeEventListener('offline', offlineHandler)
    offlineHandler = null
  }
  if (connectionChangeHandler) {
    const connection = (navigator as any).connection
    if (connection) {
      connection.removeEventListener('change', connectionChangeHandler)
    }
    connectionChangeHandler = null
  }
}

// 获取网络状态报告
export function getNetworkReport(): {
  status: NetworkStatus
  currentStrategy: SyncStrategy
  recommendedInterval: number
} {
  const status = getNetworkStatus()
  const strategy = calculateOptimalInterval(status)

  return {
    status,
    currentStrategy: {
      interval: currentInterval,
      reason: strategy.reason,
    },
    recommendedInterval: strategy.interval,
  }
}

export default {
  updateSyncStrategy,
  getCurrentInterval,
  subscribeToStrategyChanges,
  initNetworkMonitor,
  cleanupNetworkMonitor,
  getNetworkReport,
}
