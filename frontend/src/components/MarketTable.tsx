import { memo } from 'react'
import { Table, Tag, Typography } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ConvertibleQuote } from '../types'

const { Text } = Typography

interface MarketTableProps {
  bonds: ConvertibleQuote[]
  loading: boolean
  onRowClick: (code: string) => void
}

const columns: ColumnsType<ConvertibleQuote> = [
  { title: '代码', dataIndex: 'code', key: 'code', width: 100, fixed: 'left' },
  { title: '名称', dataIndex: 'name', key: 'name', width: 100, fixed: 'left' },
  {
    title: '最新价', dataIndex: 'price', key: 'price', width: 100,
    sorter: (a, b) => a.price - b.price,
    render: (v: number, r) => {
      const color = r.change_pct > 0 ? '#cf1322' : r.change_pct < 0 ? '#389e0d' : undefined
      return <span style={{ color, fontWeight: 600, fontFamily: 'monospace' }}>{v.toFixed(2)}</span>
    },
  },
  {
    title: '涨跌幅', dataIndex: 'change_pct', key: 'change_pct', width: 100,
    sorter: (a, b) => a.change_pct - b.change_pct,
    render: (v: number) => {
      const color = v > 0 ? '#cf1322' : v < 0 ? '#389e0d' : undefined
      return <Tag color={color} style={{ fontFamily: 'monospace' }}>{v > 0 ? '+' : ''}{v.toFixed(2)}%</Tag>
    },
  },
  { title: '正股价', dataIndex: 'stock_price', key: 'stock_price', width: 90, render: (v: number) => v.toFixed(2) },
  { title: '转股价', dataIndex: 'conversion_price', key: 'conversion_price', width: 90, render: (v: number) => v.toFixed(2) },
  {
    title: '转股价值', dataIndex: 'conversion_value', key: 'conversion_value', width: 100,
    sorter: (a, b) => a.conversion_value - b.conversion_value,
    render: (v: number) => v.toFixed(2),
  },
  {
    title: '溢价率', dataIndex: 'premium_ratio', key: 'premium_ratio', width: 100,
    sorter: (a, b) => a.premium_ratio - b.premium_ratio,
    render: (v: number) => {
      const color = v < 0 ? '#cf1322' : v > 50 ? '#389e0d' : undefined
      return <Text style={{ color, fontWeight: 600 }}>{v.toFixed(2)}%</Text>
    },
  },
  {
    title: '双低值', dataIndex: 'dual_low', key: 'dual_low', width: 100,
    sorter: (a, b) => a.dual_low - b.dual_low,
    render: (v: number) => {
      const color = v < 130 ? '#52c41a' : v > 180 ? '#faad14' : undefined
      return <Text style={{ color, fontWeight: 600 }}>{v.toFixed(2)}</Text>
    },
  },
  { title: '成交额(亿)', dataIndex: 'volume', key: 'volume', width: 110, sorter: (a, b) => a.volume - b.volume, render: (v: number) => v.toFixed(2) },
  { title: '剩余年限', dataIndex: 'remaining_years', key: 'remaining_years', width: 100, render: (v: number) => v.toFixed(1) },
]

function MarketTable({ bonds, loading, onRowClick }: MarketTableProps) {

  return (
    <Table<ConvertibleQuote>
      columns={columns}
      dataSource={bonds}
      rowKey="code"
      loading={loading}
      size="small"
      scroll={{ x: 1200, y: 'calc(100vh - 160px)' }}
      pagination={false}
      onRow={(record) => ({ onClick: () => onRowClick(record.code), style: { cursor: 'pointer' } })}
      locale={{ emptyText: '暂无数据' }}
    />
  )
}

export default memo(MarketTable)
