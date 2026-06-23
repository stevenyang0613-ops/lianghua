import { Tag, Space, Typography, Button, Tooltip } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, ReloadOutlined, WifiOutlined, DisconnectOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { useAppStore } from '../stores/useAppStore'
import { useMarketStore } from '../stores/useMarketStore'
import { marketWs, signalsWs, refreshWsToken } from '../utils/wsInstances'
import { healthCheck } from '../services/api'

const { Text } = Typography

export default function StatusBar() {
  const backendConnected = useAppStore((s) => s.backendConnected)
  const setBackendConnected = useAppStore((s) => s.setBackendConnected)
  const wsConnected = useAppStore((s) => s.marketWsConnected)
  const signalWsConnected = useAppStore((s) => s.signalWsConnected)
  const updatedAt = useMarketStore((s) => s.updatedAt)
  const bondCount = useMarketStore((s) => Array.isArray(s.allBonds) ? s.allBonds.length : 0)

  const handleReconnect = async () => {
    try {
      const res = await healthCheck()
      setBackendConnected(true)
      useAppStore.setState({ dataSources: res.data_sources || null })
    } catch {
      // 单次重试失败不修改全局状态，让 health check 机制管理
    }
  }

  const handleWsReconnect = () => {
    refreshWsToken()
    marketWs.connect()
  }

  const handleSignalWsReconnect = () => {
    refreshWsToken()
    signalsWs.connect()
  }

  return (
    <div
      style={{
        height: 28,
        background: 'var(--statusbar-bg, #f5f5f5)',
        borderTop: '1px solid var(--border-color, #e8e8e8)',
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
      <Space size={4}>
        {wsConnected ? (
          <Tag icon={<WifiOutlined />} color="success">行情实时</Tag>
        ) : (
          <>
            <Tag icon={<DisconnectOutlined />} color="warning">行情离线</Tag>
            <Tooltip title="重新连接行情 WebSocket">
              <Button size="small" type="link" icon={<ReloadOutlined />} onClick={handleWsReconnect} />
            </Tooltip>
          </>
        )}
      </Space>
      <Space size={4}>
        {signalWsConnected ? (
          <Tag icon={<ThunderboltOutlined />} color="success">信号实时</Tag>
        ) : (
          <>
            <Tag icon={<DisconnectOutlined />} color="warning">信号离线</Tag>
            <Tooltip title="重新连接信号 WebSocket">
              <Button size="small" type="link" icon={<ReloadOutlined />} onClick={handleSignalWsReconnect} />
            </Tooltip>
          </>
        )}
      </Space>
      <Text type="secondary" style={{ fontSize: 12 }}>LiangHua v0.1.0</Text>
      <Text type="secondary" style={{ fontSize: 12 }}>可转债: {bondCount} 只</Text>
      {updatedAt && <Text type="secondary" style={{ fontSize: 12 }}>更新: {updatedAt}</Text>}
      <div style={{ flex: 1 }} />
      <Text type="secondary" style={{ fontSize: 12 }}>数据源: AKShare</Text>
      <DataSourceTags />
    </div>
  )
}

function DataSourceTags() {
  const dataSources = useAppStore((s) => s.dataSources)
  if (!dataSources) return null
  const mxOk = dataSources.mx?.configured
  const tavilyOk = dataSources.tavily?.configured
  const items = []
  if (mxOk) items.push('MX')
  if (tavilyOk) items.push('TAVILY')
  if (items.length === 0) return null
  return <Tag color="success" style={{ fontSize: 11, lineHeight: '18px', padding: '0 4px' }}>+{items.join('/')}</Tag>
}
