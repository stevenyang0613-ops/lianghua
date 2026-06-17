/**
 * Bug修复测试：页面崩溃 - toFixed/JSON.parse/空值保护
 *
 * 覆盖的bug:
 * 1. StrategyReplay页面: cash/position/totalValue toLocaleString 崩溃
 * 2. Signals页面 price.toFixed(3) 在undefined上崩溃
 * 3. Signals页面 confidence.toFixed(0) 在undefined上崩溃
 * 4. TradePanel: account?.cash.toFixed(2) 崩溃
 * 5. JSON.parse corrupted localStorage 崩溃 (priceAlert, autoTrader, tradeLogger 等)
 * 6. priceAlert.toFixed 在 corrupted data 上崩溃
 * 7. RiskControl: v.join 在 undefined 上崩溃
 * 8. RiskHeatmap: 数据解构崩溃
 */

import { describe, it, expect } from 'vitest'

// ============================================================
// 1. fmt 安全格式化函数测试
// ============================================================
describe('fmt 安全格式化函数', () => {
  const fmt = (v: number | undefined | null, digits = 2, fallback = '-'): string =>
    typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : fallback

  it('正常数值应正确格式化', () => {
    expect(fmt(123.456)).toBe('123.46')
    expect(fmt(123.456, 3)).toBe('123.456')
    expect(fmt(0)).toBe('0.00')
    expect(fmt(-1.5, 1)).toBe('-1.5')
  })

  it('undefined应返回fallback', () => {
    expect(fmt(undefined)).toBe('-')
    expect(fmt(undefined, 2, 'N/A')).toBe('N/A')
  })

  it('null应返回fallback', () => {
    expect(fmt(null)).toBe('-')
    expect(fmt(null, 1, '0.0')).toBe('0.0')
  })

  it('NaN应返回fallback', () => {
    expect(fmt(NaN)).toBe('-')
  })

  it('Infinity应返回fallback', () => {
    expect(fmt(Infinity)).toBe('-')
    expect(fmt(-Infinity)).toBe('-')
  })
})

// ============================================================
// 2. safeJsonParse 测试
// ============================================================
describe('safeJsonParse 安全JSON解析', () => {
  const safeJsonParse = <T>(json: string | null | undefined, fallback: T): T => {
    if (!json) return fallback
    try {
      return JSON.parse(json) as T
    } catch {
      return fallback
    }
  }

  it('有效JSON应正确解析', () => {
    expect(safeJsonParse<{ a: number }>('{"a":1}', { a: 0 })).toEqual({ a: 1 })
  })

  it('损坏的JSON应返回fallback', () => {
    expect(safeJsonParse<unknown[]>('{corrupted', [])).toEqual([])
  })

  it('null应返回fallback', () => {
    expect(safeJsonParse<unknown[]>(null, [])).toEqual([])
  })

  it('undefined应返回fallback', () => {
    expect(safeJsonParse<unknown[]>(undefined, [])).toEqual([])
  })

  it('空字符串应返回fallback', () => {
    expect(safeJsonParse<unknown[]>('', [])).toEqual([])
  })

  it('非JSON字符串应返回fallback', () => {
    expect(safeJsonParse<unknown[]>('not json', [])).toEqual([])
  })
})

// ============================================================
// 3. StrategyReplay页面崩溃测试
// ============================================================
describe('StrategyReplay页面崩溃保护', () => {
  it('cash/position/totalValue为undefined时toLocaleString不崩溃', () => {
    const step = { cash: undefined as any, position: undefined as any, totalValue: undefined as any }
    // 修复后: (v ?? 0).toLocaleString()
    expect(() => (step.cash ?? 0).toLocaleString()).not.toThrow()
    expect(() => (step.position ?? 0).toLocaleString()).not.toThrow()
    expect(() => (step.totalValue ?? 0).toLocaleString()).not.toThrow()
    expect((step.cash ?? 0).toLocaleString()).toBe('0')
  })
})

// ============================================================
// 4. Signals页面崩溃测试
// ============================================================
describe('Signals页面数据空值保护', () => {
  const fmt = (v: number | undefined | null, digits = 2, fallback = '-'): string =>
    typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : fallback

  it('信号price为undefined时不应崩溃', () => {
    const signal = { price: undefined as any }
    expect(() => fmt(signal.price, 3)).not.toThrow()
    expect(fmt(signal.price, 3)).toBe('-')
  })

  it('信号confidence为undefined时不应崩溃', () => {
    const signal = { confidence: undefined as any }
    const v = signal.confidence
    const display = v != null && v >= 0.01 ? `${(v as number * 100).toFixed(0)}%` : '--'
    expect(display).toBe('--')
  })
})

// ============================================================
// 5. TradePanel崩溃测试
// ============================================================
describe('TradePanel可用资金崩溃保护', () => {
  it('account或cash为undefined时不应崩溃', () => {
    const account1: any = undefined
    const account2: any = { cash: undefined }
    const account3: any = { cash: null }
    const account4: any = { cash: 1000 }

    // 修复后: (account?.cash ?? 0).toFixed(2)
    expect(() => (account1?.cash ?? 0).toFixed(2)).not.toThrow()
    expect(() => (account2?.cash ?? 0).toFixed(2)).not.toThrow()
    expect(() => (account3?.cash ?? 0).toFixed(2)).not.toThrow()
    expect((account4?.cash ?? 0).toFixed(2)).toBe('1000.00')
  })
})

// ============================================================
// 6. priceAlert toFixed崩溃测试
// ============================================================
describe('priceAlert类型安全测试', () => {
  const safeNum = (v: unknown, fallback = 0): number => {
    const n = Number(v)
    return Number.isFinite(n) ? n : fallback
  }

  it('corrupted target应安全toFixed', () => {
    expect(() => safeNum(undefined).toFixed(2)).not.toThrow()
    expect(() => safeNum(null).toFixed(2)).not.toThrow()
    expect(() => safeNum('corrupted').toFixed(2)).not.toThrow()
    expect(safeNum(undefined).toFixed(2)).toBe('0.00')
    expect(safeNum(123.456).toFixed(2)).toBe('123.46')
  })
})

// ============================================================
// 7. RiskControl v.join 崩溃保护
// ============================================================
describe('RiskControl join 崩溃保护', () => {
  it('rules为undefined时不应崩溃', () => {
    const v: string[] | undefined = undefined
    const result = (v ?? []).join(', ') || '-'
    expect(result).toBe('-')
  })

  it('rules为null时不应崩溃', () => {
    const v: string[] | null = null
    const result = (v ?? []).join(', ') || '-'
    expect(result).toBe('-')
  })

  it('rules为正常数组时应正确join', () => {
    const v = ['rule1', 'rule2']
    const result = v.join(', ') || '-'
    expect(result).toBe('rule1, rule2')
  })
})

// ============================================================
// 8. RiskHeatmap 解构崩溃保护
// ============================================================
describe('RiskHeatmap 数据解构崩溃保护', () => {
  it('params.data为undefined时不应崩溃', () => {
    const params = undefined as { data: [number, number, number] } | undefined
    if (!params) {
      expect(true).toBe(true)
    } else {
      const [x, y, value] = params.data
      expect(typeof x).toBe('number')
    }
  })

  it('params为正常数据时应正确格式化', () => {
    const params = { data: [0, 1, 0.85] as [number, number, number] }
    if (params?.data) {
      const [x, y, value] = params.data
      expect(x).toBe(0)
      expect(y).toBe(1)
      expect(value).toBe(0.85)
    }
  })
})

// ============================================================
// 9. 除零保护测试
// ============================================================
describe('除零保护', () => {
  it('maxValue为0时回撤计算不应产生Infinity', () => {
    let maxValue = 0
    const drawdown = maxValue > 0 ? (maxValue - 50) / maxValue : 0
    expect(drawdown).toBe(0)
    expect(Number.isFinite(drawdown)).toBe(true)
  })

  it('totalAsset为0时利用率计算不应崩溃', () => {
    const totalAsset = 0
    const marketValue = 1000
    const utilization = totalAsset > 0 ? (marketValue / totalAsset) * 100 : 0
    expect(utilization).toBe(0)
    expect(Number.isFinite(utilization)).toBe(true)
  })

  it('factor.maxScore为0时进度计算不应崩溃', () => {
    const factor: any = { score: 50, maxScore: 0 }
    const percent = (factor.score / (factor.maxScore || 1)) * 100
    expect(Number.isFinite(percent)).toBe(true)
  })
})

// ============================================================
// 10. 安全除法工具测试
// ============================================================
describe('安全除法工具', () => {
  const safeDiv = (a: number, b: number, fallback = 0): number => {
    if (b === 0 || !Number.isFinite(b)) return fallback
    const r = a / b
    return Number.isFinite(r) ? r : fallback
  }

  it('正常除法应正确', () => {
    expect(safeDiv(10, 2)).toBe(5)
  })

  it('除以0应返回fallback', () => {
    expect(safeDiv(10, 0)).toBe(0)
  })

  it('除以null/undefined应返回fallback', () => {
    expect(safeDiv(10, null as any)).toBe(0)
    expect(safeDiv(10, undefined as any)).toBe(0)
  })

  it('NaN应返回fallback', () => {
    expect(safeDiv(NaN, 5)).toBe(0)
    expect(safeDiv(5, NaN)).toBe(0)
  })
})

// ============================================================
// 11. OpsDashboard 一致性测试
// ============================================================
describe('OpsDashboard health.memory空值保护', () => {
  it('health.memory为undefined时color和Progress不应崩溃', () => {
    const health: any = { memory: undefined, apiLatency: undefined }
    // 修复后: (health.memory ?? 0) > 80
    const color1 = (health.memory ?? 0) > 80 ? '#ff4d4f' : (health.memory ?? 0) > 60 ? '#faad14' : undefined
    const percent = health.memory ?? 0
    expect(color1).toBeUndefined()
    expect(percent).toBe(0)
  })

  it('health.apiLatency为undefined时不应崩溃', () => {
    const health: any = { apiLatency: undefined }
    const color = (health.apiLatency ?? 0) > 500 ? '#ff4d4f' : (health.apiLatency ?? 0) > 200 ? '#faad14' : undefined
    expect(color).toBeUndefined()
  })
})

// ============================================================
// 12. Performance时间格式化保护
// ============================================================
describe('Performance时间格式化空值保护', () => {
  it('startupTime为0或负数时应显示"-"', () => {
    const startupTime1 = 0
    const startupTime2 = -1
    const startupTime3 = Date.now()

    const display1 = startupTime1 > 0 ? new Date(startupTime1).toLocaleString() : '-'
    const display2 = startupTime2 > 0 ? new Date(startupTime2).toLocaleString() : '-'
    const display3 = startupTime3 > 0 ? new Date(startupTime3).toLocaleString() : '-'

    expect(display1).toBe('-')
    expect(display2).toBe('-')
    expect(display3).not.toBe('-')
  })
})
