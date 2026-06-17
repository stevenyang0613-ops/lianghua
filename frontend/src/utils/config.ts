/**
 * 应用环境配置
 * 统一管理开发/生产环境下的 API 地址
 */

// 后端服务配置
const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8765
let _actualPort = BACKEND_PORT
let _portChangeListeners: ((port: number) => void)[] = []

export function setBackendPort(port: number): void {
  _actualPort = port
  _portChangeListeners.forEach(cb => cb(port))
}

export function getActualPort(): number {
  return _actualPort
}

export function onPortChange(callback: (port: number) => void): () => void {
  _portChangeListeners.push(callback)
  return () => { _portChangeListeners = _portChangeListeners.filter(cb => cb !== callback) }
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
 * 检测是否在 Electron 环境中
 * 先检查 IPC 代理 (electronAPI.httpRequest)，再通过用户代理字符串兜底
 * 双重检测确保即使在 preload 加载异常时仍能正确识别 Electron 环境
 */
function isElectronEnv(): boolean {
  if (typeof window === 'undefined') return false
  if (window.electronAPI?.httpRequest) return true
  // 用户代理兜底检测
  return navigator.userAgent.includes('Electron')
}

/**
 * 检测是否有 IPC 代理可用
 */
function hasElectronAPI(): boolean {
  return typeof window !== 'undefined' && !!window.electronAPI?.httpRequest
}

/**
 * 获取 API 基础 URL
 * Electron 环境使用绝对地址，浏览器环境使用相对路径
 */
export function getApiBase(): string {
  return isElectronEnv() ? ENV.BACKEND_URL : ''
}

/**
 * 获取 WebSocket 基础 URL
 * Electron 环境使用 ws://127.0.0.1:8765，浏览器环境基于当前页面协议
 */
export function getWsBase(): string {
  if (isElectronEnv()) {
    return ENV.WS_URL
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}`
}

/**
 * 获取 HTTP 基础 URL（用于 health check 等）
 */
export function getHttpBase(): string {
  if (isElectronEnv()) {
    return ENV.BACKEND_URL
  }
  return `${window.location.protocol}//${window.location.host}`
}
