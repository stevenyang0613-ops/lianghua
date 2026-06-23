/**
 * 自动交易引擎
 * 策略自动执行和订单管理
 */

import { safeJsonParse } from './safeJson'
import { executeSignal as apiExecuteSignal, batchExecuteSignals as apiBatchExecuteSignals } from '../services/api'

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

// 与后端 STRATEGY_REGISTRY 对齐的合法策略 key
export const VALID_STRATEGIES = new Set([
  'dual_low', 'low_premium', 'momentum', 'xuanji_v8',
  'multi_factor', 'xibu_seven', 'xuanji_twelve',
  'sector_rotation', 'fusion',
])
const DEFAULT_STRATEGY = 'dual_low'

// 默认配置
const DEFAULT_CONFIG: AutoTradeConfig = {
  enabled: false,
  strategy: DEFAULT_STRATEGY,
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
// Debounced localStorage writes for auto-trader data
let _pendingConfig: AutoTradeConfig | null = null
let _pendingOrders: AutoTradeOrder[] | null = null
let _pendingLogs: AutoTradeLog[] | null = null
let _autoTraderFlushTimer: ReturnType<typeof setTimeout> | null = null
const AUTO_TRADER_FLUSH_DELAY = 500

function _flushAutoTrader(): void {
  if (_autoTraderFlushTimer) {
    clearTimeout(_autoTraderFlushTimer)
    _autoTraderFlushTimer = null
  }
  try {
    if (_pendingConfig !== null) {
      localStorage.setItem(CONFIG_KEY, JSON.stringify(_pendingConfig))
      _pendingConfig = null
    }
    if (_pendingOrders !== null) {
      localStorage.setItem(ORDERS_KEY, JSON.stringify(_pendingOrders))
      _pendingOrders = null
    }
    if (_pendingLogs !== null) {
      localStorage.setItem(LOGS_KEY, JSON.stringify(_pendingLogs))
      _pendingLogs = null
    }
  } catch (e) {
    console.warn('[AutoTrader] localStorage write failed:', e)
  }
}

function _scheduleAutoTraderFlush(): void {
  if (_autoTraderFlushTimer) return
  _autoTraderFlushTimer = setTimeout(_flushAutoTrader, AUTO_TRADER_FLUSH_DELAY)
}

export function getAutoTradeConfig(): AutoTradeConfig {
  try {
    const saved = localStorage.getItem(CONFIG_KEY)
    const parsed = safeJsonParse<Partial<AutoTradeConfig>>(saved, {})

    // 策略 key 合法性校验：非法值自动回退到默认值
    if (parsed.strategy && !VALID_STRATEGIES.has(parsed.strategy)) {
      console.warn(`[AutoTrader] 无效策略 key "${parsed.strategy}"，自动回退为 "${DEFAULT_STRATEGY}"`)
      parsed.strategy = DEFAULT_STRATEGY
    }

    return { ...DEFAULT_CONFIG, ...parsed }
  } catch {
    return { ...DEFAULT_CONFIG }
  }
}

// 更新配置
export function updateAutoTradeConfig(updates: Partial<AutoTradeConfig>): AutoTradeConfig {
  const config = getAutoTradeConfig()

  // 如果更新的策略 key 不合法，拒绝写入并回退
  if (updates.strategy && !VALID_STRATEGIES.has(updates.strategy)) {
    console.warn(`[AutoTrader] 拒绝写入无效策略 key "${updates.strategy}"`)
    updates.strategy = DEFAULT_STRATEGY
  }

  const newConfig = { ...config, ...updates }
  _pendingConfig = newConfig
  _scheduleAutoTraderFlush()
  return newConfig
}

// 获取订单列表
export function getAutoTradeOrders(): AutoTradeOrder[] {
  try {
    const saved = localStorage.getItem(ORDERS_KEY)
    return safeJsonParse<AutoTradeOrder[]>(saved, [])
  } catch {
    return []
  }
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
  _pendingOrders = orders
  _scheduleAutoTraderFlush()
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

  _pendingOrders = orders
  _scheduleAutoTraderFlush()
  return orders[index]
}

// 获取日志
export function getAutoTradeLogs(): AutoTradeLog[] {
  try {
    const saved = localStorage.getItem(LOGS_KEY)
    return safeJsonParse<AutoTradeLog[]>(saved, [])
  } catch {
    return []
  }
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
  _pendingLogs = logs
  _scheduleAutoTraderFlush()
  return newLog
}

// 清空日志
export function clearAutoTradeLogs(): void {
  if (_autoTraderFlushTimer) {
    clearTimeout(_autoTraderFlushTimer)
    _autoTraderFlushTimer = null
  }
  _pendingLogs = null
  try { localStorage.removeItem(LOGS_KEY) } catch { /* silent fail */ }
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
    return { should: false, reason: `置信度 ${(signal.confidence ?? 0).toFixed(2)} 低于阈值 ${config.minConfidence}` }
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

// 执行交易信号 — 调用后端真实 API
export async function executeSignal(
  signal: { code: string; name: string; action: 'buy' | 'sell'; price: number; confidence: number; reason: string },
  config: AutoTradeConfig,
  _quantity: number = 10
): Promise<AutoTradeOrder> {
  const order = addAutoTradeOrder({
    code: signal.code,
    name: signal.name,
    action: signal.action,
    price: signal.price,
    quantity: _quantity,
    reason: signal.reason,
    confidence: signal.confidence,
    strategy: config.strategy,
  })

  addAutoTradeLog({
    type: 'info',
    message: `创建${signal.action === 'buy' ? '买入' : '卖出'}订单: ${signal.code} ${signal.name}`,
    details: { orderId: order.id, price: signal.price, quantity: _quantity },
  })

  if (config.autoExecute) {
    try {
      // 调用后端真实交易接口
      const result = await apiExecuteSignal(signal.code)
      const executedCount = result.executed

      if (executedCount > 0) {
        updateOrderStatus(order.id, 'executed')
        addAutoTradeLog({
          type: 'trade',
          message: `订单已执行: ${signal.code} ${signal.action === 'buy' ? '买入' : '卖出'} ${result.orders?.[0]?.volume ?? _quantity}张`,
          details: { orderId: order.id, apiResult: result },
        })
      } else {
        // 后端返回未执行（例如信号不存在或已过期）
        updateOrderStatus(order.id, 'failed', '后端未执行：信号不存在或已过期')
        addAutoTradeLog({
          type: 'warning',
          message: `订单后端未执行: ${signal.code} — 信号不存在或已过期`,
          details: { orderId: order.id },
        })
      }
    } catch (err) {
      const errorMsg = err instanceof Error ? err.message : String(err)
      updateOrderStatus(order.id, 'failed', errorMsg)
      addAutoTradeLog({
        type: 'error',
        message: `订单执行失败: ${errorMsg}`,
        details: { orderId: order.id },
      })
    }
  }

  return order
}

// 批量执行所有待执行交易信号 — 调用后端真实 API
export async function batchExecutePendingSignals(config: AutoTradeConfig): Promise<{ executed: number; failed: number }> {
  const pendingOrders = getAutoTradeOrders().filter(o => o.status === 'pending')
  if (pendingOrders.length === 0) {
    return { executed: 0, failed: 0 }
  }

  try {
    const result = await apiBatchExecuteSignals()
    const executedCount = result.executed

    // 按后端返回标记已执行的订单 — 使用 code + action 双重匹配，优先匹配最新订单
    const apiOrders = result.orders || []
    let matched = 0
    for (const apiOrder of apiOrders) {
      // 按 code + action 匹配，优先取最新的 pending 订单（unshift 后按时间倒序）
      const localOrder = pendingOrders.find(
        o => o.code === apiOrder.code && o.action === apiOrder.side && o.status === 'pending'
      )
      if (localOrder) {
        updateOrderStatus(localOrder.id, 'executed')
        matched++
      } else {
        // 记录未匹配到的后端订单
        addAutoTradeLog({
          type: 'warning',
          message: `后端订单未匹配到本地记录: ${apiOrder.code} ${apiOrder.side}`,
          details: { apiOrder },
        })
      }
    }

    // 未匹配到的 pending 订单标记为失败（后端未执行）
    const remaining = pendingOrders.filter(o => o.status === 'pending')
    for (const o of remaining) {
      updateOrderStatus(o.id, 'failed', '后端未执行该订单')
      addAutoTradeLog({
        type: 'warning',
        message: `订单未执行: ${o.code} — 后端未处理`,
        details: { orderId: o.id },
      })
    }

    addAutoTradeLog({
      type: 'trade',
      message: `批量执行完成: 成功 ${matched} 笔, 未执行 ${remaining.length} 笔`,
      details: { apiResult: result },
    })

    return { executed: matched, failed: remaining.length }
  } catch (err) {
    const errorMsg = err instanceof Error ? err.message : String(err)
    // 全部标记失败
    for (const o of pendingOrders) {
      updateOrderStatus(o.id, 'failed', errorMsg)
    }
    addAutoTradeLog({
      type: 'error',
      message: `批量执行失败: ${errorMsg}`,
    })
    return { executed: 0, failed: pendingOrders.length }
  }
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
  batchExecutePendingSignals,
  getAutoTradeStats,
}
