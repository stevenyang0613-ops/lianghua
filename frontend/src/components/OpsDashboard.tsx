/**
 * 运维仪表盘组件
 * 综合展示系统健康状态、性能指标、告警信息、日志统计
 */

import { useEffect, useState, useCallback } from 'react'
import {
  Card, Row, Col, Statistic, Progress, Tag, Space, Button, Typography, Table, Tabs,
  Badge, Empty, Descriptions, List
} from 'antd'
import {
  DashboardOutlined, AlertOutlined, CheckCircleOutlined, WarningOutlined,
  CloseCircleOutlined, ReloadOutlined, DownloadOutlined, SettingOutlined,
  FileTextOutlined, LineChartOutlined, PieChartOutlined
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import { memoryMonitor } from '../utils/memoryManager'
import { logCollector, type LogEntry, type LogLevel } from '../utils/logCollector'
import { alertManager, type AlertEvent, type AlertLevel } from '../utils/alertNotification'
import { performanceTracker } from '../utils/performanceTracking'

const { Text, Title } = Typography
const { TabPane } = Tabs

// 系统健康状态
interface SystemHealth {
  status: 'healthy' | 'warning' | 'critical'
  cpu: number
  memory: number
  disk: number
  network: 'online' | 'offline' | 'degraded'
  apiLatency: number
  wsStatus: 'connected' | 'disconnected' | 'reconnecting'
  lastUpdate: number
}

// 性能摘要
interface PerformanceSummary {
  avgFps: number
  minFps: number
  avgMemory: number
  peakMemory: number
  apiCalls: number
  apiErrors: number
  cacheHits: number
  cacheMisses: number
  slowOperations: Array<{ name: string; duration: number; timestamp: number }>
}

export default function OpsDashboard() {
  const [loading, setLoading] = useState(true)
  const [health, setHealth] = useState<SystemHealth>({
    status: 'healthy',
    cpu: 0,
    memory: 0,
    disk: 0,
    network: 'online',
    apiLatency: 0,
    wsStatus: 'connected',
    lastUpdate: Date.now(),
  })
  const [performance, setPerformance] = useState<PerformanceSummary>({
    avgFps: 60,
    minFps: 60,
    avgMemory: 0,
    peakMemory: 0,
    apiCalls: 0,
    apiErrors: 0,
    cacheHits: 0,
    cacheMisses: 0,
    slowOperations: [],
  })
  const [alerts, setAlerts] = useState<AlertEvent[]>([])
  const [logs, setLogs] = useState<LogEntry[]>([])
  const [autoRefresh, setAutoRefresh] = useState(true)

  // 刷新所有数据
  const refreshData = useCallback(() => {
    setLoading(true)

    // 获取内存信息
    const memory = memoryMonitor.record()
    const memoryPercent = memory ? (memory.used / memory.total) * 100 : 0

    // 获取性能统计
    const stats = performanceTracker.getStatsByName()
    let avgFps = 60
    let minFps = 60
    if (stats.has('fps')) {
      const fpsStat = stats.get('fps')!
      avgFps = fpsStat.averageDuration
      minFps = fpsStat.minDuration
    }

    // 获取慢操作
    const report = performanceTracker.generateReport()
    const slowOps = report.summary.slowestOperations.slice(0, 5).map(op => ({
      name: op.name,
      duration: op.duration,
      timestamp: op.startTime,
    }))

    // 更新健康状态
    const newHealth: SystemHealth = {
      status: memoryPercent > 90 ? 'critical' : memoryPercent > 70 ? 'warning' : 'healthy',
      cpu: Math.random() * 30 + 10, // 模拟CPU使用率
      memory: memoryPercent,
      disk: Math.random() * 20 + 40, // 模拟磁盘使用率
      network: navigator.onLine ? 'online' : 'offline',
      apiLatency: Math.random() * 100 + 50,
      wsStatus: 'connected',
      lastUpdate: Date.now(),
    }
    setHealth(newHealth)

    // 更新性能摘要
    setPerformance({
      avgFps: Math.round(avgFps),
      minFps: Math.round(minFps),
      avgMemory: Math.round((memory?.used || 0) / (1024 * 1024)),
      peakMemory: Math.round((memory?.total || 0) / (1024 * 1024)),
      apiCalls: report.summary.totalOperations,
      apiErrors: 0,
      cacheHits: 0,
      cacheMisses: 0,
      slowOperations: slowOps,
    })

    // 获取告警
    setAlerts(alertManager.getActiveAlerts())

    // 获取最近日志
    setLogs(logCollector.getLogs({ limit: 50 }))

    setLoading(false)
  }, [])

  // 初始化和定时刷新
  useEffect(() => {
    refreshData()

    let interval: ReturnType<typeof setInterval> | null = null
    if (autoRefresh) {
      interval = setInterval(refreshData, 10000) // 10秒刷新
    }

    return () => {
      if (interval) clearInterval(interval)
    }
  }, [refreshData, autoRefresh])

  // 获取状态颜色
  const getStatusColor = (status: SystemHealth['status']) => {
    return status === 'healthy' ? '#52c41a' : status === 'warning' ? '#faad14' : '#ff4d4f'
  }

  // 获取级别颜色
  const getLevelColor = (level: AlertLevel | LogLevel) => {
    switch (level) {
      case 'critical':
      case 'fatal':
        return 'red'
      case 'error':
        return 'orange'
      case 'warning':
      case 'warn':
        return 'gold'
      case 'info':
        return 'blue'
      default:
        return 'default'
    }
  }

  // 告警表格列
  const alertColumns: ColumnsType<AlertEvent> = [
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 80,
      render: (level: AlertLevel) => (
        <Tag color={getLevelColor(level)}>{level.toUpperCase()}</Tag>
      ),
    },
    {
      title: '规则名称',
      dataIndex: 'ruleName',
      key: 'ruleName',
      width: 150,
      ellipsis: true,
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      ellipsis: true,
    },
    {
      title: '触发时间',
      dataIndex: 'firedAt',
      key: 'firedAt',
      width: 180,
      render: (time: number) => new Date(time).toLocaleString(),
    },
    {
      title: '操作',
      key: 'actions',
      width: 120,
      render: (_, record) => (
        <Space>
          <Button size="small" onClick={() => alertManager.acknowledgeAlert(record.id, 'user')}>
            确认
          </Button>
          <Button size="small" type="primary" onClick={() => alertManager.resolveAlert(record.id)}>
            解决
          </Button>
        </Space>
      ),
    },
  ]

  // 日志表格列
  const logColumns: ColumnsType<LogEntry> = [
    {
      title: '级别',
      dataIndex: 'level',
      key: 'level',
      width: 80,
      render: (level: LogLevel) => (
        <Tag color={getLevelColor(level)}>{level.toUpperCase()}</Tag>
      ),
    },
    {
      title: '分类',
      dataIndex: 'category',
      key: 'category',
      width: 100,
      ellipsis: true,
    },
    {
      title: '消息',
      dataIndex: 'message',
      key: 'message',
      ellipsis: true,
    },
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
      render: (time: number) => new Date(time).toLocaleString(),
    },
  ]

  // 导出日志
  const handleExportLogs = useCallback(() => {
    const csv = logCollector.export('csv')
    const blob = new Blob([csv], { type: 'text/csv' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `logs_${new Date().toISOString().split('T')[0]}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [])

  return (
    <div style={{ padding: 24 }}>
      {/* 头部 */}
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Space>
            <DashboardOutlined style={{ fontSize: 24 }} />
            <Title level={3} style={{ margin: 0 }}>运维仪表盘</Title>
            <Badge status={health.status === 'healthy' ? 'success' : health.status === 'warning' ? 'warning' : 'error'} />
          </Space>
        </Col>
        <Col>
          <Space>
            <Button
              icon={<ReloadOutlined spin={loading} />}
              onClick={refreshData}
            >
              刷新
            </Button>
            <Button
              type={autoRefresh ? 'primary' : 'default'}
              onClick={() => setAutoRefresh(!autoRefresh)}
            >
              {autoRefresh ? '自动刷新中' : '开启自动刷新'}
            </Button>
            <Button icon={<DownloadOutlined />} onClick={handleExportLogs}>
              导出日志
            </Button>
            <Button icon={<SettingOutlined />}>
              设置
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 概览卡片 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="系统状态"
              value={health.status === 'healthy' ? '正常' : health.status === 'warning' ? '警告' : '异常'}
              valueStyle={{ color: getStatusColor(health.status) }}
              prefix={health.status === 'healthy' ? <CheckCircleOutlined /> : health.status === 'warning' ? <WarningOutlined /> : <CloseCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="内存使用"
              value={(health.memory ?? 0).toFixed(1)}
              suffix="%"
              valueStyle={{ color: (health.memory ?? 0) > 80 ? '#ff4d4f' : (health.memory ?? 0) > 60 ? '#faad14' : undefined }}
            />
            <Progress percent={health.memory ?? 0} showInfo={false} strokeColor={(health.memory ?? 0) > 80 ? '#ff4d4f' : (health.memory ?? 0) > 60 ? '#faad14' : '#52c41a'} />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="API 延迟"
              value={(health.apiLatency ?? 0).toFixed(0)}
              suffix="ms"
              valueStyle={{ color: (health.apiLatency ?? 0) > 500 ? '#ff4d4f' : (health.apiLatency ?? 0) > 200 ? '#faad14' : undefined }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="活动告警"
              value={alerts.filter(a => a.status === 'firing').length}
              valueStyle={{ color: alerts.length > 0 ? '#ff4d4f' : '#52c41a' }}
              prefix={<AlertOutlined />}
            />
          </Card>
        </Col>
      </Row>

      {/* 详细信息 */}
      <Tabs defaultActiveKey="alerts">
        <TabPane
          tab={<span><AlertOutlined />告警管理 ({alerts.length})</span>}
          key="alerts"
        >
          {alerts.length > 0 ? (
            <Table
              columns={alertColumns}
              dataSource={alerts}
              rowKey="id"
              pagination={{ pageSize: 10 }}
            />
          ) : (
            <Empty description="暂无活动告警" />
          )}
        </TabPane>

        <TabPane
          tab={<span><FileTextOutlined />日志查看</span>}
          key="logs"
        >
          <Table
            columns={logColumns}
            dataSource={logs}
            rowKey="id"
            pagination={{ pageSize: 20 }}
            size="small"
          />
        </TabPane>

        <TabPane
          tab={<span><LineChartOutlined />性能指标</span>}
          key="performance"
        >
          <Row gutter={16}>
            <Col span={12}>
              <Card title="帧率统计">
                <Row gutter={16}>
                  <Col span={12}>
                    <Statistic title="平均 FPS" value={performance.avgFps} />
                  </Col>
                  <Col span={12}>
                    <Statistic title="最低 FPS" value={performance.minFps} valueStyle={{ color: performance.minFps < 30 ? '#ff4d4f' : undefined }} />
                  </Col>
                </Row>
              </Card>
            </Col>
            <Col span={12}>
              <Card title="API 统计">
                <Row gutter={16}>
                  <Col span={12}>
                    <Statistic title="调用次数" value={performance.apiCalls} />
                  </Col>
                  <Col span={12}>
                    <Statistic title="错误次数" value={performance.apiErrors} valueStyle={{ color: performance.apiErrors > 0 ? '#ff4d4f' : undefined }} />
                  </Col>
                </Row>
              </Card>
            </Col>
          </Row>

          <Card title="慢操作" style={{ marginTop: 16 }}>
            <List
              dataSource={performance.slowOperations}
              renderItem={item => (
                <List.Item>
                  <List.Item.Meta
                    title={item.name}
                    description={`${(item.duration ?? 0).toFixed(2)}ms - ${new Date(item.timestamp).toLocaleTimeString()}`}
                  />
                  <Tag color={item.duration > 1000 ? 'red' : item.duration > 500 ? 'orange' : 'blue'}>
                    {item.duration > 1000 ? '慢' : item.duration > 500 ? '中' : '快'}
                  </Tag>
                </List.Item>
              )}
              locale={{ emptyText: '暂无慢操作记录' }}
            />
          </Card>
        </TabPane>

        <TabPane
          tab={<span><PieChartOutlined />资源监控</span>}
          key="resources"
        >
          <Row gutter={16}>
            <Col span={8}>
              <Card title="CPU 使用率">
                <Progress type="circle" percent={health.cpu} strokeColor={health.cpu > 80 ? '#ff4d4f' : health.cpu > 60 ? '#faad14' : '#52c41a'} />
              </Card>
            </Col>
            <Col span={8}>
              <Card title="内存使用率">
                <Progress type="circle" percent={health.memory} strokeColor={health.memory > 80 ? '#ff4d4f' : health.memory > 60 ? '#faad14' : '#52c41a'} />
              </Card>
            </Col>
            <Col span={8}>
              <Card title="磁盘使用率">
                <Progress type="circle" percent={health.disk} strokeColor={health.disk > 90 ? '#ff4d4f' : health.disk > 70 ? '#faad14' : '#52c41a'} />
              </Card>
            </Col>
          </Row>

          <Card title="服务状态" style={{ marginTop: 16 }}>
            <Descriptions column={2}>
              <Descriptions.Item label="网络状态">
                <Tag color={health.network === 'online' ? 'green' : 'red'}>
                  {health.network === 'online' ? '在线' : '离线'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="WebSocket">
                <Tag color={health.wsStatus === 'connected' ? 'green' : health.wsStatus === 'reconnecting' ? 'orange' : 'red'}>
                  {health.wsStatus === 'connected' ? '已连接' : health.wsStatus === 'reconnecting' ? '重连中' : '已断开'}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label="最后更新">
                {new Date(health.lastUpdate).toLocaleString()}
              </Descriptions.Item>
              <Descriptions.Item label="运行时间">
                {Math.floor((Date.now() - health.lastUpdate) / 60000)} 分钟
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </TabPane>
      </Tabs>
    </div>
  )
}
