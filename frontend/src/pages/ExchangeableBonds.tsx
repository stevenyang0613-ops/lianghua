import { useEffect } from 'react'
import { Card, Table, Tag, Typography, Spin, Empty, message, Skeleton } from 'antd'
import { useExchangeableStore } from '../stores/useExchangeableStore'
import { fmt } from '../utils/format'

const { Text } = Typography

export default function ExchangeableBonds() {
  const data = useExchangeableStore((s) => s.data)
  const loading = useExchangeableStore((s) => s.loading)
  const loadData = useExchangeableStore((s) => s.loadData)

  useEffect(() => {
    loadData()
  }, [loadData])

  if (loading && data.length === 0) {
    return (
      <div style={{ padding: 24 }}>
        <Card title="可交换债">
          <Skeleton paragraph={{ rows: 8 }} active />
        </Card>
      </div>
    )
  }

  return (
    <div style={{ padding: 24 }}>
      <Card title="可交换债">
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          可交换债券（EB）：持有人有权按约定条件将债券交换为发债人持有的上市公司股票
        </Text>
        {data.length > 0 ? (
          <Table
            dataSource={data}
            rowKey="code"
            size="small"
            columns={[
              { title: '代码', dataIndex: 'code', width: 100, sorter: (a, b) => String(a.code ?? '').localeCompare(String(b.code ?? '')), render: (v: string) => <Text code>{v}</Text> },
              { title: '名称', dataIndex: 'name', width: 140, sorter: (a, b) => String(a.name ?? '').localeCompare(String(b.name ?? '')) },
              { title: '价格', dataIndex: 'price', width: 100, sorter: (a, b) => (a.price ?? 0) - (b.price ?? 0), render: (v: number) => <Text>{fmt(v, 2)}</Text> },
              { title: '涨跌幅%', dataIndex: 'change_pct', width: 100, sorter: (a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0), render: (v: number) => <Text style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : undefined }}>{fmt(v, 2)}</Text> },
              { title: '溢价率%', dataIndex: 'premium_ratio', width: 100, sorter: (a, b) => (a.premium_ratio ?? 0) - (b.premium_ratio ?? 0), render: (v: number) => <Text>{fmt(v, 2)}</Text> },
              { title: '剩余年限', dataIndex: 'remaining_years', width: 100, sorter: (a, b) => (a.remaining_years ?? 0) - (b.remaining_years ?? 0), render: (v: number) => <Text>{fmt(v, 2)}</Text> },
              { title: '强赎状态', dataIndex: 'call_status', width: 120, sorter: (a, b) => String(a.call_status ?? '').localeCompare(String(b.call_status ?? '')), render: (v: string) => <Tag color={v ? 'orange' : 'default'}>{v || '无'}</Tag> },
            ]}
          />
        ) : (
          <Empty description="暂无可交换债数据" />
        )}
      </Card>
    </div>
  )
}