/**
 * WebSocket 共享实例
 * 基于 WSReconnect 统一管理 market 和 signals 连接
 * 在 Electron 环境中自动使用 IPC 代理
 *
 * Token 由 StartupLoading 从后端 health 接口获取后缓存到 localStorage，
 * WS 实例在此模块加载时从 localStorage 读取。
 */
import { WSReconnect } from './wsReconnect'
import { getWsBase } from './config'

function getToken(): string {
  if (typeof window !== 'undefined') {
    return localStorage.getItem('ws_auth_token') || ''
  }
  return ''
}

/**
 * 动态获取 WS_BASE，确保端口变化后能获取最新值。
 * 不使用静态常量，因为 setBackendPort 可能在模块加载后调用。
 */
function getWsBaseDynamic(): string {
  return getWsBase()
}

function buildUrl(path: string): string {
  const sep = path.includes('?') ? '&' : '?'
  const token = getToken()
  return `${path}${sep}token=${encodeURIComponent(token)}`
}

/**
 * 创建 WSReconnect 实例并包装 connect() 方法。
 * 每次连接前重新从 localStorage 读取 token，并动态获取最新 WS_BASE，
 * 确保永远使用最新 token 和端口。
 */
function createWsReconnect(basePath: string, wsId: string): WSReconnect {
  const url = buildUrl(`${getWsBaseDynamic()}${basePath}`)
  const ws = new WSReconnect(url, {
    initialDelay: 1000,
    maxDelay: 30000,
    heartbeatInterval: 30000,
  }, wsId)

  const origConnect = ws.connect.bind(ws)
  ws.connect = function(_overrideUrl?: string) {
    const freshUrl = buildUrl(`${getWsBaseDynamic()}${basePath}`)
    return origConnect(freshUrl)
  }

  return ws
}

export const marketWs = createWsReconnect('/api/v1/ws/market', 'market')
export const signalsWs = createWsReconnect('/api/v1/ws/signals', 'signals')

/**
 * Token 更新后重置 WebSocket 连接。
 * 调用 reset 断开旧连接并清除状态，然后立即使用新 URL 重新连接。
 */
export function refreshWsToken(): void {
  const wsBase = getWsBaseDynamic()
  const marketUrl = buildUrl(`${wsBase}/api/v1/ws/market`)
  const signalsUrl = buildUrl(`${wsBase}/api/v1/ws/signals`)
  marketWs.reset(marketUrl)
  signalsWs.reset(signalsUrl)
  // 重新连接
  marketWs.connect()
  signalsWs.connect()
}
