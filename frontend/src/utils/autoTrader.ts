/**
 * 自动交易引擎
 * 策略自动执行和订单管理
 */

export interface AutoTradeConfig {
  enabled: boolean
  strategy: string
  maxPosition: number
  maxOrders: number
  stopLoss: number
  takeProfit: number
  trailingStop: boolean
  trailingPercent: number
  tradingHours: { start: string; end: string }
  excludeCodes: string[]
  minConfidence: number
  autoExecute: boolean
  notifyOnTrade: boolean
}

export interface AutoTradeOrder {
  id: string
  code: string
  name: string
  action: 'buy' | 'sell'
  price: number
  quantity: number
  reason: string
  confidence: number
  strategy: string
  status: 'pending' | 'executed' | 'cancelled' | 'failed'
  createdAt: number
  executedAt: number | null
  error?: string
}

export interface AutoTradeLog {
  id: string
  timestamp: number
  type: 'info' | 'warning' | 'error' | 'trade'
  message: string
  details?: Record<string, unknown>
}

const CONFIG_KEY = 'auto_trade_config'
const ORDERS_KEY = 'auto_trade_orders'
const LOGS_KEY = 'auto_trade_logs'

// 默认配置
const DEFAULT_CONFIG: AutoTradeConfig = {
  enabled: false,
  strategy: 'macd_cross',
  maxPosition: 30,
  maxOrders: 5,
  stopLoss: -5,
  takeProfit: 10,
  trailingStop: false,
  trailingPercent: 3,
  tradingHours: { start: '09:30', end: '15:00' },
  excludeCodes: [],
  minConfidence: 0.7,
  autoExecute: false,
  notifyOnTrade: true,
}

// 生成唯一 ID
function generateId(): string {
  return `order_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
}

// 获取配置
export function getAutoTradeConfig(): AutoTradeConfig {
  const saved = localStorage.getItem(CONFIG_KEY)
  return saved ? { ...DEFAULT_CONFIG, ...JSON.parse(saved) } : DEFAULT_CONFIG
}

// 更新配置
export function updateAutoTradeConfig(updates: Partial<AutoTradeConfig>): AutoTradeConfig {
  const config = getAutoTradeConfig()
  const newConfig = { ...config, ...updates }
  localStorage.setItem(CONFIG_KEY, JSON.stringify(newConfig))
  return newConfig
}

// 获取订单列表
export function getAutoTradeOrders(): AutoTradeOrder[] {
  const saved = localStorage.getItem(ORDERS_KEY)
  return saved ? JSON.parse(saved) : []
}

// 添加订单
export function addAutoTradeOrder(order: Omit<AutoTradeOrder, 'id' | 'createdAt' | 'status' | 'executedAt'>): AutoTradeOrder {
  const orders = getAutoTradeOrders()
  const newOrder: AutoTradeOrder = {
    ...order,
    id: generateId(),
    status: 'pending',
    createdAt: Date.now(),
    executedAt: null,
  }
  orders.unshift(newOrder)
  // 只保留最近 100 条
  if (orders.length > 100) {
    orders.splice(100)
  }
  localStorage.setItem(ORDERS_KEY, JSON.stringify(orders))
  return newOrder
}

// 更新订单状态
export function updateOrderStatus(id: string, status: AutoTradeOrder['status'], error?: string): AutoTradeOrder | null {
  const orders = getAutoTradeOrders()
  const index = orders.findIndex(o => o.id === id)
  if (index === -1) return null

  orders[index].status = status
  orders[index].executedAt = status === 'executed' ? Date.now() : null
  if (error) orders[index].error = error

  localStorage.setItem(ORDERS_KEY, JSON.stringify(orders))
  return orders[index]
}

// 获取日志
export function getAutoTradeLogs(): AutoTradeLog[] {
  const saved = localStorage.getItem(LOGS_KEY)
  return saved ? JSON.parse(saved) : []
}

// 添加日志
export function addAutoTradeLog(log: Omit<AutoTradeLog, 'id' | 'timestamp'>): AutoTradeLog {
  const logs = getAutoTradeLogs()
  const newLog: AutoTradeLog = {
    ...log,
    id: `log_${Date.now()}`,
    timestamp: Date.now(),
  }
  logs.unshift(newLog)
  // 只保留最近 200 条
  if (logs.length > 200) {
    logs.splice(200)
  }
  localStorage.setItem(LOGS_KEY, JSON.stringify(logs))
  return newLog
}

// 清空日志
export function clearAutoTradeLogs(): void {
  localStorage.removeItem(LOGS_KEY)
}

// 检查交易时间
export function isTradingTime(config: AutoTradeConfig): boolean {
  const now = new Date()
  const currentTime = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`
  return currentTime >= config.tradingHours.start && currentTime <= config.tradingHours.end
}

// 检查是否应该执行交易
export function shouldExecuteTrade(
  signal: { code: string; action: 'buy' | 'sell'; confidence: number },
  config: AutoTradeConfig,
  positions: { code: string; quantity: number }[]
): { should: boolean; reason: string } {
  // 检查是否启用
  if (!config.enabled) {
    return { should: false, reason: '自动交易未启用' }
  }

  // 检查交易时间
  if (!isTradingTime(config)) {
    return { should: false, reason: '不在交易时间' }
  }

  // 检查置信度
  if (signal.confidence < config.minConfidence) {
    return { should: false, reason: `置信度 ${signal.confidence.toFixed(2)} 低于阈值 ${config.minConfidence}` }
  }

  // 检查排除列表
  if (config.excludeCodes.includes(signal.code)) {
    return { should: false, reason: '标的在排除列表中' }
  }

  // 检查持仓数量
  if (signal.action === 'buy' && positions.length >= config.maxPosition) {
    return { should: false, reason: `持仓数量已达上限 ${config.maxPosition}` }
  }

  // 检查待执行订单数量
  const pendingOrders = getAutoTradeOrders().filter(o => o.status === 'pending')
  if (pendingOrders.length >= config.maxOrders) {
    return { should: false, reason: `待执行订单已达上限 ${config.maxOrders}` }
  }

  return { should: true, reason: '符合执行条件' }
}

// 执行交易信号
export async function executeSignal(
  signal: { code: string; name: string; action: 'buy' | 'sell'; price: number; confidence: number; reason: string },
  config: AutoTradeConfig,
  quantity: number = 10
): Promise<AutoTradeOrder> {
  const order = addAutoTradeOrder({
    code: signal.code,
    name: signal.name,
    action: signal.action,
    price: signal.price,
    quantity,
    reason: signal.reason,
    confidence: signal.confidence,
    strategy: config.strategy,
  })

  addAutoTradeLog({
    type: 'info',
    message: `创建${signal.action === 'buy' ? '买入' : '卖出'}订单: ${signal.code} ${signal.name}`,
    details: { orderId: order.id, price: signal.price, quantity },
  })

  if (config.autoExecute) {
    try {
      // 这里应该调用实际的交易接口
      // 模拟执行
      await new Promise(resolve => setTimeout(resolve, 500))

      updateOrderStatus(order.id, 'executed')
      addAutoTradeLog({
        type: 'trade',
        message: `订单已执行: ${signal.code} ${signal.action === 'buy' ? '买入' : '卖出'} ${quantity}张`,
        details: { orderId: order.id },
      })
    } catch (err) {
      updateOrderStatus(order.id, 'failed', String(err))
      addAutoTradeLog({
        type: 'error',
        message: `订单执行失败: ${String(err)}`,
        details: { orderId: order.id },
      })
    }
  }

  return order
}

// 获取统计
export function getAutoTradeStats(): {
  totalOrders: number
  executedOrders: number
  pendingOrders: number
  failedOrders: number
  buyOrders: number
  sellOrders: number
  avgConfidence: number
} {
  const orders = getAutoTradeOrders()
  const executed = orders.filter(o => o.status === 'executed')
  const pending = orders.filter(o => o.status === 'pending')
  const failed = orders.filter(o => o.status === 'failed')

  return {
    totalOrders: orders.length,
    executedOrders: executed.length,
    pendingOrders: pending.length,
    failedOrders: failed.length,
    buyOrders: orders.filter(o => o.action === 'buy').length,
    sellOrders: orders.filter(o => o.action === 'sell').length,
    avgConfidence: executed.length > 0
      ? executed.reduce((sum, o) => sum + o.confidence, 0) / executed.length
      : 0,
  }
}

export default {
  getAutoTradeConfig,
  updateAutoTradeConfig,
  getAutoTradeOrders,
  addAutoTradeOrder,
  updateOrderStatus,
  getAutoTradeLogs,
  addAutoTradeLog,
  clearAutoTradeLogs,
  isTradingTime,
  shouldExecuteTrade,
  executeSignal,
  getAutoTradeStats,
}
