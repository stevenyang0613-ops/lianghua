/**
 * 告警通知系统
 * 支持多种通知渠道、告警规则、告警抑制、通知分组
 */

import { notification } from 'antd'

// 告警级别
export type AlertLevel = 'info' | 'warning' | 'error' | 'critical'

// 通知渠道
export type NotificationChannel = 'inApp' | 'email' | 'sms' | 'webhook' | 'wechat' | 'dingtalk'

// 告警规则
export interface AlertRule {
  id: string
  name: string
  description?: string
  level: AlertLevel
  enabled: boolean
  condition: {
    metric: string
    operator: '>' | '<' | '>=' | '<=' | '==' | '!=' | 'contains' | 'matches'
    threshold: number | string
    duration?: number  // 持续时间（秒）
  }
  channels: NotificationChannel[]
  suppressDuration: number  // 抑制时间（秒）
  tags?: string[]
  recipients?: string[]
  template?: string
  createdAt: number
  updatedAt: number
}

// 告警事件
export interface AlertEvent {
  id: string
  ruleId: string
  ruleName: string
  level: AlertLevel
  message: string
  details?: Record<string, unknown>
  status: 'firing' | 'resolved'
  firedAt: number
  resolvedAt?: number
  acknowledgedAt?: number
  acknowledgedBy?: string
  notifications: {
    channel: NotificationChannel
    sentAt: number
    status: 'sent' | 'failed'
  }[]
}

// 通知模板
export interface NotificationTemplate {
  id: string
  name: string
  channels: NotificationChannel[]
  subject?: string
  body: string
  variables: string[]  // 可用变量列表
}

// Webhook 配置
export interface WebhookConfig {
  url: string
  method: 'GET' | 'POST' | 'PUT'
  headers?: Record<string, string>
  template?: string
  retryCount?: number
  retryDelay?: number
}

/**
 * 验证 Webhook URL 是否安全（防止 SSRF）
 */
function isValidWebhookUrl(url: string): boolean {
  try {
    const parsed = new URL(url)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
    const hostname = parsed.hostname.toLowerCase()
    // 阻止内网地址
    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') return false
    if (hostname.startsWith('10.')) return false
    if (hostname.startsWith('192.168.')) return false
    if (hostname.startsWith('172.')) {
      const parts = hostname.split('.').map(Number)
      if (parts.length >= 2 && parts[1] >= 16 && parts[1] <= 31) return false
    }
    // 长度限制
    if (url.length > 2048) return false
    return true
  } catch {
    return false
  }
}

/**
 * 告警管理器
 */
export class AlertManager {
  private rules: Map<string, AlertRule> = new Map()
  private events: Map<string, AlertEvent> = new Map()
  private suppressionCache: Map<string, number> = new Map()  // ruleId -> lastFiredTime
  private metricCache: Map<string, { value: number | string; timestamp: number }> = new Map()
  private notificationTemplates: Map<string, NotificationTemplate> = new Map()
  private webhookConfigs: Map<string, WebhookConfig> = new Map()
  private checkInterval: ReturnType<typeof setInterval> | null = null

  /**
   * 初始化
   */
  init(): void {
    this.loadFromStorage()
    this.startCheckTimer()
  }

  /**
   * 添加告警规则
   */
  addRule(rule: Omit<AlertRule, 'id' | 'createdAt' | 'updatedAt'>): AlertRule {
    const id = this.generateId()
    const now = Date.now()

    const newRule: AlertRule = {
      ...rule,
      id,
      createdAt: now,
      updatedAt: now,
    }

    this.rules.set(id, newRule)
    this.saveToStorage()

    return newRule
  }

  /**
   * 更新告警规则
   */
  updateRule(id: string, updates: Partial<AlertRule>): AlertRule | null {
    const rule = this.rules.get(id)
    if (!rule) return null

    const updated: AlertRule = {
      ...rule,
      ...updates,
      id: rule.id,
      createdAt: rule.createdAt,
      updatedAt: Date.now(),
    }

    this.rules.set(id, updated)
    this.saveToStorage()

    return updated
  }

  /**
   * 删除告警规则
   */
  deleteRule(id: string): boolean {
    const result = this.rules.delete(id)
    if (result) {
      this.saveToStorage()
    }
    return result
  }

  /**
   * 获取所有规则
   */
  getRules(): AlertRule[] {
    return Array.from(this.rules.values())
  }

  /**
   * 更新指标值
   */
  updateMetric(metric: string, value: number | string): void {
    this.metricCache.set(metric, { value, timestamp: Date.now() })
    this.checkRules()
  }

  /**
   * 检查所有规则
   */
  private checkRules(): void {
    for (const rule of this.rules.values()) {
      if (!rule.enabled) continue

      const metricData = this.metricCache.get(rule.condition.metric)
      if (!metricData) continue

      const triggered = this.evaluateCondition(
        metricData.value,
        rule.condition.operator,
        rule.condition.threshold
      )

      if (triggered) {
        // 检查持续时间
        if (rule.condition.duration) {
          // 需要持续一段时间才触发
          const durationMs = rule.condition.duration * 1000
          if (Date.now() - metricData.timestamp < durationMs) {
            continue
          }
        }

        // 检查抑制
        if (this.isSuppressed(rule)) {
          continue
        }

        // 触发告警
        this.fireAlert(rule, metricData.value)
      }
    }
  }

  /**
   * 转义正则表达式中的特殊字符
   */
  private escapeRegExp(str: string): string {
    return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  }

  /**
   * 评估条件
   */
  private evaluateCondition(
    value: number | string,
    operator: AlertRule['condition']['operator'],
    threshold: number | string
  ): boolean {
    if (typeof value === 'number' && typeof threshold === 'number') {
      switch (operator) {
        case '>': return value > threshold
        case '<': return value < threshold
        case '>=': return value >= threshold
        case '<=': return value <= threshold
        case '==': return value === threshold
        case '!=': return value !== threshold
        default: return false
      }
    } else {
      const strValue = String(value)
      const strThreshold = String(threshold)

      switch (operator) {
        case '==': return strValue === strThreshold
        case '!=': return strValue !== strThreshold
        case 'contains': return strValue.includes(strThreshold)
        case 'matches': return new RegExp(this.escapeRegExp(strThreshold)).test(strValue)
        default: return false
      }
    }
  }

  /**
   * 检查是否被抑制
   */
  private isSuppressed(rule: AlertRule): boolean {
    const lastFired = this.suppressionCache.get(rule.id)
    if (!lastFired) return false

    return Date.now() - lastFired < rule.suppressDuration * 1000
  }

  /**
   * 触发告警
   */
  private fireAlert(rule: AlertRule, currentValue: number | string): AlertEvent {
    const event: AlertEvent = {
      id: this.generateId(),
      ruleId: rule.id,
      ruleName: rule.name,
      level: rule.level,
      message: this.formatMessage(rule, currentValue),
      status: 'firing',
      firedAt: Date.now(),
      notifications: [],
    }

    this.events.set(event.id, event)
    this.suppressionCache.set(rule.id, Date.now())

    // 发送通知
    for (const channel of rule.channels) {
      this.sendNotification(channel, event, rule)
    }

    return event
  }

  /**
   * 格式化告警消息
   */
  private formatMessage(rule: AlertRule, currentValue: number | string): string {
    return rule.template || `告警: ${rule.name} - 当前值: ${currentValue}, 阈值: ${rule.condition.threshold}`
  }

  /**
   * 发送通知
   */
  private async sendNotification(channel: NotificationChannel, event: AlertEvent, rule: AlertRule): Promise<void> {
    const notificationRecord = { channel, sentAt: Date.now(), status: 'sent' as const }

    try {
      switch (channel) {
        case 'inApp':
          this.sendInAppNotification(event)
          break
        case 'email':
          await this.sendEmailNotification(event, rule.recipients)
          break
        case 'webhook':
          await this.sendWebhookNotification(event, rule.id)
          break
        case 'dingtalk':
          await this.sendDingTalkNotification(event, rule.id)
          break
        case 'wechat':
          await this.sendWeChatNotification(event, rule.id)
          break
        case 'sms':
          await this.sendSMSNotification(event, rule.recipients)
          break
      }

      event.notifications.push(notificationRecord)
    } catch (error) {
      event.notifications.push({ ...notificationRecord, status: 'failed' })
      console.error(`[Alert] Failed to send ${channel} notification:`, error)
    }
  }

  /**
   * 应用内通知
   */
  private sendInAppNotification(event: AlertEvent): void {
    const type = event.level === 'critical' || event.level === 'error' ? 'error' :
                 event.level === 'warning' ? 'warning' : 'info'

    notification[type]({
      message: `告警: ${event.ruleName}`,
      description: event.message,
      duration: event.level === 'critical' ? 0 : 5,
    })
  }

  /**
   * 邮件通知
   */
  private async sendEmailNotification(event: AlertEvent, recipients?: string[]): Promise<void> {
    if (!recipients || recipients.length === 0) return

    // 调用后端发送邮件
    const emailPayload = {
      to: recipients,
      subject: `[${event.level.toUpperCase()}] ${event.ruleName}`,
      body: event.message,
      details: event.details,
    }
    if (window.electronAPI?.httpRequest) {
      try { await window.electronAPI.httpRequest('POST', '/api/v1/alerts/email', emailPayload) } catch { /* email delivery failed, don't block other channels */ }
    } else {
      try {
        const resp = await fetch('/api/v1/alerts/email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(emailPayload),
        })
        if (!resp.ok) console.warn('[AlertNotification] Email delivery failed:', resp.status)
      } catch { /* email delivery failed, don't block other channels */ }
    }
  }

  /**
   * Webhook 通知
   */
  private async sendWebhookNotification(event: AlertEvent, ruleId: string): Promise<void> {
    const config = this.webhookConfigs.get(ruleId)
    if (!config) return
    if (!isValidWebhookUrl(config.url)) {
      console.warn('[AlertNotification] Invalid webhook URL, skipping:', config.url)
      return
    }

    const body = config.template ?
      this.interpolateTemplate(config.template, event) :
      JSON.stringify(event)

    try {
      const resp = await fetch(config.url, {
        method: config.method,
        headers: config.headers || { 'Content-Type': 'application/json' },
        body,
      })
      if (!resp.ok) console.warn('[AlertNotification] Webhook delivery failed:', resp.status)
    } catch { /* webhook delivery failed, don't block other channels */ }
  }

  /**
   * 钉钉通知
   */
  private async sendDingTalkNotification(event: AlertEvent, ruleId: string): Promise<void> {
    // 从配置中获取钉钉 webhook URL
    const webhookUrl = localStorage.getItem(`dingtalk_webhook_${ruleId}`)
    if (!webhookUrl || !isValidWebhookUrl(webhookUrl)) return

    const body = {
      msgtype: 'markdown',
      markdown: {
        title: `告警: ${event.ruleName}`,
        text: `### ${event.ruleName}\n\n级别: ${event.level}\n\n${event.message}\n\n时间: ${new Date(event.firedAt).toLocaleString()}`,
      },
    }

    try {
      const resp = await fetch(webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) console.warn('[AlertNotification] DingTalk delivery failed:', resp.status)
    } catch { /* dingtalk delivery failed, don't block other channels */ }
  }

  /**
   * 企业微信通知
   */
  private async sendWeChatNotification(event: AlertEvent, ruleId: string): Promise<void> {
    const webhookUrl = localStorage.getItem(`wechat_webhook_${ruleId}`)
    if (!webhookUrl || !isValidWebhookUrl(webhookUrl)) return

    const body = {
      msgtype: 'markdown',
      markdown: {
        content: `## ${event.ruleName}\n> 级别: ${event.level}\n\n${event.message}\n\n时间: ${new Date(event.firedAt).toLocaleString()}`,
      },
    }

    try {
      const resp = await fetch(webhookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) console.warn('[AlertNotification] WeChat delivery failed:', resp.status)
    } catch { /* wechat delivery failed, don't block other channels */ }
  }

  /**
   * 短信通知
   */
  private async sendSMSNotification(event: AlertEvent, recipients?: string[]): Promise<void> {
    if (!recipients || recipients.length === 0) return

    if (window.electronAPI?.httpRequest) {
      try { await window.electronAPI.httpRequest('POST', '/api/v1/alerts/sms', {
        phones: recipients,
        message: `[${event.level.toUpperCase()}] ${event.ruleName}: ${event.message}`,
      }) } catch { /* SMS delivery failed, don't block other channels */ }
    } else {
      try {
        const resp = await fetch('/api/v1/alerts/sms', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            phones: recipients,
            message: `[${event.level.toUpperCase()}] ${event.ruleName}: ${event.message}`,
          }),
        })
        if (!resp.ok) console.warn('[AlertNotification] SMS delivery failed:', resp.status)
      } catch { /* SMS delivery failed, don't block other channels */ }
    }
  }

  /**
   * 模板插值
   */
  private interpolateTemplate(template: string, event: AlertEvent): string {
    return template
      .replace(/\{\{ruleName\}\}/g, event.ruleName)
      .replace(/\{\{level\}\}/g, event.level)
      .replace(/\{\{message\}\}/g, event.message)
      .replace(/\{\{firedAt\}\}/g, new Date(event.firedAt).toISOString())
      .replace(/\{\{details\}\}/g, JSON.stringify(event.details || {}))
  }

  /**
   * 确认告警
   */
  acknowledgeAlert(eventId: string, acknowledgedBy: string): AlertEvent | null {
    const event = this.events.get(eventId)
    if (!event) return null

    event.acknowledgedAt = Date.now()
    event.acknowledgedBy = acknowledgedBy

    return event
  }

  /**
   * 解决告警
   */
  resolveAlert(eventId: string): AlertEvent | null {
    const event = this.events.get(eventId)
    if (!event) return null

    event.status = 'resolved'
    event.resolvedAt = Date.now()

    return event
  }

  /**
   * 获取活动告警
   */
  getActiveAlerts(): AlertEvent[] {
    return Array.from(this.events.values())
      .filter(e => e.status === 'firing')
      .sort((a, b) => b.firedAt - a.firedAt)
  }

  /**
   * 获取告警历史
   */
  getAlertHistory(filter?: {
    level?: AlertLevel
    ruleId?: string
    startTime?: number
    endTime?: number
    limit?: number
  }): AlertEvent[] {
    let events = Array.from(this.events.values())

    if (filter) {
      if (filter.level) {
        events = events.filter(e => e.level === filter.level)
      }
      if (filter.ruleId) {
        events = events.filter(e => e.ruleId === filter.ruleId)
      }
      if (filter.startTime) {
        events = events.filter(e => e.firedAt >= filter.startTime!)
      }
      if (filter.endTime) {
        events = events.filter(e => e.firedAt <= filter.endTime!)
      }
    }

    events.sort((a, b) => b.firedAt - a.firedAt)

    if (filter?.limit) {
      events = events.slice(0, filter.limit)
    }

    return events
  }

  /**
   * 设置 Webhook 配置
   */
  setWebhookConfig(ruleId: string, config: WebhookConfig): void {
    this.webhookConfigs.set(ruleId, config)
  }

  /**
   * 手动触发告警
   */
  manualAlert(ruleName: string, level: AlertLevel, message: string, details?: Record<string, unknown>): AlertEvent {
    const event: AlertEvent = {
      id: this.generateId(),
      ruleId: 'manual',
      ruleName,
      level,
      message,
      details,
      status: 'firing',
      firedAt: Date.now(),
      notifications: [],
    }

    this.events.set(event.id, event)

    // 发送所有启用的渠道
    const channels: NotificationChannel[] = ['inApp']
    for (const channel of channels) {
      this.sendNotification(channel, event, { id: 'manual', name: ruleName, level, channels, enabled: true, condition: { metric: '', operator: '>', threshold: 0 }, suppressDuration: 0, createdAt: Date.now(), updatedAt: Date.now() })
    }

    return event
  }

  // 私有方法

  private generateId(): string {
    return `alert_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  private startCheckTimer(): void {
    this.checkInterval = setInterval(() => {
      this.checkRules()
    }, 10000) // 10秒检查一次
  }

  private loadFromStorage(): void {
    try {
      const rulesData = localStorage.getItem('alertRules')
      if (rulesData) {
        const rules = JSON.parse(rulesData)
        this.rules = new Map(Object.entries(rules))
      }

      const eventsData = localStorage.getItem('alertEvents')
      if (eventsData) {
        const events = JSON.parse(eventsData)
        this.events = new Map(Object.entries(events))
      }
    } catch (error) {
      console.error('[AlertManager] Failed to load from storage:', error)
    }
  }

  private _saveTimer: ReturnType<typeof setTimeout> | null = null
  private _pendingSave: boolean = false

  private saveToStorage(): void {
    // Debounce: avoid hammering localStorage during batch rule updates
    this._pendingSave = true
    if (this._saveTimer) return
    this._saveTimer = setTimeout(() => {
      this._saveTimer = null
      if (!this._pendingSave) return
      this._pendingSave = false
      try {
        localStorage.setItem('alertRules', JSON.stringify(Object.fromEntries(this.rules)))
        localStorage.setItem('alertEvents', JSON.stringify(Object.fromEntries(this.events)))
      } catch (error) {
        console.error('[AlertManager] Failed to save to storage:', error)
      }
    }, 500)
  }

  /**
   * 销毁
   */
  destroy(): void {
    if (this.checkInterval) {
      clearInterval(this.checkInterval)
      this.checkInterval = null
    }
    if (this._saveTimer) {
      clearTimeout(this._saveTimer)
      this._saveTimer = null
    }
    // flush any pending save
    if (this._pendingSave) {
      this._pendingSave = false
      try {
        localStorage.setItem('alertRules', JSON.stringify(Object.fromEntries(this.rules)))
        localStorage.setItem('alertEvents', JSON.stringify(Object.fromEntries(this.events)))
      } catch (error) {
        console.error('[AlertManager] Failed to save to storage:', error)
      }
    }
  }
}

// 导出单例
export const alertManager = new AlertManager()

// 预定义告警规则
export const predefinedRules: Omit<AlertRule, 'id' | 'createdAt' | 'updatedAt'>[] = [
  {
    name: '高内存使用',
    description: '内存使用率超过80%',
    level: 'warning',
    enabled: true,
    condition: {
      metric: 'memory.usage',
      operator: '>',
      threshold: 80,
    },
    channels: ['inApp'],
    suppressDuration: 300,  // 5分钟
  },
  {
    name: 'CPU过载',
    description: 'CPU使用率超过90%',
    level: 'error',
    enabled: true,
    condition: {
      metric: 'cpu.usage',
      operator: '>',
      threshold: 90,
      duration: 60,  // 持续1分钟
    },
    channels: ['inApp', 'webhook'],
    suppressDuration: 600,  // 10分钟
  },
  {
    name: 'API错误率过高',
    description: 'API错误率超过5%',
    level: 'critical',
    enabled: true,
    condition: {
      metric: 'api.errorRate',
      operator: '>',
      threshold: 5,
    },
    channels: ['inApp', 'email', 'webhook'],
    suppressDuration: 300,
  },
  {
    name: '交易信号延迟',
    description: '信号延迟超过5秒',
    level: 'warning',
    enabled: true,
    condition: {
      metric: 'signal.latency',
      operator: '>',
      threshold: 5000,
    },
    channels: ['inApp'],
    suppressDuration: 60,
  },
  {
    name: '账户亏损预警',
    description: '当日亏损超过阈值',
    level: 'warning',
    enabled: true,
    condition: {
      metric: 'account.dailyLoss',
      operator: '<',
      threshold: -10000,  // 亏损超过1万
    },
    channels: ['inApp', 'sms'],
    suppressDuration: 0,  // 不抑制
  },
]

// 初始化预定义规则
export function initPredefinedRules(): void {
  for (const rule of predefinedRules) {
    const existing = alertManager.getRules().find(r => r.name === rule.name)
    if (!existing) {
      alertManager.addRule(rule)
    }
  }
}

export default alertManager

/**
 * 停止告警管理器（清理定时器和监听器）
 */
export function stopAlertManager(): void {
  alertManager.destroy()
}

/**
 * 转义正则表达式中的特殊字符
 */
function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
