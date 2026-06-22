/**
 * WebSocket 指数退避重连服务
 * 支持 Electron IPC 代理模式（通过 wsConnect/wsSend/wsClose 代理）
 */

import { WsIpcState, WsErrorDescriptions } from '@shared/types'
import type { WsIpcStateType } from '@shared/types'

type MessageHandler = (data: unknown) => void
type ConnectionState = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'

interface ReconnectConfig {
  initialDelay: number
  maxDelay: number
  multiplier: number
  jitter: number
  maxAttempts: number
  connectionTimeout: number
  heartbeatInterval: number
  staleThresholdMs: number
  staleCheckIntervalMs: number
}

const defaultConfig: ReconnectConfig = {
  initialDelay: 1000,
  maxDelay: 30000,
  multiplier: 2,
  jitter: 0.3,
  maxAttempts: 50,
  connectionTimeout: 5000,
  heartbeatInterval: 30000,
  staleThresholdMs: 60000,
  staleCheckIntervalMs: 10000,
}

export interface WsLogEntry {
  ts: number
  event: 'connect' | 'disconnect' | 'reconnect' | 'error' | 'close'
  detail: string
}

export interface WsErrorInfo {
  code: number
  reason: string
  ts: number
}

export interface WsDiagnostic {
  wsId: string
  state: ConnectionState
  connected: boolean
  isStale: boolean
  lastMessageTs: number
  staleMs: number
  attemptCount: number
  lastError: WsErrorInfo | null
  latency: number
  eventLog: WsLogEntry[]
}

export class WSReconnect {
  private ws: WebSocket | null = null
  private url: string
  private config: ReconnectConfig
  private state: ConnectionState = 'disconnected'
  private attempts = 0
  private currentDelay = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null
  private connectionTimer: ReturnType<typeof setTimeout> | null = null
  private messageQueue: unknown[] = []
  private messageHandlers: Map<string, Set<MessageHandler>> = new Map()
  private stateListeners: Set<(state: ConnectionState) => void> = new Set()
  private isManualClose = false
  private _eventLog: WsLogEntry[] = []
  private static MAX_LOG = 10
  private _lastPingTs = 0
  private _latency = 0
  private _latencyHistory: number[] = []
  private static MAX_LATENCY_HISTORY = 30
  private _highLatencyCount = 0
  private _latencyListeners: Set<(latency: number, consecutiveHigh: number) => void> = new Set()

  // 健康监控
  private _lastMessageTs = 0
  private _isStale = false
  private _staleCheckTimer: ReturnType<typeof setInterval> | null = null
  private _connectSeq = 0
  private _lastError: WsErrorInfo | null = null
  private _healthListeners: Set<(status: string, detail: number) => void> = new Set()

  // IPC 代理模式
  private useIPC: boolean
  private wsId: string
  private ipcCleanup: (() => void) | null = null

  constructor(url: string, config?: Partial<ReconnectConfig>, wsId?: string) {
    this.url = url
    this.config = { ...defaultConfig, ...config }
    this.wsId = wsId || `ws-${Math.random().toString(36).slice(2, 8)}`
    this.useIPC = typeof window !== 'undefined' && !!window.electronAPI?.wsConnect
  }

  async connect(overrideUrl?: string): Promise<void> {
    if (this.state === 'connected' || this.state === 'connecting') return
    this.isManualClose = false
    if (overrideUrl) this.url = overrideUrl
    this.setState('connecting')

    if (this.useIPC) {
      await this.connectViaIPC()
    } else {
      this.connectDirect()
    }
  }

  private connectDirect(): void {
    try {
      this.ws = new WebSocket(this.url)
      this.ws.binaryType = 'arraybuffer'
      this.setupEventHandlers()
      this.startConnectionTimeout()
    } catch (error) {
      console.error('[WS] 连接错误:', error)
      this._addLog('error', `连接失败: ${error}`)
      this.handleConnectionFailure()
    }
  }

  private async connectViaIPC(): Promise<void> {
    const api = window.electronAPI
    if (!api) throw new Error('[WS] electronAPI not available')
    try {
      // 清理上一次连接的监听器，避免重连时重复注册
      this.ipcCleanup?.()
      this.ipcCleanup = null

      // 连接序号：用于区分当前连接和旧连接的disconnected事件
      // wsConnect会先关闭旧连接再建新连接，旧连接的disconnected事件应被忽略
      const connectSeq = ++this._connectSeq

      // 注册 IPC 事件监听（必须在 wsConnect 之前注册，避免错过 ws-state 事件）
      const unsubState = api.onWsState((id: string, state: string, code?: number, reason?: string) => {
        if (id !== this.wsId) return
        if (state === WsIpcState.CONNECTED) {
          // 只有当前连接序号匹配时才处理
          if (connectSeq !== this._connectSeq) return
          this.clearConnectionTimeout()
          // 防止重复调用：IPC Promise可能已先resolve并调用onConnected()
          if (this.state === 'connected') return
          this.onConnected()
        } else if (state === WsIpcState.DISCONNECTED || state === WsIpcState.ERROR) {
          // 忽略旧连接的断开事件（序号不匹配或仍在connecting状态）
          if (connectSeq !== this._connectSeq) return
          if (this.state === 'connecting') return
          this.clearConnectionTimeout()
          this.onDisconnected(code || 1000, reason || '')
        }
      })

      const unsubMsg = api.onWsMessage((id: string, data: string, isBinary: boolean) => {
        if (id !== this.wsId) return
        if (isBinary) {
          // Base64 解码为 ArrayBuffer
          const binary = atob(data)
          const bytes = new Uint8Array(binary.length)
          for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
          this.handleMessage(bytes.buffer)
        } else {
          this.handleMessage(data)
        }
      })

      this.ipcCleanup = () => {
        unsubState()
        unsubMsg()
      }

      const result = await api.wsConnect(this.wsId, this.url)
      if (!result.ok) {
        this._addLog('error', `IPC连接失败: ${result.error}`)
        this.handleConnectionFailure()
        return
      }

      // wsConnect 返回 ok=true 但连接可能尚未触发 ws-state connected 事件
      // 竞态：onWsState 可能先于 IPC Promise 收到 connected 事件并调用 onConnected()
      // 此时 this.state 已经是 'connected'，不应再启动 connectionTimeout
      if (result.state === 'connected') {
        this.clearConnectionTimeout()
        if (this.state === 'connecting') {
          this.onConnected()
        }
      } else {
        this.startConnectionTimeout()
      }
    } catch (error) {
      console.error('[WS] IPC连接错误:', error)
      this._addLog('error', `IPC连接失败: ${error}`)
      this.handleConnectionFailure()
    }
  }

  private setupEventHandlers(): void {
    if (!this.ws) return
    this.ws.onopen = () => { this.clearConnectionTimeout(); this.onConnected() }
    this.ws.onclose = (e) => { this.clearConnectionTimeout(); this.onDisconnected(e.code, e.reason) }
    this.ws.onerror = (e) => console.error('[WS] 错误:', e)
    this.ws.onmessage = (e) => this.handleMessage(e.data)
  }

  private onConnected(): void {
    console.log('[WS] 已连接', this.useIPC ? '(via IPC)' : '')
    this._addLog('connect', `连接成功${this.useIPC ? ' (IPC)' : ''}`)
    this.attempts = 0
    this.currentDelay = 0
    this._lastError = null
    this._isStale = false
    this._lastMessageTs = Date.now()
    this.setState('connected')
    this.startHeartbeat()
    this.startStaleCheck()
    this.flushMessageQueue()
  }

  private onDisconnected(code: number, reason: string): void {
    console.log(`[WS] 已断开 code=${code} reason=${reason}`)
    this._addLog('disconnect', `code=${code} reason=${reason || 'none'}`)
    this._lastError = { code, reason, ts: Date.now() }
    this.stopHeartbeat()
    this.stopStaleCheck()
    this._isStale = false
    this.setState('disconnected')

    // 4001 = token失效，立即刷新token后重连（不指数退避）
    if (code === 4001) {
      console.log('[WS] Token失效(4001)，立即刷新token重连')
      this.refreshTokenAndReconnect()
      return
    }

    // 5030 = 服务端引擎不可用(Service Unavailable)，延长重连间隔避免刷屏
    if (code === 5030) {
      console.log('[WS] 服务端引擎不可用(5030)，30秒后重连')
      if (this.isManualClose) return
      this.attempts++
      this.setState('reconnecting')
      this.reconnectTimer = setTimeout(() => this.connect(), 30000)
      return
    }

    // 1013 = 连接数超限，延长重连间隔
    if (code === 1013) {
      console.log('[WS] 连接数超限(1013)，60秒后重连')
      if (this.isManualClose) return
      this.attempts++
      this.setState('reconnecting')
      this.reconnectTimer = setTimeout(() => this.connect(), 60000)
      return
    }

    if (!this.isManualClose) this.scheduleReconnect()
  }

  private async refreshTokenAndReconnect(): Promise<void> {
    try {
      const { getApiBase } = await import('./config')
      const base = getApiBase()
      // 从 /health 获取新 token
      const resp = await fetch(`${base}/health`)
      if (resp.ok) {
        const data = await resp.json()
        const newToken = data.ws_auth_token
        if (newToken) {
          localStorage.setItem('ws_auth_token', newToken)
          console.log('[WS] Token刷新成功，更新URL重连')
          // 更新URL中的token
          const { refreshWsToken } = await import('./wsInstances')
          refreshWsToken()
          return
        }
      }
      console.warn('[WS] Token刷新失败，使用常规重连')
    } catch (e) {
      console.warn('[WS] Token刷新异常，使用常规重连:', e)
    }
    // 刷新失败则常规重连
    if (!this.isManualClose) this.scheduleReconnect()
  }

  private handleConnectionFailure(): void {
    this.clearConnectionTimeout()
    this.setState('disconnected')
    this.scheduleReconnect()
  }

  private calculateDelay(): number {
    if (this.currentDelay === 0) {
      this.currentDelay = this.config.initialDelay
    } else {
      this.currentDelay = Math.min(this.currentDelay * this.config.multiplier, this.config.maxDelay)
    }
    // After 10+ consecutive failures, cap at maxDelay to prevent excessive retrying
    if (this.attempts > 10) {
      this.currentDelay = this.config.maxDelay
    }
    const jitter = this.currentDelay * this.config.jitter * (Math.random() * 2 - 1)
    return Math.max(0, this.currentDelay + jitter)
  }

  private scheduleReconnect(): void {
    if (this.isManualClose) return
    this.attempts++
    if (this.config.maxAttempts > 0 && this.attempts > this.config.maxAttempts) {
      console.error('[WS] 已达最大重试次数')
      return
    }
    const delay = this.calculateDelay()
    console.log(`[WS] 将在 ${Math.round(delay)}ms 后重连 (尝试 ${this.attempts})`)
    this._addLog('reconnect', `尝试 #${this.attempts}, 延迟 ${Math.round(delay)}ms`)
    this.setState('reconnecting')
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }

  private startConnectionTimeout(): void {
    this.connectionTimer = setTimeout(() => {
      console.warn('[WS] 连接超时')
      if (this.useIPC) {
        window.electronAPI?.wsClose(this.wsId)
      } else {
        this.ws?.close()
      }
      this.handleConnectionFailure()
    }, this.config.connectionTimeout)
  }

  private clearConnectionTimeout(): void {
    if (this.connectionTimer) { clearTimeout(this.connectionTimer); this.connectionTimer = null }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = setInterval(() => {
      this._lastPingTs = Date.now()
      this.send({ type: 'ping' })
    }, this.config.heartbeatInterval)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) { clearInterval(this.heartbeatTimer); this.heartbeatTimer = null }
  }

  private flushMessageQueue(): void {
    while (this.messageQueue.length > 0) {
      const msg = this.messageQueue.shift()
      if (msg) this.doSend(msg)
    }
  }

  private async handleMessage(data: string | ArrayBuffer): Promise<void> {
    this._lastMessageTs = Date.now()
    this._isStale = false
    try {
      let text: string
      if (typeof data === 'string') {
        text = data
      } else {
        // Binary gzip compressed message
        try {
          const ds = new DecompressionStream('gzip')
          const writer = ds.writable.getWriter()
          writer.write(new Uint8Array(data))
          writer.close()
          const reader = ds.readable.getReader()
          const chunks: Uint8Array[] = []
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            chunks.push(value)
          }
          const totalLen = chunks.reduce((s, c) => s + c.length, 0)
          const merged = new Uint8Array(totalLen)
          let offset = 0
          for (const c of chunks) { merged.set(c, offset); offset += c.length }
          text = new TextDecoder().decode(merged)
        } catch {
          // gzip 解压失败，尝试直接解码
          text = new TextDecoder().decode(new Uint8Array(data))
        }
      }
      const message = JSON.parse(text)
      if (message.type === 'ping') {
        this.send({ type: 'pong' })
        return
      }
      if (message.type === 'pong') {
        if (this._lastPingTs > 0) {
          this._latency = Date.now() - this._lastPingTs
          this._latencyHistory.push(this._latency)
          if (this._latencyHistory.length > WSReconnect.MAX_LATENCY_HISTORY) this._latencyHistory.shift()
          if (this._latency > 500) {
            this._highLatencyCount++
            this._latencyListeners.forEach(l => l(this._latency, this._highLatencyCount))
          } else {
            this._highLatencyCount = 0
          }
          this._lastPingTs = 0
        }
        return
      }
      this.messageHandlers.get(message.type)?.forEach(h => {
        try { h(message.data) } catch (e) {
          console.error('[WS] Handler error (isolated):', e)
          // Never let handler errors propagate — they must not crash the React tree
        }
      })
      this.messageHandlers.get('*')?.forEach(h => {
        try { h(message) } catch (e) {
          console.error('[WS] Wildcard handler error (isolated):', e)
        }
      })
    } catch (e) {
      console.error('[WS] Message handling error:', e, typeof data === 'string' ? data.slice(0, 100) : `binary ${(data as ArrayBuffer).byteLength} bytes`)
    }
  }

  private setState(state: ConnectionState): void {
    this.state = state
    this.stateListeners.forEach(l => l(state))
  }

  private doSend(message: unknown): void {
    const payload = JSON.stringify(message)
    if (this.useIPC) {
      window.electronAPI?.wsSend(this.wsId, payload)
    } else if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(payload)
    }
  }

  send(message: unknown): void {
    if (this.state === 'connected') this.doSend(message)
    else this.messageQueue.push(message)
  }

  subscribe(type: string, handler: MessageHandler): () => void {
    if (!this.messageHandlers.has(type)) this.messageHandlers.set(type, new Set())
    this.messageHandlers.get(type)?.add(handler)
    return () => this.messageHandlers.get(type)?.delete(handler)
  }

  onStateChange(listener: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(listener)
    // Defer initial callback to prevent synchronous setState during mount
    // which causes React error #300 (Maximum update depth exceeded)
    const currentState = this.state
    queueMicrotask(() => {
      if (this.stateListeners.has(listener)) {
        listener(currentState)
      }
    })
    return () => this.stateListeners.delete(listener)
  }

  getState(): ConnectionState { return this.state }
  isConnected(): boolean { return this.state === 'connected' }
  getAttemptCount(): number { return this.attempts }

  disconnect(): void {
    this.isManualClose = true
    this._addLog('close', '手动断开')
    if (this.reconnectTimer) { clearTimeout(this.reconnectTimer); this.reconnectTimer = null }
    this.stopHeartbeat()
    this.stopStaleCheck()
    this.clearConnectionTimeout()
    if (this.useIPC) {
      window.electronAPI?.wsClose(this.wsId)
    } else {
      this.ws?.close()
    }
    this.ws = null
    this.ipcCleanup?.()
    this.ipcCleanup = null
    this.setState('disconnected')
  }

  reset(url?: string): void {
    this.disconnect()
    if (url) this.url = url
    this.attempts = 0
    this.currentDelay = 0
    this.messageQueue = []
  }

  private _addLog(event: WsLogEntry['event'], detail: string): void {
    this._eventLog.push({ ts: Date.now(), event, detail })
    if (this._eventLog.length > WSReconnect.MAX_LOG) this._eventLog.shift()
  }

  getEventLog(): WsLogEntry[] {
    return [...this._eventLog]
  }

  getLatency(): number {
    return this._latency
  }

  getLatencyHistory(): number[] {
    return [...this._latencyHistory]
  }

  onLatencyWarning(listener: (latency: number, consecutiveHigh: number) => void): () => void {
    this._latencyListeners.add(listener)
    return () => this._latencyListeners.delete(listener)
  }

  // ---- 健康监控 ----

  private startStaleCheck(): void {
    this.stopStaleCheck()
    this._staleCheckTimer = setInterval(() => {
      if (!this._lastMessageTs || this.state !== 'connected') return
      const elapsed = Date.now() - this._lastMessageTs
      if (elapsed > this.config.staleThresholdMs && !this._isStale) {
        this._isStale = true
        this._healthListeners.forEach(l => l('stale', elapsed))
      }
    }, this.config.staleCheckIntervalMs)
  }

  private stopStaleCheck(): void {
    if (this._staleCheckTimer) { clearInterval(this._staleCheckTimer); this._staleCheckTimer = null }
  }

  isStale(): boolean { return this._isStale }

  getLastError(): WsErrorInfo | null { return this._lastError }

  updateStaleThreshold(ms: number): void {
    this.config.staleThresholdMs = ms
    if (this._isStale && this._lastMessageTs && Date.now() - this._lastMessageTs <= ms) {
      this._isStale = false
    }
  }

  onHealthWarning(listener: (status: string, detail: number) => void): () => void {
    this._healthListeners.add(listener)
    return () => this._healthListeners.delete(listener)
  }

  getDiagnostic(): WsDiagnostic {
    return {
      wsId: this.wsId,
      state: this.state,
      connected: this.isConnected(),
      isStale: this._isStale,
      lastMessageTs: this._lastMessageTs,
      staleMs: this._lastMessageTs ? Date.now() - this._lastMessageTs : -1,
      attemptCount: this.attempts,
      lastError: this._lastError,
      latency: this._latency,
      eventLog: this.getEventLog(),
    }
  }

  /** 根据错误码返回用户友好的错误描述 */
  static describeError(error: WsErrorInfo | null): string {
    if (!error) return ''
    return WsErrorDescriptions[error.code] || error.reason || `连接错误 (${error.code})`
  }
}

export const createWSReconnect = (url: string, config?: Partial<ReconnectConfig>, wsId?: string) => new WSReconnect(url, config, wsId)
export default WSReconnect
