/**
 * WebSocket 指数退避重连服务
 * 支持 Electron IPC 代理模式（通过 wsConnect/wsSend/wsClose 代理）
 */

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
}

const defaultConfig: ReconnectConfig = {
  initialDelay: 1000,
  maxDelay: 30000,
  multiplier: 2,
  jitter: 0.3,
  maxAttempts: 0,
  connectionTimeout: 10000,
  heartbeatInterval: 30000,
}

export interface WsLogEntry {
  ts: number
  event: 'connect' | 'disconnect' | 'reconnect' | 'error' | 'close'
  detail: string
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

  connect(overrideUrl?: string): void {
    if (this.state === 'connected' || this.state === 'connecting') return
    this.isManualClose = false
    if (overrideUrl) this.url = overrideUrl
    this.setState('connecting')

    if (this.useIPC) {
      this.connectViaIPC()
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
    try {
      // 注册 IPC 事件监听
      const unsubState = window.electronAPI!.onWsState((id: string, state: string, code?: number, reason?: string) => {
        if (id !== this.wsId) return
        if (state === 'connected') {
          this.clearConnectionTimeout()
          this.onConnected()
        } else if (state === 'disconnected' || state === 'error') {
          this.clearConnectionTimeout()
          this.onDisconnected(code || 1000, reason || '')
        }
      })

      const unsubMsg = window.electronAPI!.onWsMessage((id: string, data: string, isBinary: boolean) => {
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

      const result = await window.electronAPI!.wsConnect(this.wsId, this.url)
      if (!result.ok) {
        this._addLog('error', `IPC连接失败: ${result.error}`)
        this.handleConnectionFailure()
        return
      }
      this.startConnectionTimeout()
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
    this.setState('connected')
    this.startHeartbeat()
    this.flushMessageQueue()
  }

  private onDisconnected(code: number, reason: string): void {
    console.log(`[WS] 已断开`)
    this._addLog('disconnect', `code=${code} reason=${reason || 'none'}`)
    this.stopHeartbeat()
    this.setState('disconnected')
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
    try {
      let text: string
      if (typeof data === 'string') {
        text = data
      } else {
        // Binary gzip compressed message
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
      }
      const message = JSON.parse(text)
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
      this.messageHandlers.get(message.type)?.forEach(h => h(message.data))
      this.messageHandlers.get('*')?.forEach(h => h(message))
    } catch { /* ignore */ }
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
    listener(this.state)
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
}

export const createWSReconnect = (url: string, config?: Partial<ReconnectConfig>, wsId?: string) => new WSReconnect(url, config, wsId)
export default WSReconnect
