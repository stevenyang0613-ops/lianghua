import type { ConvertibleQuote } from '../types'

function escapeXml(str: string): string {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

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

  const xmlContent = `<?xml version="1.0" encoding="UTF-8"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">
<Worksheet ss:Name="可转债行情">
<Table>
<Row>${headers.map((h) => `<Cell><Data ss:Type="String">${escapeXml(h)}</Data></Cell>`).join('')}</Row>
${rows.map((row) => `<Row>${row.map((cell, i) => {
  const type = i === 0 || i === 1 ? 'String' : 'Number'
  return `<Cell><Data ss:Type="${type}">${escapeXml(cell)}</Data></Cell>`
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

// Trade export functions
export function exportTrades(trades: any[], filename: string = 'trades'): void {
  const headers = ['时间', '代码', '名称', '方向', '价格', '数量', '金额', '状态']

  const rows = trades.map((t) => [
    new Date(t.created_at).toLocaleString(),
    t.code,
    t.name,
    t.side === 'buy' ? '买入' : '卖出',
    t.price.toFixed(2),
    t.volume,
    (t.price * t.volume).toFixed(2),
    t.status === 'filled' ? '已成交' : t.status === 'pending' ? '待成交' : '已撤单',
  ])

  const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
  const blob = new Blob(['﻿' + csvContent], { type: 'text/csv;charset=utf-8;' })
  downloadBlob(blob, `${filename}_${formatDateForFilename()}.csv`)
}

// Position export function
export function exportPositions(positions: any[], filename: string = 'positions'): void {
  const headers = ['代码', '名称', '持仓数量', '成本价', '当前价', '市值', '盈亏', '盈亏率(%)']

  const rows = positions.map((p) => [
    p.code,
    p.name,
    p.volume,
    p.avg_cost?.toFixed(2) || '0',
    p.current_price?.toFixed(2) || '0',
    p.market_value?.toFixed(2) || '0',
    p.pnl?.toFixed(2) || '0',
    ((p.pnl_rate || 0) * 100).toFixed(2),
  ])

  const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
  const blob = new Blob(['﻿' + csvContent], { type: 'text/csv;charset=utf-8;' })
  downloadBlob(blob, `${filename}_${formatDateForFilename()}.csv`)
}

// Backtest result export
export function exportBacktestResult(result: any, filename: string = 'backtest'): void {
  const summary = {
    策略名称: result.strategy,
    回测区间: `${result.start_date} 至 ${result.end_date}`,
    初始资金: result.initial_capital,
    最终资金: result.final_capital,
    总收益率: `${(result.total_return * 100).toFixed(2)}%`,
    年化收益率: `${(result.annualized_return * 100).toFixed(2)}%`,
    夏普比率: result.sharpe_ratio?.toFixed(2),
    最大回撤: `${((result.max_drawdown || 0) * 100).toFixed(2)}%`,
    交易次数: result.trade_count,
    胜率: `${((result.win_rate || 0) * 100).toFixed(2)}%`,
    生成时间: new Date().toLocaleString(),
  }

  const jsonContent = JSON.stringify({ summary, ...result }, null, 2)
  const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8;' })
  downloadBlob(blob, `${filename}_${result.strategy}_${formatDateForFilename()}.json`)
}

// Signals export
export function exportSignals(signals: any[], filename: string = 'signals'): void {
  const headers = ['时间', '代码', '名称', '策略', '信号类型', '价格', '置信度(%)', '说明']

  const rows = signals.map((s) => [
    new Date(s.created_at).toLocaleString(),
    s.code,
    s.name,
    s.strategy,
    s.signal_type,
    s.price?.toFixed(2) || '',
    ((s.confidence || 0) * 100).toFixed(1),
    s.description || '',
  ])

  const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
  const blob = new Blob(['﻿' + csvContent], { type: 'text/csv;charset=utf-8;' })
  downloadBlob(blob, `${filename}_${formatDateForFilename()}.csv`)
}

// Fund curve export
export function exportFundCurve(points: any[], filename: string = 'fund_curve'): void {
  const headers = ['日期', '净值', '累计收益率(%)']

  const rows = points.map((p) => [p.date, p.nav, ((p.total_return || 0) * 100).toFixed(2)])

  const csvContent = [headers.join(','), ...rows.map((r) => r.join(','))].join('\n')
  const blob = new Blob(['﻿' + csvContent], { type: 'text/csv;charset=utf-8;' })
  downloadBlob(blob, `${filename}_${formatDateForFilename()}.csv`)
}

// Account report export
export function exportAccountReport(
  account: any,
  positions: any[],
  orders: any[],
  filename: string = 'account_report'
): void {
  const report = `
========================================
LiangHua 交易报告
生成时间: ${new Date().toLocaleString()}
========================================

账户概览:
  总资产: ¥${account?.total_value?.toFixed(2) || '0.00'}
  现金: ¥${account?.cash?.toFixed(2) || '0.00'}
  持仓市值: ¥${((account?.total_value || 0) - (account?.cash || 0)).toFixed(2)}
  累计盈亏: ¥${account?.pnl?.toFixed(2) || '0.00'}

持仓详情:
  持仓数量: ${positions.length} 只
${positions
  .map(
    (p) =>
      `  - ${p.name}(${p.code}): ${p.volume}股, 盈亏¥${p.pnl?.toFixed(2) || '0.00'}`
  )
  .join('\n')}

交易记录:
  已成交: ${orders.filter((o) => o.status === 'filled').length} 笔
  待成交: ${orders.filter((o) => o.status === 'pending').length} 笔
  已撤单: ${orders.filter((o) => o.status === 'cancelled').length} 笔

========================================
`.trim()

  const blob = new Blob([report], { type: 'text/plain;charset=utf-8;' })
  downloadBlob(blob, `${filename}_${formatDateForFilename()}.txt`)
}
