/**
 * WebSocket 共享实例
 * 基于 WSReconnect 统一管理 market 和 signals 连接
 * 在 Electron 环境中自动使用 IPC 代理
 *
 * Token 由 StartupLoading 从后端 health 接口获取后缓存到 localStorage，
 * WS 实例在此模块加载时从 localStorage 读取。
 *
 * 心跳策略：交易时间(9:00-15:30) 30s，非交易时间 120s
 */
import { WSReconnect } from './wsReconnect'
import { getWsBase, getHttpBase } from './config'

const STALE_KEY = 'ws_stale_threshold_sec'
const DEFAULT_STALE_MS = 60000

/**
 * 从 localStorage 获取 WS 认证 token。
 * 如果为空，尝试从后端 health 接口异步获取（降级机制）。
 */
function getToken(): string {
  try {
    if (typeof window !== 'undefined') {
      const cached = localStorage.getItem('ws_auth_token')
      if (cached) return cached
    }
  } catch { /* localStorage unavailable (private mode, sandbox, etc.) */ }
  return ''
}

/**
 * 通过后端 health 接口获取 token 并缓存到 localStorage。
 * 空 token 时作为降级机制调用，避免发送无效请求。
 */
async function fetchTokenFromHealth(): Promise<string> {
  try {
    if (typeof window === 'undefined') return ''
    const base = getHttpBase()
    const resp = await fetch(`${base}/health`, { signal: AbortSignal.timeout(5000) })
    if (resp.ok) {
      const data = await resp.json()
      const token = data?.ws_auth_token
      if (typeof token === 'string' && token) {
        localStorage.setItem('ws_auth_token', token)
        return token
      }
    }
  } catch (e) {
    console.warn('[WS] fetchTokenFromHealth failed:', e)
  }
  return ''
}

function getStaleThresholdMs(): number {
  try {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem(STALE_KEY)
      if (saved) {
        const parsed = parseInt(saved, 10)
        return Number.isFinite(parsed) && parsed > 0 ? parsed * 1000 : DEFAULT_STALE_MS
      }
    }
  } catch { /* localStorage unavailable */ }
  return DEFAULT_STALE_MS
}

// 交易时间判断：周一至周五 9:00-15:30 使用短心跳
function getHeartbeatInterval(): number {
  const now = new Date()
  const day = now.getDay()
  const hours = now.getHours()
  const minutes = now.getMinutes()
  const isWeekday = day >= 1 && day <= 5
  const timeValue = hours * 60 + minutes
  const isTradingHours = timeValue >= 9 * 60 && timeValue <= 15 * 60 + 30
  return (isWeekday && isTradingHours) ? 30000 : 120000
}

const WS_BASE = getWsBase()

/**
 * 构建 WebSocket URL。
 * 如果 token 为空，直接返回 path；
 * 如果 URL 中已有 token 参数，不再重复添加（避免 refreshWsToken 后重复 ?token=）。
 */
function buildUrl(path: string): string {
  const token = getToken()
  if (!token) return path
  // 防御：URL 已含 token 时不再追加
  if (path.includes('token=')) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}token=${encodeURIComponent(token)}`
}

/**
 * 创建 WSReconnect 实例。
 * 初始 URL 通过 buildUrl 构建，token 更新由 refreshWsToken 统一调用 reset+connect 处理。
 * connect 与 url 设置逻辑统一在 WSReconnect 类内部（单一定义）。
 */
function createWsReconnect(basePath: string, wsId: string): WSReconnect {
  const url = buildUrl(`${WS_BASE}${basePath}`)
  return new WSReconnect(url, {
    initialDelay: 1000,
    maxDelay: 30000,
    heartbeatInterval: getHeartbeatInterval(),
    staleThresholdMs: getStaleThresholdMs(),
  }, wsId)
}

export const marketWs = createWsReconnect('/api/v1/ws/market', 'market')
export const signalsWs = createWsReconnect('/api/v1/ws/signals', 'signals')

let _lastToken = ''
let _refreshing = false
let _refreshTimer: ReturnType<typeof setTimeout> | null = null

/**
 * 取消待执行的 refreshWsToken 定时器。
 * 在应用卸载或页面刷新前调用，避免孤儿 timer。
 */
export function cancelRefreshWsToken(): void {
  if (_refreshTimer) {
    clearTimeout(_refreshTimer)
    _refreshTimer = null
  }
}

/**
 * 销毁所有 WebSocket 实例和定时器。
 * 在应用卸载时调用，避免内存泄漏。
 */
export function destroyWsInstances(): void {
  try {
    marketWs.dispose()
  } catch { /* noop */ }
  try {
    signalsWs.dispose()
  } catch { /* noop */ }
  cancelRefreshWsToken()
}

/**
 * Token 更新后重置 WebSocket 连接。
 * 串行化 reset+connect：先断开 market，重连 market 成功后再断开/重连 signals，
 * 避免两个连接同时断开导致大量并发重连请求。
 * 使用 _refreshing 互斥锁防止并发调用导致双连接。
 */
export function refreshWsToken(): void {
  if (_refreshing) return
  _refreshing = true

  // 清理旧的待执行 timer，防止重叠
  cancelRefreshWsToken()

  try {
    const newToken = getToken()
    if (newToken === _lastToken && marketWs.isConnected()) {
      _refreshing = false
      return
    }
    _lastToken = newToken
    const marketUrl = buildUrl(`${WS_BASE}/api/v1/ws/market`)
    const signalsUrl = buildUrl(`${WS_BASE}/api/v1/ws/signals`)

    // 串行化：先 reset+connect market，等稳定后再处理 signals
    marketWs.reset(marketUrl)
    marketWs.connect()

    // 延迟 500ms 再 reset signals，避免两个 WS 同时断开/重连的冲击
    _refreshTimer = setTimeout(() => {
      try {
        signalsWs.reset(signalsUrl)
        signalsWs.connect()
      } finally {
        _refreshing = false
        _refreshTimer = null
      }
    }, 500)
  } catch {
    _refreshing = false
  }
}
