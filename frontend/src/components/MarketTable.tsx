import { memo } from 'react'
import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ConvertibleQuote } from '../types'
import { fmt } from '../utils/format'

interface MarketTableProps {
  bonds: ConvertibleQuote[]
  loading: boolean
  onRowClick: (code: string) => void
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

const columns: ColumnsType<ConvertibleQuote> = [
  { title: '代码', dataIndex: 'code', key: 'code', width: 110, fixed: 'left', sorter: (a, b) => String(a.code ?? '').localeCompare(String(b.code ?? '')) },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100, fixed: 'left', sorter: (a, b) => String(a.name ?? '').localeCompare(String(b.name ?? '')) },
  {
    title: '最新价', dataIndex: 'price', key: 'price', width: 100,
    sorter: (a, b) => (a.price ?? 0) - (b.price ?? 0),
    render: (v: number, r) => {
      const change = r.change_pct ?? 0
      const color = change > 0 ? '#cf1322' : change < 0 ? '#389e0d' : undefined
      return numCell(fmt(v), color)
    },
  },
  {
    title: '涨跌幅', dataIndex: 'change_pct', key: 'change_pct', width: 100,
    sorter: (a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0),
    render: (v: number) => {
      const n = v ?? 0
      const color = n > 0 ? '#cf1322' : n < 0 ? '#389e0d' : undefined
      return numCell(`${n > 0 ? '+' : ''}${fmt(n)}%`, color)
    },
  },
  {
    title: '正股价', dataIndex: 'stock_price', key: 'stock_price', width: 90,
    sorter: (a, b) => (a.stock_price ?? 0) - (b.stock_price ?? 0),
    render: (v: number) => numCell(fmt(v)),
  },
  {
    title: '转股价', dataIndex: 'conversion_price', key: 'conversion_price', width: 90,
    sorter: (a, b) => (a.conversion_price ?? 0) - (b.conversion_price ?? 0),
    render: (v: number) => numCell(fmt(v)),
  },
  {
    title: '转股价值', dataIndex: 'conversion_value', key: 'conversion_value', width: 100,
    sorter: (a, b) => (a.conversion_value ?? 0) - (b.conversion_value ?? 0),
    render: (v: number) => numCell(fmt(v)),
  },
  {
    title: '溢价率', dataIndex: 'premium_ratio', key: 'premium_ratio', width: 100,
    sorter: (a, b) => (a.premium_ratio ?? 0) - (b.premium_ratio ?? 0),
    render: (v: number) => {
      const n = v ?? 0
      const color = n < 0 ? '#cf1322' : n > 50 ? '#389e0d' : undefined
      return numCell(`${fmt(n)}%`, color)
    },
  },
  {
    title: '双低值', dataIndex: 'dual_low', key: 'dual_low', width: 100,
    sorter: (a, b) => (a.dual_low ?? 0) - (b.dual_low ?? 0),
    render: (v: number) => {
      const n = v ?? 0
      const color = n < 130 ? '#52c41a' : n > 180 ? '#faad14' : undefined
      return numCell(fmt(n), color)
    },
  },
  {
    title: '成交额(亿)', dataIndex: 'volume', key: 'volume', width: 110,
    sorter: (a, b) => (a.volume ?? 0) - (b.volume ?? 0),
    render: (v: number) => v > 0
      ? numCell(fmt(v))
      : <span style={{ color: '#bbb', fontSize: 13 }}>休市</span>,
  },
  {
    title: '剩余年限', dataIndex: 'remaining_years', key: 'remaining_years', width: 100,
    sorter: (a, b) => (a.remaining_years ?? 0) - (b.remaining_years ?? 0),
    render: (v: number) => v > 0
      ? numCell(fmt(v, 1))
      : <span style={{ color: '#bbb', fontSize: 13 }}>-</span>,
  },
  {
    title: '强赎', dataIndex: 'forced_call_days', key: 'forced_call_days', width: 70,
    sorter: (a, b) => (a.forced_call_days ?? 0) - (b.forced_call_days ?? 0),
    render: (v: number) => {
      if (!v || v <= 0) return <span style={{ color: '#bbb', fontSize: 13 }}>-</span>
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

function MarketTable({ bonds, loading, onRowClick }: MarketTableProps) {

  return (
    <Table<ConvertibleQuote>
      columns={columns}
      dataSource={bonds}
      rowKey="code"
      loading={loading}
      size="small"
      scroll={{ x: 1300, y: 'calc(100vh - 160px)' }}
      pagination={false}
      onRow={(record) => ({ onClick: () => onRowClick(record.code), style: { cursor: 'pointer' } })}
      locale={{ emptyText: '暂无数据' }}
    />
  )
}

export default memo(MarketTable)
