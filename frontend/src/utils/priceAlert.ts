/**
 * 价格预警服务
 * 支持价格、涨跌幅、成交量预警
 */

import { safeJsonParse } from './safeJson'

export interface PriceAlert {
  id: string
  code: string
  name: string
  type: 'price_above' | 'price_below' | 'change_above' | 'change_below' | 'volume_above' | 'volume_below'
  target: number
  current: number
  triggered: boolean
  triggeredAt: number | null
  createdAt: number
  expiresAt: number | null
  repeat: boolean
  sound: boolean
  notify: boolean
  message: string
}

interface AlertCondition {
  type: PriceAlert['type']
  check: (current: number, target: number) => boolean
  label: (target: number) => string
}

const safeNum = (v: unknown, fallback = 0): number => {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

const ALERT_CONDITIONS: Record<string, AlertCondition> = {
  price_above: {
    type: 'price_above',
    check: (current, target) => current >= target,
    label: (target) => `价格高于 ¥${safeNum(target).toFixed(2)}`,
  },
  price_below: {
    type: 'price_below',
    check: (current, target) => current <= target,
    label: (target) => `价格低于 ¥${safeNum(target).toFixed(2)}`,
  },
  change_above: {
    type: 'change_above',
    check: (current, target) => current >= target,
    label: (target) => `涨幅大于 ${safeNum(target).toFixed(2)}%`,
  },
  change_below: {
    type: 'change_below',
    check: (current, target) => current <= target,
    label: (target) => `跌幅大于 ${Math.abs(safeNum(target)).toFixed(2)}%`,
  },
  volume_above: {
    type: 'volume_above',
    check: (current, target) => current >= target,
    label: (target) => `成交量大于 ${(safeNum(target) / 10000).toFixed(0)}万`,
  },
  volume_below: {
    type: 'volume_below',
    check: (current, target) => current <= target,
    label: (target) => `成交量小于 ${(safeNum(target) / 10000).toFixed(0)}万`,
  },
}

const ALERTS_KEY = 'price_alerts'

// 生成唯一ID
function generateId(): string {
  return `alert_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
}

// 获取所有预警
export function getAlerts(): PriceAlert[] {
  const saved = localStorage.getItem(ALERTS_KEY)
  return safeJsonParse<PriceAlert[]>(saved, [])
}

// 获取活跃预警
export function getActiveAlerts(): PriceAlert[] {
  return getAlerts().filter((a) => !a.triggered || a.repeat)
}

// 添加预警
export function addAlert(alert: Omit<PriceAlert, 'id' | 'triggered' | 'triggeredAt' | 'createdAt'>): PriceAlert {
  const alerts = getAlerts()

  const newAlert: PriceAlert = {
    ...alert,
    id: generateId(),
    triggered: false,
    triggeredAt: null,
    createdAt: Date.now(),
  }

  alerts.push(newAlert)
  localStorage.setItem(ALERTS_KEY, JSON.stringify(alerts))

  return newAlert
}

// 更新预警
export function updateAlert(id: string, updates: Partial<PriceAlert>): PriceAlert | null {
  const alerts = getAlerts()
  const index = alerts.findIndex((a) => a.id === id)

  if (index === -1) return null

  alerts[index] = { ...alerts[index], ...updates }
  localStorage.setItem(ALERTS_KEY, JSON.stringify(alerts))

  return alerts[index]
}

// 删除预警
export function deleteAlert(id: string): boolean {
  const alerts = getAlerts()
  const filtered = alerts.filter((a) => a.id !== id)

  if (filtered.length === alerts.length) return false

  localStorage.setItem(ALERTS_KEY, JSON.stringify(filtered))
  return true
}

// 清除所有预警
export function clearAlerts(): void {
  localStorage.removeItem(ALERTS_KEY)
}

// 清除已触发的预警
export function clearTriggeredAlerts(): number {
  const alerts = getAlerts()
  const active = alerts.filter((a) => !a.triggered)
  const removed = alerts.length - active.length

  localStorage.setItem(ALERTS_KEY, JSON.stringify(active))
  return removed
}

// 检查预警条件
export function checkAlert(
  alert: PriceAlert,
  data: { price: number; change: number; volume: number }
): boolean {
  const condition = ALERT_CONDITIONS[alert.type]
  if (!condition) return false

  let currentValue: number
  switch (alert.type) {
    case 'price_above':
    case 'price_below':
      currentValue = data.price
      break
    case 'change_above':
    case 'change_below':
      currentValue = data.change
      break
    case 'volume_above':
    case 'volume_below':
      currentValue = data.volume
      break
    default:
      return false
  }

  return condition.check(currentValue, alert.target)
}

// 批量检查预警
export function checkAllAlerts(
  dataMap: Map<string, { price: number; change: number; volume: number }>
): PriceAlert[] {
  const alerts = getActiveAlerts()
  const triggered: PriceAlert[] = []

  alerts.forEach((alert) => {
    const data = dataMap.get(alert.code)
    if (!data) return

    if (checkAlert(alert, data)) {
      alert.triggered = true
      alert.triggeredAt = Date.now()
      alert.current = data.price
      triggered.push(alert)

      // 如果不是重复预警，则更新状态
      if (!alert.repeat) {
        updateAlert(alert.id, { triggered: true, triggeredAt: Date.now(), current: data.price })
      }
    }
  })

  return triggered
}

// 获取预警标签
export function getAlertLabel(alert: PriceAlert): string {
  const condition = ALERT_CONDITIONS[alert.type]
  return condition ? condition.label(alert.target) : alert.type
}

// 获取预警统计
export function getAlertStats(): {
  total: number
  active: number
  triggered: number
  byType: Record<string, number>
} {
  const alerts = getAlerts()

  return {
    total: alerts.length,
    active: alerts.filter((a) => !a.triggered || a.repeat).length,
    triggered: alerts.filter((a) => a.triggered).length,
    byType: alerts.reduce(
      (acc, a) => {
        acc[a.type] = (acc[a.type] || 0) + 1
        return acc
      },
      {} as Record<string, number>
    ),
  }
}

// 预警类型选项
export const ALERT_TYPE_OPTIONS = [
  { value: 'price_above', label: '价格高于' },
  { value: 'price_below', label: '价格低于' },
  { value: 'change_above', label: '涨幅大于' },
  { value: 'change_below', label: '跌幅大于' },
  { value: 'volume_above', label: '成交量放大' },
  { value: 'volume_below', label: '成交量缩小' },
]

export default {
  getAlerts,
  getActiveAlerts,
  addAlert,
  updateAlert,
  deleteAlert,
  clearAlerts,
  clearTriggeredAlerts,
  checkAlert,
  checkAllAlerts,
  getAlertLabel,
  getAlertStats,
  ALERT_TYPE_OPTIONS,
}
