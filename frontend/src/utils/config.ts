/**
 * 应用环境配置
 * 统一管理开发/生产环境下的 API 地址
 */

// 后端服务配置
const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8765
let _actualPort = BACKEND_PORT

export function setBackendPort(port: number): void {
  _actualPort = port
}

export function getActualPort(): number {
  return _actualPort
}

export const ENV = {
  BACKEND_HOST,
  BACKEND_PORT,
  get BACKEND_URL(): string {
    return `http://${BACKEND_HOST}:${_actualPort}`
  },
  get WS_URL(): string {
    return `ws://${BACKEND_HOST}:${_actualPort}`
  },
  // WS_AUTH_TOKEN 由后端动态生成，前端通过 localStorage 缓存
  get WS_AUTH_TOKEN(): string {
    if (typeof window !== 'undefined') {
      const cached = localStorage.getItem('ws_auth_token')
      if (cached) return cached
    }
    return ''
  },
}

/**
 * 设置 WebSocket 认证 token（由 StartupLoading 从后端获取后调用）
 */
export function setWsAuthToken(token: string): void {
  if (typeof window !== 'undefined' && token) {
    localStorage.setItem('ws_auth_token', token)
  }
}

/**
 * 检测是否在 Electron 环境中（有 IPC 代理可用）
 * 只检查 httpRequest 是否存在，不依赖 isElectron 标志
 */
function hasElectronAPI(): boolean {
  return typeof window !== 'undefined' && !!window.electronAPI?.httpRequest
}

/**
 * 获取 API 基础 URL
 * Electron 环境使用绝对地址，浏览器环境使用相对路径
 */
export function getApiBase(): string {
  return hasElectronAPI() ? ENV.BACKEND_URL : ''
}

/**
 * 获取 WebSocket 基础 URL
 * Electron 环境使用 ws://127.0.0.1:8765，浏览器环境基于当前页面协议
 */
export function getWsBase(): string {
  if (hasElectronAPI()) {
    return ENV.WS_URL
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}`
}

/**
 * 获取 HTTP 基础 URL（用于 health check 等）
 */
export function getHttpBase(): string {
  if (hasElectronAPI()) {
    return ENV.BACKEND_URL
  }
  return `${window.location.protocol}//${window.location.host}`
}
