import { Tag, Space, Typography, Button, Tooltip } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, ReloadOutlined } from '@ant-design/icons'
import { useAppStore } from '../stores/useAppStore'
import { useMarketStore } from '../stores/useMarketStore'
import { healthCheck } from '../services/api'

const { Text } = Typography

export default function StatusBar() {
  const backendConnected = useAppStore((s) => s.backendConnected)
  const setBackendConnected = useAppStore((s) => s.setBackendConnected)
  const updatedAt = useMarketStore((s) => s.updatedAt)
  const bondCount = useMarketStore((s) => s.allBonds.length)

  const handleReconnect = async () => {
    try {
      await healthCheck()
      setBackendConnected(true)
    } catch {
      setBackendConnected(false)
    }
  }

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
          <>
            <Tag icon={<CloseCircleOutlined />} color="error">后端未连接</Tag>
            <Tooltip title="重新连接后端服务">
              <Button size="small" type="link" icon={<ReloadOutlined />} onClick={handleReconnect} />
            </Tooltip>
          </>
        )}
      </Space>
      <Text type="secondary" style={{ fontSize: 12 }}>LiangHua v0.1.0</Text>
      <Text type="secondary" style={{ fontSize: 12 }}>可转债: {bondCount} 只</Text>
      {updatedAt && <Text type="secondary" style={{ fontSize: 12 }}>更新: {updatedAt}</Text>}
      <div style={{ flex: 1 }} />
      <Text type="secondary" style={{ fontSize: 12 }}>数据源: AKShare</Text>
    </div>
  )
}
