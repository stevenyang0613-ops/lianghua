import { Tag, Space, Typography } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined } from '@ant-design/icons'

const { Text } = Typography

export default function StatusBar({ backendConnected = false }: { backendConnected?: boolean }) {
  return (
    <div
      style={{
        height: 28,
        background: '#f5f5f5',
        borderTop: '1px solid #e8e8e8',
        display: 'flex',
        alignItems: 'center',
        padding: '0 12px',
        gap: 16,
        fontSize: 12,
      }}
    >
      <Space size={4}>
        {backendConnected ? (
          <Tag icon={<CheckCircleOutlined />} color="success">后端已连接</Tag>
        ) : (
          <Tag icon={<CloseCircleOutlined />} color="error">后端未连接</Tag>
        )}
      </Space>
      <Text type="secondary" style={{ fontSize: 12 }}>LiangHua v0.1.0</Text>
      <div style={{ flex: 1 }} />
      <Text type="secondary" style={{ fontSize: 12 }}>数据源: AKShare</Text>
    </div>
  )
}
