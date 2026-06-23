import { memo, useMemo } from 'react'
import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ConvertibleQuote } from '../types'
import { fmt } from '../utils/format'

interface MarketTableProps {
  bonds: ConvertibleQuote[]
  loading: boolean
  onRowClick: (code: string) => void
  extraColumns?: ColumnsType<ConvertibleQuote>
}

/** 数字单元格统一样式: 等宽字体 + 加粗 + 13px + 着色 */
function numCell(value: string, color?: string) {
  return (
    <span
      style={{
        color,
        fontWeight: 600,
        fontFamily: 'SF Mono, Monaco, Consolas, monospace',
        fontSize: 13,
      }}
    >
      {value}
    </span>
  )
}

/** 可选列定义 — 供用户自定义显示 */
export const EXTENDED_COLUMNS: ColumnsType<ConvertibleQuote> = [
  {
    title: 'PE', dataIndex: 'pe', key: 'pe', width: 80,
    sorter: (a, b) => (a.pe ?? -Infinity) - (b.pe ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v < 0 ? '#cf1322' : v > 50 ? '#faad14' : undefined
      return numCell(fmt(v), color)
    },
  },
  {
    title: 'PB', dataIndex: 'pb', key: 'pb', width: 80,
    sorter: (a, b) => (a.pb ?? -Infinity) - (b.pb ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v < 0 ? '#cf1322' : v > 5 ? '#faad14' : undefined
      return numCell(fmt(v), color)
    },
  },
  {
    title: 'ROE', dataIndex: 'roe', key: 'roe', width: 80,
    sorter: (a, b) => (a.roe ?? -Infinity) - (b.roe ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 15 ? '#52c41a' : v > 8 ? undefined : '#cf1322'
      return numCell(`${fmt(v)}%`, color)
    },
  },
  {
    title: '换手率', dataIndex: 'turnover_rate', key: 'turnover_rate', width: 90,
    sorter: (a, b) => (a.turnover_rate ?? -Infinity) - (b.turnover_rate ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 10 ? '#cf1322' : v > 5 ? '#faad14' : undefined
      return numCell(`${fmt(v)}%`, color)
    },
  },
  {
    title: '新闻情绪', dataIndex: 'sentiment_score', key: 'sentiment_score', width: 90,
    sorter: (a, b) => (a.sentiment_score ?? -Infinity) - (b.sentiment_score ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 0.3 ? '#52c41a' : v < -0.3 ? '#cf1322' : undefined
      const label = v > 0.3 ? '正面' : v < -0.3 ? '负面' : '中性'
      return <Tag color={color} style={{ fontSize: 12 }}>{label} {fmt(v)}</Tag>
    },
  },
  {
    title: '北向(亿)', dataIndex: 'north_net', key: 'north_net', width: 90,
    sorter: (a, b) => (a.north_net ?? -Infinity) - (b.north_net ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 0 ? '#cf1322' : v < 0 ? '#389e0d' : undefined
      return numCell(`${v > 0 ? '+' : ''}${fmt(v)}`, color)
    },
  },
  {
    title: '行业', dataIndex: 'industry', key: 'industry', width: 120,
    sorter: (a, b) => String(a.industry ?? '').localeCompare(String(b.industry ?? '')),
    render: (v: string | null) => {
      if (!v) return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
      return <Tag style={{ fontSize: 12 }}>{v}</Tag>
    },
  },
  {
    title: '概念', dataIndex: 'concepts', key: 'concepts', width: 140,
    render: (v: string[] | null) => {
      if (!v || v.length === 0) return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
      return <span style={{ fontSize: 12 }}>{v.slice(0, 3).join(', ')}{v.length > 3 ? '...' : ''}</span>
    },
  },
  {
    title: '剩余规模', dataIndex: 'outstanding_scale', key: 'outstanding_scale', width: 90,
    sorter: (a, b) => (a.outstanding_scale ?? -Infinity) - (b.outstanding_scale ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v < 3 ? '#52c41a' : v > 20 ? '#faad14' : undefined
      return numCell(`${fmt(v)}亿`, color)
    },
  },
  {
    title: '质押率', dataIndex: 'pledge_ratio', key: 'pledge_ratio', width: 80,
    sorter: (a, b) => (a.pledge_ratio ?? -Infinity) - (b.pledge_ratio ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 50 ? '#cf1322' : v > 30 ? '#faad14' : undefined
      return numCell(`${fmt(v)}%`, color)
    },
  },
  {
    title: '历史波动率', dataIndex: 'hv', key: 'hv', width: 90,
    sorter: (a, b) => (a.hv ?? -Infinity) - (b.hv ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      return numCell(`${fmt(v)}%`)
    },
  },
  {
    title: '纯债溢价率', dataIndex: 'pure_bond_premium_ratio', key: 'pure_bond_premium_ratio', width: 100,
    sorter: (a, b) => (a.pure_bond_premium_ratio ?? -Infinity) - (b.pure_bond_premium_ratio ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v < 0 ? '#52c41a' : v > 30 ? '#cf1322' : undefined
      return numCell(`${fmt(v)}%`, color)
    },
  },
  {
    title: '评级', dataIndex: 'rating', key: 'rating', width: 80,
    sorter: (a, b) => String(a.rating ?? '').localeCompare(String(b.rating ?? '')),
    render: (v: string | null) => {
      if (!v) return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
      const color = v.startsWith('AAA') ? '#52c41a' : v.startsWith('AA') ? '#1677ff' : v.startsWith('A') ? '#faad14' : undefined
      return <Tag color={color} style={{ fontSize: 12 }}>{v}</Tag>
    },
  },
  {
    title: '营收增速', dataIndex: 'revenue_yoy', key: 'revenue_yoy', width: 90,
    sorter: (a, b) => (a.revenue_yoy ?? -Infinity) - (b.revenue_yoy ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 0 ? '#cf1322' : v < 0 ? '#389e0d' : undefined
      return numCell(`${v > 0 ? '+' : ''}${fmt(v)}%`, color)
    },
  },
  {
    title: '利润增速', dataIndex: 'profit_yoy', key: 'profit_yoy', width: 90,
    sorter: (a, b) => (a.profit_yoy ?? -Infinity) - (b.profit_yoy ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 0 ? '#cf1322' : v < 0 ? '#389e0d' : undefined
      return numCell(`${v > 0 ? '+' : ''}${fmt(v)}%`, color)
    },
  },
]

const columns: ColumnsType<ConvertibleQuote> = [
  { title: '代码', dataIndex: 'code', key: 'code', width: 110, fixed: 'left', sorter: (a, b) => String(a.code ?? '').localeCompare(String(b.code ?? '')) },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100, fixed: 'left', sorter: (a, b) => String(a.name ?? '').localeCompare(String(b.name ?? '')) },
  {
    title: '最新价', dataIndex: 'price', key: 'price', width: 100,
    sorter: (a, b) => (a.price ?? -Infinity) - (b.price ?? -Infinity),
    render: (v: number | null, r) => {
      const change = r.change_pct
      const color = change !== null && change !== undefined ? (change > 0 ? '#cf1322' : change < 0 ? '#389e0d' : undefined) : undefined
      return numCell(fmt(v), color)
    },
  },
  {
    title: '涨跌幅', dataIndex: 'change_pct', key: 'change_pct', width: 100,
    sorter: (a, b) => (a.change_pct ?? -Infinity) - (b.change_pct ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v > 0 ? '#cf1322' : v < 0 ? '#389e0d' : undefined
      return numCell(`${v > 0 ? '+' : ''}${fmt(v)}%`, color)
    },
  },
  {
    title: '正股价', dataIndex: 'stock_price', key: 'stock_price', width: 90,
    sorter: (a, b) => (a.stock_price ?? -Infinity) - (b.stock_price ?? -Infinity),
    render: (v: number | null) => numCell(fmt(v)),
  },
  {
    title: '转股价', dataIndex: 'conversion_price', key: 'conversion_price', width: 90,
    sorter: (a, b) => (a.conversion_price ?? -Infinity) - (b.conversion_price ?? -Infinity),
    render: (v: number | null) => numCell(fmt(v)),
  },
  {
    title: '转股价值', dataIndex: 'conversion_value', key: 'conversion_value', width: 100,
    sorter: (a, b) => (a.conversion_value ?? -Infinity) - (b.conversion_value ?? -Infinity),
    render: (v: number | null) => numCell(fmt(v)),
  },
  {
    title: '溢价率', dataIndex: 'premium_ratio', key: 'premium_ratio', width: 100,
    sorter: (a, b) => (a.premium_ratio ?? -Infinity) - (b.premium_ratio ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v < 0 ? '#cf1322' : v > 50 ? '#389e0d' : undefined
      return numCell(`${fmt(v)}%`, color)
    },
  },
  {
    title: '双低值', dataIndex: 'dual_low', key: 'dual_low', width: 100,
    sorter: (a, b) => (a.dual_low ?? -Infinity) - (b.dual_low ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      const color = v < 130 ? '#52c41a' : v > 180 ? '#faad14' : undefined
      return numCell(fmt(v), color)
    },
  },
  {
    title: '成交额(亿)', dataIndex: 'volume', key: 'volume', width: 110,
    sorter: (a, b) => (a.volume ?? -Infinity) - (b.volume ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      return v > 0 ? numCell(fmt(v)) : <span style={{ color: '#bbb', fontSize: 13 }}>休市</span>
    },
  },
  {
    title: '剩余年限', dataIndex: 'remaining_years', key: 'remaining_years', width: 100,
    sorter: (a, b) => (a.remaining_years ?? -Infinity) - (b.remaining_years ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined) return numCell('-')
      return v > 0 ? numCell(fmt(v, 1)) : <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
    },
  },
  {
    title: '强赎', dataIndex: 'forced_call_days', key: 'forced_call_days', width: 70,
    sorter: (a, b) => (a.forced_call_days ?? -Infinity) - (b.forced_call_days ?? -Infinity),
    render: (v: number | null) => {
      if (v === null || v === undefined || v <= 0) return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
      const color = v >= 10 ? '#ff4d4f' : v >= 5 ? '#faad14' : '#1677ff'
      return numCell(`${v}/15`, color)
    },
  },
  {
    title: '强赎状态', dataIndex: 'call_status', key: 'call_status', width: 90,
    sorter: (a, b) => String(a.call_status ?? '').localeCompare(String(b.call_status ?? '')),
    render: (v: string, r) => {
      if (r.is_called) return <Tag color="red" style={{ fontSize: 12 }}>已公告强赎</Tag>
      if (v) return <Tag color="orange" style={{ fontSize: 12 }}>{v}</Tag>
      return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
    },
  },
]

function MarketTable({ bonds, loading, onRowClick, extraColumns = [] }: MarketTableProps) {
  const mergedColumns = useMemo(() => [...columns, ...extraColumns], [extraColumns])

  return (
    <Table<ConvertibleQuote>
      columns={mergedColumns}
      dataSource={bonds}
      rowKey="code"
      loading={loading}
      size="small"
      scroll={{ x: 1300 + extraColumns.length * 80, y: 'calc(100vh - 160px)' }}
      pagination={false}
      onRow={(record) => ({ onClick: () => onRowClick(record.code), style: { cursor: 'pointer' } })}
      locale={{ emptyText: '暂无数据' }}
    />
  )
}

export default memo(MarketTable)
