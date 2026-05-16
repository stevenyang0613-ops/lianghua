/**
 * 数据导入/导出工具
 * 支持导出市场数据、自选股、策略、预警等
 */

import type { ConvertibleQuote } from '../types'

export interface ExportData {
  version: string
  exportedAt: string
  appVersion: string
  data: {
    watchlist?: ConvertibleQuote[]
    alerts?: AlertConfig[]
    strategies?: StrategyConfig[]
    settings?: Record<string, unknown>
    analytics?: string
  }
}

export interface AlertConfig {
  id: string
  code: string
  name: string
  alertType: string
  threshold: number
  direction: string
  enabled: boolean
  createdAt: string
}

export interface StrategyConfig {
  id: string
  name: string
  type: string
  params: Record<string, unknown>
  enabled: boolean
  createdAt: string
}

const CURRENT_VERSION = '1.0.0'

// 导出数据到 JSON 文件
export async function exportToJson(
  data: ExportData['data'],
  filename = 'lianghua-export'
): Promise<void> {
  const exportData: ExportData = {
    version: CURRENT_VERSION,
    exportedAt: new Date().toISOString(),
    appVersion: '1.0.0',
    data,
  }

  const json = JSON.stringify(exportData, null, 2)
  const blob = new Blob([json], { type: 'application/json' })
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}-${new Date().toISOString().split('T')[0]}.json`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// 导出数据到 CSV 文件
export async function exportToCsv(
  quotes: ConvertibleQuote[],
  filename = 'lianghua-quotes'
): Promise<void> {
  const headers = [
    '代码', '名称', '价格', '涨跌幅', '正股价格', '转股价',
    '转股价值', '溢价率', '双低值', '成交量'
  ]

  const rows = quotes.map((q) => [
    q.code,
    q.name,
    q.price,
    q.change_pct?.toFixed(2) || 0,
    q.stock_price,
    q.conversion_price,
    q.conversion_value?.toFixed(2) || 0,
    q.premium_ratio?.toFixed(2) || 0,
    q.dual_low?.toFixed(2) || 0,
    q.volume || 0,
  ])

  const csv = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
  const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}-${new Date().toISOString().split('T')[0]}.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// 导出数据到 Excel (简化版，使用 HTML 表格)
export async function exportToExcel(
  quotes: ConvertibleQuote[],
  filename = 'lianghua-quotes'
): Promise<void> {
  const headers = [
    '代码', '名称', '价格', '涨跌幅', '正股价格', '转股价',
    '转股价值', '溢价率', '双低值', '成交量'
  ]

  let html = `
    <html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">
    <head><meta charset="utf-8"></head>
    <body>
    <table border="1">
      <tr>${headers.map((h) => `<th>${h}</th>`).join('')}</tr>
  `

  quotes.forEach((q) => {
    html += `<tr>
      <td>${q.code}</td>
      <td>${q.name}</td>
      <td>${q.price}</td>
      <td>${q.change_pct?.toFixed(2) || 0}%</td>
      <td>${q.stock_price}</td>
      <td>${q.conversion_price}</td>
      <td>${q.conversion_value?.toFixed(2) || 0}</td>
      <td>${q.premium_ratio?.toFixed(2) || 0}%</td>
      <td>${q.dual_low?.toFixed(2) || 0}</td>
      <td>${q.volume || 0}</td>
    </tr>`
  })

  html += '</table></body></html>'

  const blob = new Blob([html], { type: 'application/vnd.ms-excel' })
  const url = URL.createObjectURL(blob)

  const a = document.createElement('a')
  a.href = url
  a.download = `${filename}-${new Date().toISOString().split('T')[0]}.xls`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

// 从 JSON 文件导入数据
export async function importFromJson(file: File): Promise<ExportData | null> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string
        const data = JSON.parse(content) as ExportData
        resolve(data)
      } catch (error) {
        console.error('Failed to parse JSON:', error)
        resolve(null)
      }
    }
    reader.onerror = () => resolve(null)
    reader.readAsText(file)
  })
}

// 从 CSV 文件导入自选股
export async function importFromCsv(file: File): Promise<string[] | null> {
  return new Promise((resolve) => {
    const reader = new FileReader()
    reader.onload = (e) => {
      try {
        const content = e.target?.result as string
        const lines = content.split('\n')
        const codes: string[] = []

        // 跳过标题行
        for (let i = 1; i < lines.length; i++) {
          const line = lines[i].trim()
          if (line) {
            const columns = line.split(',')
            const code = columns[0]?.trim().replace(/"/g, '')
            if (code && /^\d{6}$/.test(code)) {
              codes.push(code)
            }
          }
        }

        resolve(codes.length > 0 ? codes : null)
      } catch (error) {
        console.error('Failed to parse CSV:', error)
        resolve(null)
      }
    }
    reader.onerror = () => resolve(null)
    reader.readAsText(file)
  })
}

// 验证导入数据版本兼容性
export function validateImportData(data: ExportData): {
  valid: boolean
  warnings: string[]
  errors: string[]
} {
  const result = { valid: true, warnings: [] as string[], errors: [] as string[] }

  if (!data.version) {
    result.errors.push('缺少版本信息')
    result.valid = false
  }

  if (!data.data) {
    result.errors.push('缺少数据内容')
    result.valid = false
  }

  if (data.version !== CURRENT_VERSION) {
    result.warnings.push(`版本不匹配: 当前 ${CURRENT_VERSION}, 导入 ${data.version}`)
  }

  const daysSinceExport = data.exportedAt
    ? (Date.now() - new Date(data.exportedAt).getTime()) / (1000 * 60 * 60 * 24)
    : 0

  if (daysSinceExport > 30) {
    result.warnings.push(`导出数据已超过 ${Math.floor(daysSinceExport)} 天，可能已过时`)
  }

  return result
}

// 批量导出所有用户数据
export async function exportAllUserData(): Promise<void> {
  // 从 localStorage 收集数据
  const data: ExportData['data'] = {}

  // 自选股
  const watchlistStr = localStorage.getItem('watchlist')
  if (watchlistStr) {
    try {
      data.watchlist = JSON.parse(watchlistStr)
    } catch { /* ignore */ }
  }

  // 预警配置
  const alertsStr = localStorage.getItem('alerts')
  if (alertsStr) {
    try {
      data.alerts = JSON.parse(alertsStr)
    } catch { /* ignore */ }
  }

  // 策略配置
  const strategiesStr = localStorage.getItem('strategies')
  if (strategiesStr) {
    try {
      data.strategies = JSON.parse(strategiesStr)
    } catch { /* ignore */ }
  }

  // 设置
  data.settings = {}
  const settingsKeys = ['theme', 'locale', 'preferences']
  settingsKeys.forEach((key) => {
    const value = localStorage.getItem(key)
    if (value) {
      try {
        data.settings![key] = JSON.parse(value)
      } catch {
        data.settings![key] = value
      }
    }
  })

  await exportToJson(data, 'lianghua-backup')
}

// 批量导入用户数据
export async function importAllUserData(data: ExportData['data']): Promise<{
  success: boolean
  imported: string[]
  errors: string[]
}> {
  const result = { success: true, imported: [] as string[], errors: [] as string[] }

  try {
    if (data.watchlist) {
      localStorage.setItem('watchlist', JSON.stringify(data.watchlist))
      result.imported.push('自选股')
    }

    if (data.alerts) {
      localStorage.setItem('alerts', JSON.stringify(data.alerts))
      result.imported.push('预警配置')
    }

    if (data.strategies) {
      localStorage.setItem('strategies', JSON.stringify(data.strategies))
      result.imported.push('策略配置')
    }

    if (data.settings) {
      Object.entries(data.settings).forEach(([key, value]) => {
        localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value))
      })
      result.imported.push('系统设置')
    }
  } catch (error) {
    result.success = false
    result.errors.push(String(error))
  }

  return result
}

export default {
  exportToJson,
  exportToCsv,
  exportToExcel,
  importFromJson,
  importFromCsv,
  validateImportData,
  exportAllUserData,
  importAllUserData,
}
