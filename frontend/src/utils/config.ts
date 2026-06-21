/**
 * 应用环境配置
 * 统一管理开发/生产环境下的 API 地址
 */

// 后端服务配置
const BACKEND_HOST = '127.0.0.1'
const BACKEND_PORT = 8765
let _actualPort = BACKEND_PORT
let _portChangeListeners: ((port: number) => void)[] = []

// 浏览器环境下探测到的后端直接 URL（绕过 Vite 代理）
let _browserBackendUrl: string | null = null

export function setBackendPort(port: number): void {
  _actualPort = port
  _portChangeListeners.forEach(cb => cb(port))
}

/**
 * 设置浏览器环境探测到的后端 URL
 * 当 Vite 代理不可用时，StartupLoading 探测后端直接地址后调用此函数
 */
export function setBrowserBackendUrl(url: string): void {
  _browserBackendUrl = url
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
 * Electron 环境使用绝对地址，浏览器环境使用相对路径（依赖 Vite 代理或同源后端）
 *
 * 浏览器降级逻辑：
 * 1. 如果探测到后端直连地址（_browserBackendUrl），使用它
 * 2. 如果当前页面 host 就是后端（如 http://127.0.0.1:8765），用当前 origin
 * 3. 否则走 Vite 代理（/api → localhost:8765），返回空字符串让 fetch 使用相对路径
 */
export function getApiBase(): string {
  if (isElectronEnv()) return ENV.BACKEND_URL

  // 优先使用探测到的后端直连地址
  if (_browserBackendUrl) return _browserBackendUrl

  // 浏览器环境：如果页面直接由后端提供服务（Electron HTTP server 或生产部署）
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    const port = window.location.port
    if (host === BACKEND_HOST && port === String(_actualPort)) {
      return `${window.location.protocol}//${host}:${port}`
    }
  }

  // 走 Vite 代理路径
  return ''
}

/**
 * 浏览器环境下探测后端直连地址
 * 使用 Promise.any 并行尝试所有候选地址，首个成功即返回，其余自动取消
 * @param signal 外部 AbortSignal，用于组件卸载时取消请求
 * @returns true 表示探测成功
 */
export async function probeDirectBackend(signal?: AbortSignal): Promise<boolean> {
  if (isElectronEnv()) return false // Electron 不需要探测

  const candidates = [
    `http://${BACKEND_HOST}:${_actualPort}`,
    `http://localhost:${_actualPort}`,
  ]

  // 共享 AbortController：外部 signal 取消 或 任一候选成功 后，取消所有剩余请求
  const sharedController = new AbortController()
  const onExternalAbort = () => sharedController.abort()
  signal?.addEventListener('abort', onExternalAbort, { once: true })

  // 5 秒总超时：后端完全不可达时，避免等待浏览器默认 30-120s 超时
  const timeoutId = setTimeout(() => sharedController.abort(), 5000)

  const probePromises = candidates.map(async (base) => {
    try {
      const resp = await fetch(`${base}/health`, { signal: sharedController.signal })
      if (resp.ok) {
        const data = await resp.json()
        if (data.status === 'ok') {
          // 成功：取消其他候选的请求
          sharedController.abort()
          _browserBackendUrl = base
          // 如果后端返回了 token，也保存
          if (data.ws_auth_token) {
            setWsAuthToken(data.ws_auth_token)
          }
          console.log('[Config] Probed direct backend URL:', base)
          return true
        }
      }
      return false
    } catch {
      return false
    }
  })

  try {
    // Promise.any: 首个 resolve(true) 即返回；全部 false 则走 catch
    const result = await Promise.any(probePromises)
    clearTimeout(timeoutId)
    signal?.removeEventListener('abort', onExternalAbort)
    return result === true
  } catch {
    // 所有候选都失败或总超时
    clearTimeout(timeoutId)
    signal?.removeEventListener('abort', onExternalAbort)
    return false
  }
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
