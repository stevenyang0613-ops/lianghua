import { Empty, Typography } from 'antd'
const { Title } = Typography

export default function DetailPanel({ visible }: { visible: boolean }) {
  if (!visible) return null
  return (
    <div style={{ width: 300, borderLeft: '1px solid #e8e8e8', height: '100%', display: 'flex', flexDirection: 'column', background: '#fff' }}>
      <div style={{ padding: 16, borderBottom: '1px solid #f0f0f0' }}>
        <Title level={5} style={{ margin: 0 }}>详情面板</Title>
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Empty description="选中可转债查看详情" />
      </div>
    </div>
  )
}
