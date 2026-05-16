import { Table, Button, Empty, Tag, Typography, Space } from 'antd'
import { ExportOutlined, HistoryOutlined } from '@ant-design/icons'
import type { Order } from '../../stores/useTradeStore'
import { exportTrades } from '../../utils/export'

const { Text } = Typography

const statusColors: Record<string, string> = {
  filled: 'green',
  pending: 'orange',
  cancelled: 'default',
  rejected: 'red',
}

const statusLabels: Record<string, string> = {
  filled: '已成交',
  pending: '待成交',
  cancelled: '已撤单',
  rejected: '已拒绝',
}

interface OrderHistoryProps {
  orders: Order[]
  onCancelOrder: (orderId: string) => void
}

const orderColumns = (onCancelOrder: (orderId: string) => void) => [
  { title: 'ID', dataIndex: 'id', width: 120, ellipsis: true },
  { title: '代码', dataIndex: 'code', width: 90 },
  { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
  { title: '方向', dataIndex: 'side', width: 60, render: (v: string) => <Tag color={v === 'buy' ? 'red' : 'green'}>{v === 'buy' ? '买' : '卖'}</Tag> },
  { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => v.toFixed(2) },
  { title: '数量', dataIndex: 'volume', width: 60 },
  { title: '成交', dataIndex: 'filled_volume', width: 60 },
  { title: '状态', dataIndex: 'status', width: 80, render: (v: string) => <Tag color={statusColors[v]}>{statusLabels[v] || v}</Tag> },
  { title: '操作', width: 80, render: (_: any, record: Order) =>
    record.status === 'pending' ? <Button size="small" danger onClick={() => onCancelOrder(record.id)}>撤单</Button> : null
  },
]

export default function OrderHistory({ orders, onCancelOrder }: OrderHistoryProps) {
  return (
    <>
      <Space style={{ marginBottom: 8 }}>
        <Text type="secondary"><HistoryOutlined /> 委托记录 (共 {orders.length} 笔)</Text>
        {orders.length > 0 && (
          <Button size="small" icon={<ExportOutlined />} onClick={() => exportTrades(orders)}>导出</Button>
        )}
      </Space>
      {orders.length === 0 ? (
        <Empty description="暂无委托记录" style={{ margin: '20px 0' }} />
      ) : (
        <Table
          dataSource={[...orders].reverse().slice(0, 100)}
          rowKey="id"
          columns={orderColumns(onCancelOrder)}
          size="small"
          pagination={{ pageSize: 10, showSizeChanger: false }}
          scroll={{ x: 700, y: 250 }}
        />
      )}
    </>
  )
}
