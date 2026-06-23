/**
 * 实时行情推送服务
 */
import { EventEmitter } from 'events'

export interface QuoteData {
  symbol: string
  price: number
  open: number
  high: number
  low: number
  prevClose: number
  volume: number
  amount: number
  bidPrice: number
  askPrice: number
  bidVolume: number
  askVolume: number
  timestamp: number
}

export interface QuoteUpdate {
  symbol: string
  price?: number
  volume?: number
  bidPrice?: number
  askPrice?: number
  timestamp: number
}

type QuoteEventType = 'quote' | 'update' | 'error' | 'connected' | 'disconnected'

class RealtimeQuoteService extends EventEmitter {
  private ws: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private pingTimer: ReturnType<typeof setTimeout> | null = null
  private subscriptions: Set<string> = new Set()
  private quotes: Map<string, QuoteData> = new Map()
  private isConnected: boolean = false
  private reconnectAttempts: number = 0
  private maxReconnectAttempts: number = 10
  private reconnectDelay: number = 1000

  constructor(private url: string = 'wss://api.lianghua.com/ws/quotes') {
    super()
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }
    // 清除旧的重连定时器，防止重复连接
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    try {
      this.ws = new WebSocket(this.url)
      this.setupEventHandlers()
    } catch (error) {
      this.emit('error', error)
      this.scheduleReconnect()
    }
  }

  private setupEventHandlers(): void {
    if (!this.ws) return

    this.ws.onopen = () => {
      this.isConnected = true
      this.reconnectAttempts = 0
      this.emit('connected')

      // 重新订阅所有股票
      this.subscriptions.forEach(symbol => {
        this.subscribeSymbol(symbol)
      })

      // 启动心跳
      this.startPing()
    }

    this.ws.onclose = () => {
      this.isConnected = false
      this.emit('disconnected')
      this.stopPing()
      this.scheduleReconnect()
    }

    this.ws.onerror = (error) => {
      this.emit('error', error)
    }

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        this.handleMessage(data)
      } catch (error) {
        console.error('解析行情数据失败:', error)
      }
    }
  }

  private handleMessage(data: any): void {
    switch (data.type) {
      case 'quote':
        this.handleFullQuote(data.payload)
        break
      case 'update':
        this.handleQuoteUpdate(data.payload)
        break
      case 'pong':
        // 心跳响应
        break
      default:
        console.warn('未知消息类型:', data.type)
    }
  }

  private handleFullQuote(payload: QuoteData): void {
    this.quotes.set(payload.symbol, payload)
    this.emit('quote', payload)
  }

  private handleQuoteUpdate(payload: QuoteUpdate): void {
    const existing = this.quotes.get(payload.symbol)
    if (existing) {
      const updated: QuoteData = {
        ...existing,
        ...payload,
        timestamp: payload.timestamp,
      } as QuoteData
      this.quotes.set(payload.symbol, updated)
      this.emit('update', { symbol: payload.symbol, data: updated, changes: payload })
    }
  }

  subscribe(symbols: string[]): void {
    symbols.forEach(symbol => {
      this.subscriptions.add(symbol)
      if (this.isConnected) {
        this.subscribeSymbol(symbol)
      }
    })
  }

  private subscribeSymbol(symbol: string): void {
    this.send({
      action: 'subscribe',
      symbol,
    })
  }

  unsubscribe(symbols: string[]): void {
    symbols.forEach(symbol => {
      this.subscriptions.delete(symbol)
      if (this.isConnected) {
        this.send({
          action: 'unsubscribe',
          symbol,
        })
      }
    })
  }

  getQuote(symbol: string): QuoteData | undefined {
    return this.quotes.get(symbol)
  }

  getAllQuotes(): Map<string, QuoteData> {
    return new Map(this.quotes)
  }

  private send(data: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private startPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer)
      this.pingTimer = null
    }
    this.pingTimer = setInterval(() => {
      this.send({ action: 'ping' })
    }, 30000)
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('达到最大重连次数，停止重连')
      // 状态更新：通知 UI 层重连已耗尽
      this.emit('maxReconnectReached', this.reconnectAttempts)
      this.emit('disconnected')
      return
    }

    this.reconnectAttempts++
    const delay = Math.min(
      this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1),
      30000
    )

    this.reconnectTimer = setTimeout(() => {
      this.connect()
    }, delay)
  }

  disconnect(): void {
    this.stopPing()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.subscriptions.clear()
    this.quotes.clear()
    this.isConnected = false
  }

  onQuote(callback: (quote: QuoteData) => void): () => void {
    this.on('quote', callback)
    return () => this.off('quote', callback)
  }

  onUpdate(callback: (update: { symbol: string; data: QuoteData; changes: QuoteUpdate }) => void): () => void {
    this.on('update', callback)
    return () => this.off('update', callback)
  }

  onError(callback: (error: any) => void): () => void {
    this.on('error', callback)
    return () => this.off('error', callback)
  }
}

export const realtimeQuoteService = new RealtimeQuoteService()
export default RealtimeQuoteService
