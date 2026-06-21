/**
 * 报告生成器
 * 支持 Excel 和 PDF 报告导出
 */

import { safeJsonParse } from './safeJson'

export interface ReportConfig {
  title: string
  type: 'trade' | 'performance' | 'position' | 'signal' | 'backtest' | 'custom'
  dateRange?: [string, string]
  includeCharts: boolean
  format: 'excel' | 'pdf' | 'csv'
  data: Record<string, unknown>[]
}

export interface GeneratedReport {
  id: string
  title: string
  type: ReportConfig['type']
  format: ReportConfig['format']
  createdAt: number
  size: string
  downloadUrl: string
}

const REPORTS_KEY = 'generated_reports'

// 生成唯一ID
function generateId(): string {
  return `report_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`
}

// 格式化文件大小
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// 生成 CSV 内容
function generateCSV(data: Record<string, unknown>[], headers: string[]): string {
  const rows = [headers.join(',')]

  data.forEach((item) => {
    const row = headers.map((h) => {
      const value = item[h]
      if (value === null || value === undefined) return ''
      if (typeof value === 'string' && value.includes(',')) {
        return `"${value}"`
      }
      return String(value)
    })
    rows.push(row.join(','))
  })

  return rows.join('\n')
}

// 生成 Excel (简化版，实际需要使用 xlsx 库)
function generateExcel(data: Record<string, unknown>[], title: string): string {
  const headers = Object.keys(data[0] || {})
  const titleRow = `# ${title}\n`
  return titleRow + generateCSV(data, headers)
}

// 生成 PDF 内容 (简化版，实际需要使用 jspdf 库)
function generatePDFContent(config: ReportConfig): string {
  const lines: string[] = []

  lines.push(`# ${config.title}`)
  lines.push('')
  lines.push(`生成时间: ${new Date().toLocaleString('zh-CN')}`)
  lines.push(`报告类型: ${config.type}`)
  lines.push('')

  if (config.data.length > 0) {
    lines.push('## 数据统计')
    lines.push(`总记录数: ${config.data.length}`)
    lines.push('')
    lines.push('## 数据预览 (前10条)')
    config.data.slice(0, 10).forEach((item, i) => {
      lines.push(`${i + 1}. ${JSON.stringify(item)}`)
    })
  }

  return lines.join('\n')
}

// 生成报告
export function generateReport(config: ReportConfig): GeneratedReport {
  const id = generateId()
  let content: string
  let mimeType: string

  switch (config.format) {
    case 'csv': {
      const headers = Object.keys(config.data[0] || {})
      content = generateCSV(config.data, headers)
      mimeType = 'text/csv'
      break
    }
    case 'excel': {
      content = generateExcel(config.data, config.title)
      mimeType = 'application/vnd.ms-excel'
      break
    }
    case 'pdf': {
      content = generatePDFContent(config)
      mimeType = 'text/plain' // 实际应为 application/pdf
      break
    }
    default:
      throw new Error('Unsupported format')
  }

  const blob = new Blob([content], { type: mimeType })
  const downloadUrl = URL.createObjectURL(blob)

  const report: GeneratedReport = {
    id,
    title: config.title,
    type: config.type,
    format: config.format,
    createdAt: Date.now(),
    size: formatSize(blob.size),
    downloadUrl,
  }

  // 保存报告记录
  const reports = getReports()
  reports.push(report)
  localStorage.setItem(REPORTS_KEY, JSON.stringify(reports))

  return report
}

// 获取所有报告
export function getReports(): GeneratedReport[] {
  const saved = localStorage.getItem(REPORTS_KEY)
  const reports = safeJsonParse<GeneratedReport[]>(saved, [])
  if (reports.length === 0) {
    // Seed a sample report on first use so the UI is never empty
    const sample: GeneratedReport = {
      id: 'report_sample_1',
      title: '示例报告：可转债市场概览',
      type: 'custom',
      format: 'csv',
      createdAt: Date.now() - 86400000,
      size: '2.1 KB',
      downloadUrl: '',
    }
    localStorage.setItem(REPORTS_KEY, JSON.stringify([sample]))
    return [sample]
  }
  return reports
}

// 删除报告
export function deleteReport(id: string): boolean {
  const reports = getReports()
  const report = reports.find((r) => r.id === id)

  if (report) {
    URL.revokeObjectURL(report.downloadUrl)
  }

  const filtered = reports.filter((r) => r.id !== id)
  localStorage.setItem(REPORTS_KEY, JSON.stringify(filtered))

  return true
}

// 清除所有报告
export function clearReports(): void {
  const reports = getReports()
  reports.forEach((r) => URL.revokeObjectURL(r.downloadUrl))
  localStorage.removeItem(REPORTS_KEY)
}

// 下载报告
export function downloadReport(report: GeneratedReport): void {
  const a = document.createElement('a')
  a.href = report.downloadUrl
  a.download = `${report.title}-${new Date(report.createdAt).toISOString().slice(0, 10)}.${report.format === 'excel' ? 'xls' : report.format}`
  a.click()
}

// 快速生成交易报告
export function generateTradeReport(trades: Record<string, unknown>[]): GeneratedReport {
  return generateReport({
    title: '交易报告',
    type: 'trade',
    data: trades,
    includeCharts: false,
    format: 'excel',
  })
}

// 快速生成绩效报告
export function generatePerformanceReport(metrics: Record<string, unknown>[]): GeneratedReport {
  return generateReport({
    title: '绩效报告',
    type: 'performance',
    data: metrics,
    includeCharts: true,
    format: 'excel',
  })
}

// 快速生成持仓报告
export function generatePositionReport(positions: Record<string, unknown>[]): GeneratedReport {
  return generateReport({
    title: '持仓报告',
    type: 'position',
    data: positions,
    includeCharts: false,
    format: 'excel',
  })
}

// 快速生成信号报告
export function generateSignalReport(signals: Record<string, unknown>[]): GeneratedReport {
  return generateReport({
    title: '信号报告',
    type: 'signal',
    data: signals,
    includeCharts: false,
    format: 'csv',
  })
}

// 报告类型选项
export const REPORT_TYPE_OPTIONS = [
  { value: 'trade', label: '交易报告' },
  { value: 'performance', label: '绩效报告' },
  { value: 'position', label: '持仓报告' },
  { value: 'signal', label: '信号报告' },
  { value: 'backtest', label: '回测报告' },
  { value: 'custom', label: '自定义报告' },
]

// 报告格式选项
export const REPORT_FORMAT_OPTIONS = [
  { value: 'excel', label: 'Excel (.xls)' },
  { value: 'csv', label: 'CSV (.csv)' },
  { value: 'pdf', label: 'PDF (.pdf)' },
]

export default {
  generateReport,
  getReports,
  deleteReport,
  clearReports,
  downloadReport,
  generateTradeReport,
  generatePerformanceReport,
  generatePositionReport,
  generateSignalReport,
  REPORT_TYPE_OPTIONS,
  REPORT_FORMAT_OPTIONS,
}
