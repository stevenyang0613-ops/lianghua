import React, { useState } from 'react'
import { Card, Typography, Row, Col, Space, Button, Popconfirm, Statistic, Modal, Tag, Empty, message } from 'antd'
import { BugOutlined, EyeOutlined, ClearOutlined } from '@ant-design/icons'
import { getErrorLogs, clearErrorLogs, getErrorStats } from '../../utils/errorLogger'

const { Text } = Typography

export const ErrorLogCard = React.memo(function ErrorLogCard() {
  const [errorLogModalVisible, setErrorLogModalVisible] = useState(false)
  const [errorLogs, setErrorLogs] = useState<any[]>([])
  const [errorStats, setErrorStats] = useState({ total: 0, byType: {}, recentCount: 0, lastErrorTime: null as number | null })

  const handleViewErrorLogs = () => {
    setErrorLogs(getErrorLogs())
    setErrorStats(getErrorStats())
    setErrorLogModalVisible(true)
  }

  const handleClearErrorLogs = () => {
    clearErrorLogs()
    setErrorStats(getErrorStats())
    message.success('错误日志已清除')
  }

  // Refresh stats on mount
  React.useEffect(() => {
    setErrorStats(getErrorStats())
  }, [])

  return (
    <>
      <Card title={<span><BugOutlined style={{ marginRight: 8 }} />错误日志</span>} style={{ marginBottom: 16 }}>
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={8}>
            <Statistic title="错误总数" value={errorStats.total} valueStyle={{ fontSize: 18 }} />
          </Col>
          <Col span={8}>
            <Statistic title="今日错误" value={errorStats.recentCount} valueStyle={{ fontSize: 18, color: errorStats.recentCount > 10 ? '#ff4d4f' : '#52c41a' }} />
          </Col>
          <Col span={8}>
            <div>
              <Text type="secondary" style={{ fontSize: 12 }}>最后错误</Text>
              <br />
              <Text style={{ fontSize: 13 }}>{errorStats.lastErrorTime ? new Date(errorStats.lastErrorTime).toLocaleString('zh-CN') : '无'}</Text>
            </div>
          </Col>
        </Row>
        <Space>
          <Button
            icon={<EyeOutlined />}
            size="small"
            onClick={handleViewErrorLogs}
          >
            查看错误日志
          </Button>
          <Popconfirm title="确定清除所有错误日志？" onConfirm={handleClearErrorLogs}>
            <Button icon={<ClearOutlined />} size="small" danger>
              清除日志
            </Button>
          </Popconfirm>
        </Space>
      </Card>

      <Modal
        title="错误日志"
        open={errorLogModalVisible}
        onCancel={() => setErrorLogModalVisible(false)}
        footer={[
          <Button key="close" type="primary" onClick={() => setErrorLogModalVisible(false)}>
            关闭
          </Button>,
        ]}
        width={800}
      >
        {errorLogs.length === 0 ? (
          <Empty description="暂无错误日志" />
        ) : (
          <div style={{ maxHeight: 400, overflow: 'auto' }}>
            {errorLogs.map((log, i) => (
              <div key={i} style={{ marginBottom: 12, padding: 8, background: '#fff1f0', borderRadius: 4 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <Tag color="error">{log.type}</Tag>
                  <Text type="secondary" style={{ fontSize: 12 }}>{new Date(log.timestamp).toLocaleString('zh-CN')}</Text>
                </div>
                <Text type="danger" style={{ fontSize: 13 }}>{log.message}</Text>
                {log.stack && (
                  <pre style={{ fontSize: 11, margin: '8px 0 0', padding: 8, background: '#f5f5f5', borderRadius: 4, overflow: 'auto', maxHeight: 100 }}>
                    {log.stack}
                  </pre>
                )}
              </div>
            ))}
          </div>
        )}
      </Modal>
    </>
  )
})
