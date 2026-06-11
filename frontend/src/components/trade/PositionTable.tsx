import React from 'react'
import { Table, Empty, Button } from 'antd'
import { ExportOutlined } from '@ant-design/icons'
import { Typography } from 'antd'
import type { Position } from '../../stores/useTradeStore'
import { exportPositions } from '../../utils/export'
import { fmt } from '../../utils/format'

const { Text } = Typography




interface PositionTableProps {
  positions: Position[]
}

const positionColumns = [
  { title: '代码', dataIndex: 'code', width: 90 },
  { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
  { title: '持仓', dataIndex: 'volume', width: 60 },
  { title: '可用', dataIndex: 'available_volume', width: 60 },
  { title: '成本价', dataIndex: 'cost_price', width: 80, render: (v: number) => fmt(v) },
  { title: '现价', dataIndex: 'current_price', width: 80, render: (v: number) => fmt(v) },
  { title: '市值', dataIndex: 'market_value', width: 90, render: (v: number) => fmt(v) },
  {
    title: '盈亏',
    dataIndex: 'profit_amount',
    width: 90,
    render: (v: number) => <Text style={{ color: (v ?? 0) >= 0 ? '#cf1322' : '#389e0d' }}>{(v ?? 0) >= 0 ? '+' : ''}{fmt(v)}</Text>,
  },
  {
    title: '收益率',
    dataIndex: 'profit_pct',
    width: 80,
    render: (v: number) => <span style={{ color: (v ?? 0) >= 0 ? '#cf1322' : '#389e0d' }}>{(v ?? 0) >= 0 ? '+' : ''}{fmt(v)}%</span>,
  },
]

function PositionTable({ positions }: PositionTableProps) {
  return (
    <>
      {positions.length > 0 && (
        <Button size="small" icon={<ExportOutlined />} onClick={() => exportPositions(positions)} style={{ marginBottom: 8 }}>
          导出持仓
        </Button>
      )}
      {positions.length === 0 ? (
        <Empty description="暂无持仓" style={{ margin: '40px 0' }} />
      ) : (
        <Table dataSource={positions} rowKey="code" columns={positionColumns} size="small" pagination={false} scroll={{ x: 800, y: 300 }} />
      )}
    </>
  )
}

export default React.memo(PositionTable)
