/**
 * 缓存预热服务
 * 应用启动时后台预热常用API数据
 */

import { fetchAllQuotes, fetchDualLowRanking, fetchForcedRedemption, fetchPulseScan } from '../services/api'

const WARMUP_ENABLED_KEY = 'preload_data'
const WARMUP_STATUS_KEY = 'warmup_status'

interface WarmupStatus {
  lastWarmup: string | null
  duration: number
  successCount: number
  errorCount: number
  errors: string[]
}

// 预热任务列表
const warmupTasks: { name: string; fn: () => Promise<unknown> }[] = [
  { name: 'market_quotes', fn: fetchAllQuotes },
  { name: 'dual_low', fn: fetchDualLowRanking },
  { name: 'forced_redemption', fn: fetchForcedRedemption },
  { name: 'pulse_scan', fn: fetchPulseScan },
]

function loadStatus(): WarmupStatus {
  const saved = localStorage.getItem(WARMUP_STATUS_KEY)
  if (saved) {
    return JSON.parse(saved)
  }
  return { lastWarmup: null, duration: 0, successCount: 0, errorCount: 0, errors: [] }
}

function saveStatus(status: WarmupStatus): void {
  localStorage.setItem(WARMUP_STATUS_KEY, JSON.stringify(status))
}

export function isEnabled(): boolean {
  return localStorage.getItem(WARMUP_ENABLED_KEY) === 'true'
}

export function getStatus(): WarmupStatus {
  return loadStatus()
}

// 执行缓存预热
export async function runWarmup(): Promise<WarmupStatus> {
  if (!isEnabled()) {
    console.log('[Warmup] Preload disabled, skipping')
    return loadStatus()
  }

  // 检查离线模式
  if (localStorage.getItem('offline_mode') === 'true') {
    console.log('[Warmup] Offline mode, skipping')
    return loadStatus()
  }

  console.log('[Warmup] Starting cache warmup...')
  const startTime = Date.now()

  const status: WarmupStatus = {
    lastWarmup: new Date().toLocaleString('zh-CN'),
    duration: 0,
    successCount: 0,
    errorCount: 0,
    errors: [],
  }

  // 并行执行预热任务
  const results = await Promise.allSettled(
    warmupTasks.map(async (task) => {
      await task.fn()
      return task.name
    })
  )

  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      status.successCount++
      console.log(`[Warmup] ✅ ${warmupTasks[index].name}`)
    } else {
      status.errorCount++
      const error = `${warmupTasks[index].name}: ${result.reason}`
      status.errors.push(error)
      console.error(`[Warmup] ❌ ${error}`)
    }
  })

  status.duration = Date.now() - startTime
  saveStatus(status)

  console.log(`[Warmup] Complete: ${status.successCount}/${warmupTasks.length} in ${status.duration}ms`)
  return status
}

// 检查是否需要预热
export function shouldWarmup(): boolean {
  if (!isEnabled()) return false

  const status = loadStatus()
  if (!status.lastWarmup) return true

  // 距离上次预热超过1小时，重新预热
  const lastWarmupTime = new Date(status.lastWarmup).getTime()
  const oneHourAgo = Date.now() - 60 * 60 * 1000

  return lastWarmupTime < oneHourAgo
}

// 初始化预热
export function initWarmup(): void {
  if (shouldWarmup()) {
    // 延迟执行，不阻塞启动
    setTimeout(() => {
      runWarmup().catch(err => console.error('[Warmup] Failed:', err))
    }, 2000)
  }
}

export default {
  isEnabled,
  getStatus,
  runWarmup,
  shouldWarmup,
  initWarmup,
}
