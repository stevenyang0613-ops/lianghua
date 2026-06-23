import { Card, Tag, Typography, Row, Col, Button, message } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useState, useEffect, useRef } from 'react'
import { fetchSignalsHealth } from '../../services/api'
import type { SignalsHealth } from '../../services/api'

const { Text } = Typography

export function WsDiagnosticCard() {
  const [health, setHealth] = useState<SignalsHealth | null>(null)
  const [loading, setLoading] = useState(false)
  const isMountedRef = useRef(true)

  const load = async () => {
    if (!isMountedRef.current) return
    setLoading(true)
    try {
      const data = await fetchSignalsHealth()
      if (!isMountedRef.current) return
      setHealth(data)
    } catch (e: any) {
      if (!isMountedRef.current) return
      message.error(`WS诊断失败: ${e.message}`)
    } finally {
      if (isMountedRef.current) setLoading(false)
    }
  }

  useEffect(() => {
    isMountedRef.current = true
    load()
    return () => { isMountedRef.current = false }
  }, [])

  return (
    <Card size="small" title="WebSocket 诊断" extra={<Button size="small" icon={<ReloadOutlined />} onClick={load} loading={loading}>刷新</Button>}>
      {health ? (
        <Row gutter={16}>
          <Col span={8}>
            <Text>引擎: </Text>
            <Tag color={health.engine_available ? 'green' : 'red'}>{health.engine_available ? '正常' : '不可用'}</Tag>
          </Col>
          <Col span={8}>
            <Text>策略: </Text>
            <Tag>{health.active_strategies?.join(', ') || '-'}</Tag>
          </Col>
          <Col span={8}>
            <Text>信号数: </Text>
            <Text strong>{health.current_signals_count ?? '-'}</Text>
          </Col>
          <Col span={8}>
            <Text>行情WS: </Text>
            <Tag color={health.ws_connections?.market > 0 ? 'green' : 'default'}>{health.ws_connections?.market || 0} 连接</Tag>
          </Col>
          <Col span={8}>
            <Text>信号WS: </Text>
            <Tag color={health.ws_connections?.signals > 0 ? 'green' : 'default'}>{health.ws_connections?.signals || 0} 连接</Tag>
          </Col>
          <Col span={8}>
            <Text>去重: </Text>
            <Text>{health.dedup_config?.window_seconds || '-'}s / {((health.dedup_config?.price_threshold || 0) * 100).toFixed(0)}%</Text>
          </Col>
        </Row>
      ) : (
        <Text type="secondary">加载中...</Text>
      )}
    </Card>
  )
}