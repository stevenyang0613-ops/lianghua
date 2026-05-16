/**
 * 数据导出工具
 * 支持 Excel、CSV、PDF 多格式导出，大数据分片导出
 */

interface ExportOptions {
  filename: string
  sheetName?: string
  headers?: string[]
  formatters?: Record<string, (value: unknown) => string>
  chunkSize?: number
  onProgress?: (progress: number) => void
}

type ExportFormat = 'csv' | 'excel' | 'pdf' | 'json'

/**
 * 导出为 CSV
 */
export async function exportToCSV<T extends Record<string, unknown>>(
  data: T[],
  options: ExportOptions
): Promise<void> {
  const { filename, headers, formatters, chunkSize = 10000, onProgress } = options

  // 获取列名
  const columns = headers || (data.length > 0 ? Object.keys(data[0]) : [])

  // 分片处理大数据
  const chunks = chunkArray(data, chunkSize)
  let csvContent = ''

  // 添加表头
  csvContent += columns.map(escapeCSV).join(',') + '\n'

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i]

    for (const row of chunk) {
      const values = columns.map(col => {
        let value = row[col]
        if (formatters && formatters[col]) {
          value = formatters[col](value)
        }
        return escapeCSV(formatValue(value))
      })
      csvContent += values.join(',') + '\n'
    }

    // 报告进度
    if (onProgress) {
      onProgress((i + 1) / chunks.length * 100)
    }

    // 让出主线程
    await sleep(0)
  }

  // 下载文件
  downloadFile(csvContent, `${filename}.csv`, 'text/csv;charset=utf-8')
}

/**
 * 导出为 Excel（简化版，使用 HTML 表格格式）
 */
export async function exportToExcel<T extends Record<string, unknown>>(
  data: T[],
  options: ExportOptions
): Promise<void> {
  const { filename, sheetName: _sheetName = 'Sheet1', headers, formatters, chunkSize = 10000, onProgress } = options

  // 获取列名
  const columns = headers || (data.length > 0 ? Object.keys(data[0]) : [])

  // 构建 HTML 表格
  let html = `<html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:x="urn:schemas-microsoft-com:office:excel">
<head>
  <meta charset="UTF-8">
  <style>
    table { border-collapse: collapse; }
    th, td { border: 1px solid #ddd; padding: 8px; }
    th { background: #f5f5f5; font-weight: bold; }
  </style>
</head>
<body>
<table>`

  // 添加表头
  html += '<tr>' + columns.map(col => `<th>${escapeHtml(col)}</th>`).join('') + '</tr>'

  // 分片处理
  const chunks = chunkArray(data, chunkSize)

  for (let i = 0; i < chunks.length; i++) {
    const chunk = chunks[i]

    for (const row of chunk) {
      html += '<tr>'
      for (const col of columns) {
        let value = row[col]
        if (formatters && formatters[col]) {
          value = formatters[col](value)
        }
        html += `<td>${escapeHtml(formatValue(value))}</td>`
      }
      html += '</tr>'
    }

    if (onProgress) {
      onProgress((i + 1) / chunks.length * 100)
    }

    await sleep(0)
  }

  html += '</table></body></html>'

  // 下载文件
  downloadFile(html, `${filename}.xls`, 'application/vnd.ms-excel')
}

/**
 * 导出为 PDF（简化版，使用打印功能）
 */
export async function exportToPDF<T extends Record<string, unknown>>(
  data: T[],
  options: ExportOptions
): Promise<void> {
  const { filename, headers, formatters, onProgress } = options

  // 获取列名
  const columns = headers || (data.length > 0 ? Object.keys(data[0]) : [])

  // 创建打印窗口
  const printWindow = window.open('', '_blank')
  if (!printWindow) {
    throw new Error('无法打开打印窗口')
  }

  // 构建 HTML
  let html = `
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>${filename}</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 20px; }
    h1 { text-align: center; margin-bottom: 20px; }
    table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
    th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
    th { background: #f5f5f5; font-weight: bold; }
    tr:nth-child(even) { background: #fafafa; }
    .footer { text-align: center; font-size: 12px; color: #666; }
    @media print {
      .no-print { display: none; }
    }
  </style>
</head>
<body>
  <h1>${escapeHtml(filename)}</h1>
  <table>
    <thead>
      <tr>${columns.map(col => `<th>${escapeHtml(col)}</th>`).join('')}</tr>
    </thead>
    <tbody>
`

  for (let i = 0; i < data.length; i++) {
    const row = data[i]
    html += '<tr>'
    for (const col of columns) {
      let value = row[col]
      if (formatters && formatters[col]) {
        value = formatters[col](value)
      }
      html += `<td>${escapeHtml(formatValue(value))}</td>`
    }
    html += '</tr>'

    if (onProgress && i % 100 === 0) {
      onProgress(i / data.length * 100)
    }
  }

  html += `
    </tbody>
  </table>
  <div class="footer">
    生成时间: ${new Date().toLocaleString()} | 共 ${data.length} 条记录
  </div>
  <div class="no-print" style="text-align: center; margin-top: 20px;">
    <button onclick="window.print()">打印</button>
    <button onclick="window.close()">关闭</button>
  </div>
</body>
</html>
`

  printWindow.document.write(html)
  printWindow.document.close()

  if (onProgress) {
    onProgress(100)
  }
}

/**
 * 导出为 JSON
 */
export async function exportToJSON<T extends Record<string, unknown>>(
  data: T[],
  options: ExportOptions
): Promise<void> {
  const { filename, formatters, onProgress } = options

  let processedData = data

  if (formatters) {
    processedData = data.map(row => {
      const newRow: Record<string, unknown> = {}
      for (const [key, value] of Object.entries(row)) {
        if (formatters[key]) {
          newRow[key] = formatters[key](value)
        } else {
          newRow[key] = value
        }
      }
      return newRow as T
    })
  }

  const jsonContent = JSON.stringify(processedData, null, 2)

  if (onProgress) {
    onProgress(100)
  }

  downloadFile(jsonContent, `${filename}.json`, 'application/json')
}

/**
 * 通用导出函数
 */
export async function exportData<T extends Record<string, unknown>>(
  data: T[],
  format: ExportFormat,
  options: ExportOptions
): Promise<void> {
  switch (format) {
    case 'csv':
      return exportToCSV(data, options)
    case 'excel':
      return exportToExcel(data, options)
    case 'pdf':
      return exportToPDF(data, options)
    case 'json':
      return exportToJSON(data, options)
    default:
      throw new Error(`Unsupported format: ${format}`)
  }
}

/**
 * 分片数组
 */
function chunkArray<T>(array: T[], size: number): T[][] {
  const chunks: T[][] = []
  for (let i = 0; i < array.length; i += size) {
    chunks.push(array.slice(i, i + size))
  }
  return chunks
}

/**
 * 睡眠函数
 */
function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

/**
 * 转义 CSV 值
 */
function escapeCSV(value: string): string {
  if (value.includes(',') || value.includes('"') || value.includes('\n')) {
    return `"${value.replace(/"/g, '""')}"`
  }
  return value
}

/**
 * 转义 HTML
 */
function escapeHtml(value: string): string {
  const map: Record<string, string> = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;',
  }
  return value.replace(/[&<>"']/g, c => map[c])
}

/**
 * 格式化值
 */
function formatValue(value: unknown): string {
  if (value === null || value === undefined) {
    return ''
  }
  if (typeof value === 'object') {
    return JSON.stringify(value)
  }
  return String(value)
}

/**
 * 下载文件
 */
function downloadFile(content: string, filename: string, mimeType: string): void {
  const blob = new Blob(['﻿' + content], { type: mimeType })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

/**
 * 流式导出（大数据集）
 */
export class StreamingExporter<T extends Record<string, unknown>> {
  private data: T[] = []
  private options: ExportOptions
  private format: ExportFormat

  constructor(format: ExportFormat, options: ExportOptions) {
    this.format = format
    this.options = options
  }

  addChunk(chunk: T[]): void {
    this.data.push(...chunk)
  }

  async export(): Promise<void> {
    await exportData(this.data, this.format, this.options)
    this.data = []
  }

  getDataLength(): number {
    return this.data.length
  }
}

export default {
  exportToCSV,
  exportToExcel,
  exportToPDF,
  exportToJSON,
  exportData,
  StreamingExporter,
}
