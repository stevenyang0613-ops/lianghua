/**
 * 预警引擎
 */
import { EventEmitter } from 'events'

export interface AlertRule {
  id: string
  name: string
  type: AlertType
  condition: AlertCondition
  actions: AlertAction[]
  enabled: boolean
  priority: AlertPriority
  cooldown: number // 冷却时间（秒）
  lastTriggered?: number
  metadata?: Record<string, any>
}

export type AlertType =
  | 'price'
  | 'volume'
  | 'change'
  | 'indicator'
  | 'position'
  | 'pnl'
  | 'custom'

export type AlertPriority = 'low' | 'medium' | 'high' | 'critical'

export interface AlertCondition {
  symbol?: string
  field: string
  operator: 'gt' | 'gte' | 'lt' | 'lte' | 'eq' | 'neq' | 'cross_up' | 'cross_down'
  value: number | string
  secondaryValue?: number // 用于区间判断
  timeframe?: string
}

export interface AlertAction {
  type: 'notify' | 'sound' | 'email' | 'webhook' | 'order'
  config: Record<string, any>
}

export interface AlertEvent {
  rule: AlertRule
  trigger: {
    time: number
    value: number
    previousValue?: number
    symbol: string
  }
  message: string
}

export interface MarketData {
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
  timestamp: number
  indicators?: Record<string, number>
}

export interface Position {
  symbol: string
  quantity: number
  avgPrice: number
  currentPrice: number
  marketValue: number
  profitLoss: number
  profitLossPercent: number
}

class AlertEngine extends EventEmitter {
  private rules: Map<string, AlertRule> = new Map()
  private priceHistory: Map<string, number[]> = new Map()
  private maxHistoryLength: number = 100
  private alertQueue: AlertEvent[] = []
  private processing: boolean = false

  constructor() {
    super()
    this.startProcessing()
  }

  addRule(rule: AlertRule): void {
    this.rules.set(rule.id, rule)
  }

  removeRule(ruleId: string): void {
    this.rules.delete(ruleId)
  }

  getRule(ruleId: string): AlertRule | undefined {
    return this.rules.get(ruleId)
  }

  getAllRules(): AlertRule[] {
    return Array.from(this.rules.values())
  }

  enableRule(ruleId: string): void {
    const rule = this.rules.get(ruleId)
    if (rule) {
      rule.enabled = true
    }
  }

  disableRule(ruleId: string): void {
    const rule = this.rules.get(ruleId)
    if (rule) {
      rule.enabled = false
    }
  }

  // 更新市场数据并检查预警
  updateMarketData(data: MarketData): void {
    // 记录价格历史
    const history = this.priceHistory.get(data.symbol) || []
    history.push(data.price)
    if (history.length > this.maxHistoryLength) {
      history.shift()
    }
    this.priceHistory.set(data.symbol, history)

    // 检查所有相关规则
    this.rules.forEach(rule => {
      if (!rule.enabled) return
      if (rule.condition.symbol && rule.condition.symbol !== data.symbol) return

      this.checkRule(rule, data)
    })
  }

  // 更新持仓数据
  updatePosition(position: Position): void {
    this.rules.forEach(rule => {
      if (!rule.enabled) return
      if (rule.type !== 'position' && rule.type !== 'pnl') return
      if (rule.condition.symbol && rule.condition.symbol !== position.symbol) return

      this.checkPositionRule(rule, position)
    })
  }

  private checkRule(rule: AlertRule, data: MarketData): void {
    const { condition } = rule
    const now = Date.now()

    // 检查冷却时间
    if (rule.lastTriggered && now - rule.lastTriggered < rule.cooldown * 1000) {
      return
    }

    let fieldValue: number | undefined
    switch (condition.field) {
      case 'price':
        fieldValue = data.price
        break
      case 'open':
        fieldValue = data.open
        break
      case 'high':
        fieldValue = data.high
        break
      case 'low':
        fieldValue = data.low
        break
      case 'prevClose':
        fieldValue = data.prevClose
        break
      case 'volume':
        fieldValue = data.volume
        break
      case 'amount':
        fieldValue = data.amount
        break
      case 'bidPrice':
        fieldValue = data.bidPrice
        break
      case 'askPrice':
        fieldValue = data.askPrice
        break
      case 'change':
        fieldValue = ((data.price - data.prevClose) / data.prevClose) * 100
        break
      case 'changePercent':
        fieldValue = ((data.price - data.prevClose) / data.prevClose) * 100
        break
      default:
        if (data.indicators && condition.field in data.indicators) {
          fieldValue = data.indicators[condition.field]
        }
    }

    if (fieldValue === undefined) return

    const targetValue = typeof condition.value === 'string'
      ? parseFloat(condition.value)
      : condition.value

    const history = this.priceHistory.get(data.symbol) || []
    const previousValue = history.length > 1 ? history[history.length - 2] : undefined

    if (this.evaluateCondition(fieldValue, targetValue, condition.operator, previousValue)) {
      this.triggerAlert(rule, {
        time: now,
        value: fieldValue,
        previousValue,
        symbol: data.symbol,
      })
    }
  }

  private checkPositionRule(rule: AlertRule, position: Position): void {
    const { condition } = rule
    const now = Date.now()

    if (rule.lastTriggered && now - rule.lastTriggered < rule.cooldown * 1000) {
      return
    }

    let fieldValue: number | undefined
    switch (condition.field) {
      case 'quantity':
        fieldValue = position.quantity
        break
      case 'profitLoss':
        fieldValue = position.profitLoss
        break
      case 'profitLossPercent':
        fieldValue = position.profitLossPercent
        break
      case 'marketValue':
        fieldValue = position.marketValue
        break
    }

    if (fieldValue === undefined) return

    const targetValue = typeof condition.value === 'string'
      ? parseFloat(condition.value)
      : condition.value

    if (this.evaluateCondition(fieldValue, targetValue, condition.operator)) {
      this.triggerAlert(rule, {
        time: now,
        value: fieldValue,
        symbol: position.symbol,
      })
    }
  }

  private evaluateCondition(
    value: number,
    target: number,
    operator: string,
    previousValue?: number
  ): boolean {
    switch (operator) {
      case 'gt':
        return value > target
      case 'gte':
        return value >= target
      case 'lt':
        return value < target
      case 'lte':
        return value <= target
      case 'eq':
        return Math.abs(value - target) < 0.0001
      case 'neq':
        return Math.abs(value - target) >= 0.0001
      case 'cross_up':
        return previousValue !== undefined && previousValue <= target && value > target
      case 'cross_down':
        return previousValue !== undefined && previousValue >= target && value < target
      default:
        return false
    }
  }

  private triggerAlert(rule: AlertRule, trigger: AlertEvent['trigger']): void {
    const message = this.generateAlertMessage(rule, trigger)

    const event: AlertEvent = {
      rule,
      trigger,
      message,
    }

    rule.lastTriggered = trigger.time

    // 添加到队列
    this.alertQueue.push(event)

    // 执行动作
    this.executeActions(rule.actions, event)

    // 发送事件
    this.emit('alert', event)
  }

  private generateAlertMessage(rule: AlertRule, trigger: AlertEvent['trigger']): string {
    const { condition, name } = rule
    const operatorText: Record<string, string> = {
      gt: '大于',
      gte: '大于等于',
      lt: '小于',
      lte: '小于等于',
      eq: '等于',
      neq: '不等于',
      cross_up: '上穿',
      cross_down: '下穿',
    }

    return `[${name}] ${trigger.symbol} ${condition.field} ${operatorText[condition.operator] || condition.operator} ${condition.value}，当前值: ${trigger.value.toFixed(2)}`
  }

  private executeActions(actions: AlertAction[], event: AlertEvent): void {
    actions.forEach(action => {
      switch (action.type) {
        case 'notify':
          this.sendNotification(event, action.config)
          break
        case 'sound':
          this.playSound(action.config)
          break
        case 'email':
          this.sendEmail(event, action.config)
          break
        case 'webhook':
          this.sendWebhook(event, action.config)
          break
        case 'order':
          this.executeOrder(event, action.config)
          break
      }
    })
  }

  private sendNotification(event: AlertEvent, config: any): void {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(`预警: ${event.rule.name}`, {
        body: event.message,
        icon: config.icon,
        tag: event.rule.id,
      })
    }
    this.emit('notification', event)
  }

  private playSound(config: any): void {
    try {
      const audio = new Audio(config.url || '/assets/alert.mp3')
      audio.volume = config.volume || 1
      audio.play()
    } catch (error) {
      console.error('播放声音失败:', error)
    }
  }

  private sendEmail(event: AlertEvent, config: any): void {
    // 通过后端发送邮件
    this.emit('email', { event, config })
  }

  private sendWebhook(event: AlertEvent, config: any): void {
    fetch(config.url, {
      method: config.method || 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...config.headers,
      },
      body: JSON.stringify({
        rule: event.rule.name,
        symbol: event.trigger.symbol,
        value: event.trigger.value,
        message: event.message,
        timestamp: event.trigger.time,
      }),
    }).catch(error => {
      console.error('Webhook发送失败:', error)
    })
  }

  private executeOrder(event: AlertEvent, config: any): void {
    this.emit('order', { event, config })
  }

  private startProcessing(): void {
    this.processing = true
  }

  stopProcessing(): void {
    this.processing = false
  }

  getAlertHistory(): AlertEvent[] {
    return [...this.alertQueue]
  }

  clearAlertHistory(): void {
    this.alertQueue = []
  }

  onAlert(callback: (event: AlertEvent) => void): () => void {
    this.on('alert', callback)
    return () => this.off('alert', callback)
  }
}

export const alertEngine = new AlertEngine()
export default AlertEngine
