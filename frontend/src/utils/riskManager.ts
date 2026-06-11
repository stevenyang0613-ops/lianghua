/**
 * 风控管理服务
 * 实时风险监控和预警
 */

export interface RiskRule {
  id: string
  name: string
  type: 'position_limit' | 'loss_limit' | 'exposure_limit' | 'concentration' | 'drawdown' | 'custom'
  enabled: boolean
  threshold: number
  current: number
  level: 'info' | 'warning' | 'critical'
  action: 'alert' | 'block' | 'auto_close'
  triggered: boolean
  triggeredAt: number | null
  description: string
}

export interface RiskStatus {
  overallLevel: 'safe' | 'warning' | 'danger' | 'critical'
  rules: RiskRule[]
  lastCheck: number
  recommendations: string[]
}

export interface PortfolioRisk {
  totalValue: number
  cashRatio: number
  positionRatio: number
  concentrationRisk: number
  leverage: number
  var95: number // 95% VaR
  maxDrawdown: number
  beta: number
  sharpeRatio: number
}

const RISK_RULES_KEY = 'risk_rules'
const RISK_HISTORY_KEY = 'risk_history'

// 默认风控规则
const DEFAULT_RULES: RiskRule[] = [
  {
    id: 'position_limit',
    name: '仓位上限',
    type: 'position_limit',
    enabled: true,
    threshold: 80,
    current: 0,
    level: 'warning',
    action: 'alert',
    triggered: false,
    triggeredAt: null,
    description: '总仓位占比超过阈值时预警',
  },
  {
    id: 'single_position_limit',
    name: '单一标的仓位上限',
    type: 'concentration',
    enabled: true,
    threshold: 20,
    current: 0,
    level: 'warning',
    action: 'alert',
    triggered: false,
    triggeredAt: null,
    description: '单一标的仓位占比超过阈值时预警',
  },
  {
    id: 'daily_loss_limit',
    name: '日亏损上限',
    type: 'loss_limit',
    enabled: true,
    threshold: -5,
    current: 0,
    level: 'critical',
    action: 'block',
    triggered: false,
    triggeredAt: null,
    description: '当日亏损超过阈值时禁止新开仓',
  },
  {
    id: 'max_drawdown',
    name: '最大回撤',
    type: 'drawdown',
    enabled: true,
    threshold: -15,
    current: 0,
    level: 'critical',
    action: 'auto_close',
    triggered: false,
    triggeredAt: null,
    description: '回撤超过阈值时自动减仓',
  },
]

// 获取风控规则
export function getRiskRules(): RiskRule[] {
  const saved = localStorage.getItem(RISK_RULES_KEY)
  if (saved) {
    try { return JSON.parse(saved) } catch { /* fall through */ }
  }
  localStorage.setItem(RISK_RULES_KEY, JSON.stringify(DEFAULT_RULES))
  return DEFAULT_RULES
}

// 更新风控规则
export function updateRiskRule(id: string, updates: Partial<RiskRule>): RiskRule | null {
  const rules = getRiskRules()
  const index = rules.findIndex(r => r.id === id)
  if (index === -1) return null

  rules[index] = { ...rules[index], ...updates }
  localStorage.setItem(RISK_RULES_KEY, JSON.stringify(rules))
  return rules[index]
}

// 重置风控规则
export function resetRiskRules(): void {
  localStorage.setItem(RISK_RULES_KEY, JSON.stringify(DEFAULT_RULES))
}

// 检查风控状态
export function checkRiskStatus(portfolio: PortfolioRisk): RiskStatus {
  const rules = getRiskRules()
  const recommendations: string[] = []
  let overallLevel: RiskStatus['overallLevel'] = 'safe'

  rules.forEach(rule => {
    if (!rule.enabled) return

    let triggered = false

    switch (rule.type) {
      case 'position_limit':
        rule.current = portfolio.positionRatio
        triggered = portfolio.positionRatio > rule.threshold
        break
      case 'concentration':
        rule.current = portfolio.concentrationRisk
        triggered = portfolio.concentrationRisk > rule.threshold
        break
      case 'loss_limit':
        // 日亏损需要外部传入
        break
      case 'drawdown':
        rule.current = portfolio.maxDrawdown
        triggered = portfolio.maxDrawdown < rule.threshold
        break
    }

    if (triggered && !rule.triggered) {
      rule.triggered = true
      rule.triggeredAt = Date.now()

      // 添加建议
      if (rule.type === 'position_limit') {
        recommendations.push('建议降低仓位，控制风险敞口')
      } else if (rule.type === 'concentration') {
        recommendations.push('持仓过于集中，建议分散投资')
      } else if (rule.type === 'drawdown') {
        recommendations.push('回撤较大，建议审视持仓或止损')
      }
    }

    if (rule.triggered) {
      if (rule.level === 'critical') overallLevel = 'critical'
      else if (overallLevel !== 'critical' && rule.level === 'warning') overallLevel = 'warning'
    }
  })

  // 保存更新后的规则
  localStorage.setItem(RISK_RULES_KEY, JSON.stringify(rules))

  // 记录风控历史
  addRiskHistory({
    timestamp: Date.now(),
    level: overallLevel,
    rules: rules.filter(r => r.triggered).map(r => r.name),
  })

  return {
    overallLevel,
    rules,
    lastCheck: Date.now(),
    recommendations,
  }
}

// 风控历史记录
interface RiskHistoryItem {
  timestamp: number
  level: RiskStatus['overallLevel']
  rules: string[]
}

function addRiskHistory(item: RiskHistoryItem): void {
  const history = getRiskHistory()
  history.push(item)
  // 只保留最近 100 条
  if (history.length > 100) {
    history.splice(0, history.length - 100)
  }
  localStorage.setItem(RISK_HISTORY_KEY, JSON.stringify(history))
}

export function getRiskHistory(): RiskHistoryItem[] {
  const saved = localStorage.getItem(RISK_HISTORY_KEY)
  if (saved) {
    try { return JSON.parse(saved) } catch { /* ignore corrupt data */ }
  }
  return []
}

// 计算组合风险指标
export function calculatePortfolioRisk(
  positions: { code: string; value: number; profit: number }[],
  cash: number,
  history?: { date: string; value: number }[]
): PortfolioRisk {
  const totalValue = positions.reduce((sum, p) => sum + p.value, 0) + cash
  const positionRatio = (totalValue > 0 ? (totalValue - cash) / totalValue : 0) * 100
  const cashRatio = (totalValue > 0 ? cash / totalValue : 0) * 100

  // 集中度风险（最大持仓占比）
  const maxPosition = Math.max(...positions.map(p => p.value), 0)
  const concentrationRisk = totalValue > 0 ? (maxPosition / totalValue) * 100 : 0

  // 最大回撤
  let maxDrawdown = 0
  if (history && history.length > 0) {
    let peak = history[0].value
    history.forEach(h => {
      if (h.value > peak) peak = h.value
      const drawdown = ((peak - h.value) / peak) * 100
      if (drawdown > maxDrawdown) maxDrawdown = drawdown
    })
  }

  // 简化的 VaR 计算（实际应使用历史模拟法或参数法）
  const dailyReturns = positions.map(p => p.profit / (p.value - p.profit || 1))
  const avgReturn = dailyReturns.reduce((a, b) => a + b, 0) / dailyReturns.length
  const variance = dailyReturns.reduce((sum, r) => sum + Math.pow(r - avgReturn, 2), 0) / dailyReturns.length
  const stdDev = Math.sqrt(variance)
  const var95 = totalValue * (avgReturn - 1.65 * stdDev) // 95% 置信区间

  return {
    totalValue,
    cashRatio,
    positionRatio,
    concentrationRisk,
    leverage: 1, // 简化，实际需要计算
    var95,
    maxDrawdown: -maxDrawdown,
    beta: 1, // 简化，实际需要回归计算
    sharpeRatio: avgReturn / (stdDev || 1), // 简化
  }
}

// 获取风控建议
export function getRiskRecommendations(status: RiskStatus): string[] {
  const recommendations: string[] = []

  if (status.overallLevel === 'critical') {
    recommendations.push('⚠️ 风险状态危急，建议立即减仓或清仓')
  } else if (status.overallLevel === 'danger') {
    recommendations.push('🔴 风险水平较高，请密切关注持仓变化')
  } else if (status.overallLevel === 'warning') {
    recommendations.push('🟡 存在一定风险，建议适度控制仓位')
  } else {
    recommendations.push('✅ 风险状态正常，继续保持监控')
  }

  status.rules.forEach(rule => {
    if (rule.triggered) {
      recommendations.push(`【${rule.name}】已触发阈值 (${rule.current.toFixed(1)}% > ${rule.threshold}%)`)
    }
  })

  return [...recommendations, ...status.recommendations]
}

export default {
  getRiskRules,
  updateRiskRule,
  resetRiskRules,
  checkRiskStatus,
  getRiskHistory,
  calculatePortfolioRisk,
  getRiskRecommendations,
}
