import React, { useState, useCallback } from 'react'
import { Card, Typography, Space, Button, Modal, Empty, Spin, message } from 'antd'
import { FileTextOutlined, ClearOutlined, DownloadOutlined } from '@ant-design/icons'

const { Text } = Typography

interface LogEntry {
  time: string
  level: 'INFO' | 'WARN' | 'ERROR'
  message: string
}

export const LogViewerCard = React.memo(function LogViewerCard() {
  const [logModalVisible, setLogModalVisible] = useState(false)
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [logsLoading, setLogsLoading] = useState(false)

  const fetchLogs = useCallback(async () => {
    setLogsLoading(true)
    try {
      const savedLogs = localStorage.getItem('app_logs')
      if (savedLogs) {
        setLogs(JSON.parse(savedLogs))
      } else {
        setLogs([])
      }
    } catch {
      setLogs([])
    } finally {
      setLogsLoading(false)
    }
  }, [])

  const clearLogs = () => {
    localStorage.removeItem('app_logs')
    setLogs([])
    message.success('日志已清除')
  }

  const exportLogs = () => {
    const content = logs.map(l => `[${l.time}] [${l.level}] ${l.message}`).join('\n')
    const blob = new Blob([content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lianghua-logs-${new Date().toISOString().slice(0, 10)}.txt`
    a.click()
    URL.revokeObjectURL(url)
    message.success('日志已导出')
  }

  return (
    <>
      <Card title={<span><FileTextOutlined style={{ marginRight: 8 }} />日志查看器</span>} style={{ marginBottom: 16 }}>
        <Space style={{ width: '100%', justifyContent: 'space-between' }}>
          <Text type="secondary" style={{ fontSize: 12 }}>查看应用运行日志，便于排查问题</Text>
          <Space>
            <Button icon={<FileTextOutlined />} size="small" onClick={() => { fetchLogs(); setLogModalVisible(true) }}>
              查看日志
            </Button>
            <Button icon={<ClearOutlined />} size="small" onClick={clearLogs}>
              清除
            </Button>
          </Space>
        </Space>
      </Card>

      <Modal
        title="应用日志"
        open={logModalVisible}
        onCancel={() => setLogModalVisible(false)}
        footer={[
          <Button key="clear" icon={<ClearOutlined />} onClick={clearLogs}>
            清除日志
          </Button>,
          <Button key="export" icon={<DownloadOutlined />} onClick={exportLogs}>
            导出日志
          </Button>,
          <Button key="close" type="primary" onClick={() => setLogModalVisible(false)}>
            关闭
          </Button>,
        ]}
        width={700}
      >
        {logsLoading ? (
          <Spin />
        ) : logs.length === 0 ? (
          <Empty description="暂无日志" />
        ) : (
          <div style={{ maxHeight: 400, overflow: 'auto', background: '#1e1e1e', padding: 12, borderRadius: 4 }}>
            {logs.map((log, i) => (
              <div key={i} style={{ fontFamily: 'monospace', fontSize: 12, marginBottom: 4 }}>
                <Text style={{ color: '#888' }}>[{log.time}]</Text>
                <Text style={{ color: log.level === 'ERROR' ? '#ff6b6b' : log.level === 'WARN' ? '#ffd93d' : '#69db7c', margin: '0 8px' }}>[{log.level}]</Text>
                <Text style={{ color: '#fff' }}>{log.message}</Text>
              </div>
            ))}
          </div>
        )}
      </Modal>
    </>
  )
})
