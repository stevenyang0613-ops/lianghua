import type { ConvertibleQuote } from '../types'

export function exportToCSV(bonds: ConvertibleQuote[], filename: string = 'bonds'): void {
  const headers = [
    '代码', '名称', '最新价', '涨跌幅(%)', '正股价', '正股涨跌幅(%)',
    '转股价', '转股价值', '溢价率(%)', '双低值', 'YTM(%)', '成交额(亿)', '剩余年限'
  ]

  const rows = bonds.map((b) => [
    b.code,
    b.name,
    b.price.toFixed(2),
    b.change_pct.toFixed(2),
    b.stock_price.toFixed(2),
    b.stock_change_pct.toFixed(2),
    b.conversion_price.toFixed(2),
    b.conversion_value.toFixed(2),
    b.premium_ratio.toFixed(2),
    b.dual_low.toFixed(2),
    b.ytm.toFixed(2),
    b.volume.toFixed(2),
    b.remaining_years.toFixed(1),
  ])

  const csvContent = [
    headers.join(','),
    ...rows.map((r) => r.map((cell) => `"${cell}"`).join(',')),
  ].join('\n')

  const BOM = '﻿'
  const blob = new Blob([BOM + csvContent], { type: 'text/csv;charset=utf-8;' })
  downloadBlob(blob, `${filename}.csv`)
}

export function exportToExcel(bonds: ConvertibleQuote[], filename: string = 'bonds'): void {
  const headers = [
    '代码', '名称', '最新价', '涨跌幅(%)', '正股价', '正股涨跌幅(%)',
    '转股价', '转股价值', '溢价率(%)', '双低值', 'YTM(%)', '成交额(亿)', '剩余年限'
  ]

  const rows = bonds.map((b) => [
    b.code,
    b.name,
    b.price.toFixed(2),
    b.change_pct.toFixed(2),
    b.stock_price.toFixed(2),
    b.stock_change_pct.toFixed(2),
    b.conversion_price.toFixed(2),
    b.conversion_value.toFixed(2),
    b.premium_ratio.toFixed(2),
    b.dual_low.toFixed(2),
    b.ytm.toFixed(2),
    b.volume.toFixed(2),
    b.remaining_years.toFixed(1),
  ])

  let xmlContent = `<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Worksheet ss:Name="可转债行情">
<Table>
<Row>${headers.map((h) => `<Cell><Data ss:Type="String">${h}</Data></Cell>`).join('')}</Row>
${rows.map((row) => `<Row>${row.map((cell, i) => {
  const type = i === 0 || i === 1 ? 'String' : 'Number'
  return `<Cell><Data ss:Type="${type}">${cell}</Data></Cell>`
}).join('')}</Row>`).join('\n')}
</Table>
</Worksheet>
</Workbook>`

  const blob = new Blob([xmlContent], { type: 'application/vnd.ms-excel;charset=utf-8;' })
  downloadBlob(blob, `${filename}.xls`)
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

export function formatDateForFilename(): string {
  const now = new Date()
  return `${now.getFullYear()}${String(now.getMonth() + 1).padStart(2, '0')}${String(now.getDate()).padStart(2, '0')}`
}
