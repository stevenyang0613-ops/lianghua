import { useEffect, useState } from 'react'
import { Card, Table, Tag, Typography, Spin, Empty, message } from 'antd'
import { fetchExchangeableBonds } from '../services/api'
import { fmt } from '../utils/format'

const { Text } = Typography

export default function ExchangeableBonds() {
  const [data, setData] = useState<any[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchExchangeableBonds()
      .then((res: any) => setData(Array.isArray(res) ? res : res?.bonds || []))
      .catch((e: any) => message.error(`加载可交换债失败: ${e.message}`))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <Spin style={{ display: 'block', margin: '100px auto' }} />

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
              { title: '代码', dataIndex: 'code', width: 100, render: (v: string) => <Text code>{v}</Text> },
              { title: '名称', dataIndex: 'name', width: 140 },
              { title: '价格', dataIndex: 'price', width: 100, render: (v: number) => <Text>{fmt(v, 2)}</Text> },
              { title: '涨跌幅%', dataIndex: 'change_pct', width: 100, render: (v: number) => <Text style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : undefined }}>{fmt(v, 2)}</Text> },
              { title: '溢价率%', dataIndex: 'premium_ratio', width: 100, render: (v: number) => <Text>{fmt(v, 2)}</Text> },
              { title: '剩余年限', dataIndex: 'remaining_years', width: 100, render: (v: number) => <Text>{fmt(v, 2)}</Text> },
              { title: '强赎状态', dataIndex: 'call_status', width: 120, render: (v: string) => <Tag color={v ? 'orange' : 'default'}>{v || '无'}</Tag> },
            ]}
          />
        ) : (
          <Empty description="暂无可交换债数据" />
        )}
      </Card>
    </div>
  )
}