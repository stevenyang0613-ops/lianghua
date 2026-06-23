/**
 * 订单状态流服务
 */
import { EventEmitter } from 'events'

export interface Order {
  orderId: string
  symbol: string
  side: 'buy' | 'sell'
  type: 'limit' | 'market'
  price: number
  quantity: number
  filledQuantity: number
  avgPrice: number
  status: OrderStatus
  commission: number
  createdAt: number
  updatedAt: number
  accountId: string
}

export type OrderStatus =
  | 'pending'
  | 'submitted'
  | 'partial'
  | 'filled'
  | 'cancelled'
  | 'rejected'

export interface Trade {
  tradeId: string
  orderId: string
  symbol: string
  side: 'buy' | 'sell'
  price: number
  quantity: number
  commission: number
  timestamp: number
}

export interface OrderEvent {
  type: 'created' | 'updated' | 'filled' | 'cancelled' | 'rejected' | 'trade'
  order: Order
  trade?: Trade
  timestamp: number
}

type OrderEventType = 'order' | 'trade' | 'error' | 'connected' | 'disconnected'

class OrderStreamService extends EventEmitter {
  private ws: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private isConnected: boolean = false
  private orders: Map<string, Order> = new Map()
  private activeOrders: Map<string, Order> = new Map()
  private trades: Trade[] = []
  private maxTradesHistory: number = 1000

  constructor(private url: string = 'wss://api.lianghua.com/ws/orders') {
    super()
  }

  connect(accountId: string): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return
    }
    // 清除旧的重连定时器，防止重复连接
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    try {
      const url = `${this.url}?accountId=${accountId}`
      this.ws = new WebSocket(url)
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
      this.emit('connected')
    }

    this.ws.onclose = () => {
      this.isConnected = false
      this.emit('disconnected')
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
        console.error('解析订单数据失败:', error)
      }
    }
  }

  private handleMessage(data: any): void {
    switch (data.type) {
      case 'order':
        this.handleOrderEvent(data.payload)
        break
      case 'trade':
        this.handleTradeEvent(data.payload)
        break
      case 'sync':
        this.handleSyncEvent(data.payload)
        break
      default:
        console.warn('未知订单消息类型:', data.type)
    }
  }

  private handleOrderEvent(payload: OrderEvent): void {
    const order = payload.order
    this.orders.set(order.orderId, order)

    // 更新活跃订单
    if (['pending', 'submitted', 'partial'].includes(order.status)) {
      this.activeOrders.set(order.orderId, order)
    } else {
      this.activeOrders.delete(order.orderId)
    }

    this.emit('order', payload)
  }

  private handleTradeEvent(payload: Trade): void {
    this.trades.unshift(payload)
    if (this.trades.length > this.maxTradesHistory) {
      this.trades.pop()
    }
    this.emit('trade', payload)
  }

  private handleSyncEvent(payload: { orders: Order[]; trades: Trade[] }): void {
    // 同步订单
    payload.orders.forEach(order => {
      this.orders.set(order.orderId, order)
      if (['pending', 'submitted', 'partial'].includes(order.status)) {
        this.activeOrders.set(order.orderId, order)
      }
    })

    // 同步成交记录
    this.trades = payload.trades.slice(0, this.maxTradesHistory)

    this.emit('sync', { orders: payload.orders, trades: payload.trades })
  }

  getOrder(orderId: string): Order | undefined {
    return this.orders.get(orderId)
  }

  getActiveOrders(): Order[] {
    return Array.from(this.activeOrders.values())
  }

  getAllOrders(): Order[] {
    return Array.from(this.orders.values())
  }

  getTrades(symbol?: string): Trade[] {
    if (symbol) {
      return this.trades.filter(t => t.symbol === symbol)
    }
    return [...this.trades]
  }

  submitOrder(order: {
    symbol: string
    side: 'buy' | 'sell'
    type: 'limit' | 'market'
    price: number
    quantity: number
  }): Promise<string> {
    return new Promise((resolve, reject) => {
      if (!this.isConnected) {
        reject(new Error('未连接到服务器'))
        return
      }

      const orderId = this.generateOrderId()
      this.send({
        action: 'submit',
        order: {
          orderId,
          ...order,
        },
      })

      // 等待确认
      const handler = (event: OrderEvent) => {
        if (event.order.orderId === orderId) {
          this.off('order', handler)
          if (event.order.status === 'rejected') {
            reject(new Error('订单被拒绝'))
          } else {
            resolve(orderId)
          }
        }
      }
      this.on('order', handler)

      // 超时处理
      setTimeout(() => {
        this.off('order', handler)
        reject(new Error('订单提交超时'))
      }, 10000)
    })
  }

  cancelOrder(orderId: string): Promise<void> {
    return new Promise((resolve, reject) => {
      if (!this.isConnected) {
        reject(new Error('未连接到服务器'))
        return
      }

      this.send({
        action: 'cancel',
        orderId,
      })

      const handler = (event: OrderEvent) => {
        if (event.order.orderId === orderId && event.type === 'cancelled') {
          this.off('order', handler)
          resolve()
        }
      }
      this.on('order', handler)

      setTimeout(() => {
        this.off('order', handler)
        reject(new Error('取消订单超时'))
      }, 10000)
    })
  }

  private generateOrderId(): string {
    return `ORD${Date.now()}${Math.random().toString(36).substr(2, 9)}`
  }

  private send(data: any): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.reconnectTimer = setTimeout(() => {
      // 需要重新获取accountId来重连
      this.emit('reconnect-needed')
    }, 5000)
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
    this.orders.clear()
    this.activeOrders.clear()
    this.trades = []
    this.isConnected = false
  }

  onOrder(callback: (event: OrderEvent) => void): () => void {
    this.on('order', callback)
    return () => this.off('order', callback)
  }

  onTrade(callback: (trade: Trade) => void): () => void {
    this.on('trade', callback)
    return () => this.off('trade', callback)
  }
}

export const orderStreamService = new OrderStreamService()
export default OrderStreamService
