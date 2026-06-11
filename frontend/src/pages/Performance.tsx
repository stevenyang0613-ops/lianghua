/**
 * 性能监控仪表板页面
 * 包含 API 响应监控 + Electron 进程级性能指标
 */

import { useEffect, useState, useCallback } from 'react'
import { Card, Typography, Row, Col, Statistic, Table, Tag, Button, Space, Progress, Select, Empty, Spin, Tooltip, Tabs, Descriptions } from 'antd'
import { ThunderboltOutlined, ReloadOutlined, DownloadOutlined, DeleteOutlined, WarningOutlined, CheckCircleOutlined, ApiOutlined, DashboardOutlined, BugOutlined } from '@ant-design/icons'
import { getStats, getRecords, clearRecords, exportReport, getConfig, updateConfig } from '../utils/performanceMonitor'
import { getStorageStats } from '../utils/compression'
import type { ColumnsType } from 'antd/es/table'

const { Title, Text } = Typography

// ---- Electron performance metrics ----
interface ElectronPerfMetrics {
  startupTime: number
  backendReadyTime: number
  frontendLoadTime: number
  memoryUsage: { rss: number; heapTotal: number; heapUsed: number; external: number }
  cpuUsage: { user: number; system: number }
  crashCount: number
  lastCrashTime: number | null
  uptime: number
}

interface CrashReport {
  timestamp: number
  type: string
  message: string
  stack?: string
  appVersion: string
  electronVersion: string
  platform: string
  arch: string
  memoryUsage: { rss: number; heapTotal: number; heapUsed: number }
  uptime: number
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`
}

function formatUptime(ms: number): string {
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const h = Math.floor(m / 60)
  if (h > 0) return `${h}h ${m % 60}m`
  if (m > 0) return `${m}m ${s % 60}s`
  return `${s}s`
}

interface PerformanceRecord {
  api: string
  duration: number
  timestamp: number
  status: 'ok' | 'warning' | 'critical'
}

export default function Performance() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [stats, setStats] = useState(getStats())
  const [records, setRecords] = useState<PerformanceRecord[]>([])
  const [storageStats, setStorageStats] = useState(getStorageStats())
  const [loading, setLoading] = useState(false)
  const [config, setConfig] = useState(getConfig())
  const [timeRange, setTimeRange] = useState<'all' | 'today' | 'week'>('today')
  const [electronMetrics, setElectronMetrics] = useState<ElectronPerfMetrics | null>(null)
  const [crashReports, setCrashReports] = useState<CrashReport[]>([])
  const [activeTab, setActiveTab] = useState('api')

  const loadElectronMetrics = useCallback(async () => {
    if (!window.electronAPI?.getPerformanceMetrics) return
    try {
      const metrics = await window.electronAPI.getPerformanceMetrics()
      setElectronMetrics(metrics as ElectronPerfMetrics)
    } catch {}
  }, [])

  const loadCrashReports = useCallback(async () => {
    if (!window.electronAPI?.getCrashReports) return
    try {
      const reports = await window.electronAPI.getCrashReports(20)
      setCrashReports(reports as CrashReport[])
    } catch {}
  }, [])

  useEffect(() => {
    loadElectronMetrics()
    loadCrashReports()
    const interval = setInterval(() => {
      loadElectronMetrics()
    }, 5000)
    return () => clearInterval(interval)
  }, [loadElectronMetrics, loadCrashReports])

  useEffect(() => {
    loadData()
  }, [timeRange])

  const loadData = () => {
    setLoading(true)
    const allRecords = getRecords()
    const now = Date.now()

    let filteredRecords = allRecords
    if (timeRange === 'today') {
      const todayStart = new Date().setHours(0, 0, 0, 0)
      filteredRecords = allRecords.filter(r => r.timestamp >= todayStart)
    } else if (timeRange === 'week') {
      const weekAgo = now - 7 * 24 * 60 * 60 * 1000
      filteredRecords = allRecords.filter(r => r.timestamp >= weekAgo)
    }

    setRecords(filteredRecords)
    setStats(getStats())
    setStorageStats(getStorageStats())
    setLoading(false)
  }

  const handleClearRecords = () => {
    clearRecords()
    loadData()
  }

  const handleExport = () => {
    const report = exportReport()
    const blob = new Blob([report], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lianghua-perf-report-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const handleConfigChange = (key: string, value: number | boolean) => {
    updateConfig({ [key]: value })
    setConfig(getConfig())
  }

  const columns: ColumnsType<PerformanceRecord> = [
    {
      title: 'API',
      dataIndex: 'api',
      key: 'api',
      width: 200,
      render: (api: string) => <Tag>{api}</Tag>,
    },
    {
      title: '响应时间',
      dataIndex: 'duration',
      key: 'duration',
      width: 120,
      sorter: (a, b) => a.duration - b.duration,
      render: (duration: number) => (
        <Text style={{ color: duration > config.criticalThreshold ? '#ff4d4f' : duration > config.warningThreshold ? '#faad14' : '#52c41a' }}>
          {duration}ms
        </Text>
      ),
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      filters: [
        { text: '正常', value: 'ok' },
        { text: '警告', value: 'warning' },
        { text: '严重', value: 'critical' },
      ],
      onFilter: (value, record) => record.status === value,
      render: (status: string) => {
        const colors = { ok: 'success', warning: 'warning', critical: 'error' }
        const icons = { ok: <CheckCircleOutlined />, warning: <WarningOutlined />, critical: <WarningOutlined /> }
        return <Tag color={colors[status as keyof typeof colors]} icon={icons[status as keyof typeof icons]}>{status.toUpperCase()}</Tag>
      },
    },
    {
      title: '时间',
      dataIndex: 'timestamp',
      key: 'timestamp',
      width: 180,
      render: (timestamp: number) => new Date(timestamp).toLocaleString('zh-CN'),
    },
  ]

  // 响应时间分布
  const getDistribution = () => {
    if (records.length === 0) return null

    const buckets = [
      { label: '<200ms', count: 0, color: '#52c41a' },
      { label: '200-500ms', count: 0, color: '#73d13d' },
      { label: '500-1000ms', count: 0, color: '#faad14' },
      { label: '1-3s', count: 0, color: '#fa8c16' },
      { label: '>3s', count: 0, color: '#ff4d4f' },
    ]

    records.forEach(r => {
      if (r.duration < 200) buckets[0].count++
      else if (r.duration < 500) buckets[1].count++
      else if (r.duration < 1000) buckets[2].count++
      else if (r.duration < 3000) buckets[3].count++
      else buckets[4].count++
    })

    return buckets
  }

  const distribution = getDistribution()

  const handleClearCrashReports = async () => {
    if (window.electronAPI?.clearCrashReports) {
      await window.electronAPI.clearCrashReports()
      loadCrashReports()
    }
  }

  const handleExportDiagnostics = async () => {
    if (window.electronAPI?.exportDiagnosticLogs) {
      const result = await window.electronAPI.exportDiagnosticLogs()
      if (result?.path) {
        // Download the diagnostic file
        const blob = new Blob([JSON.stringify({ electronMetrics, crashReports }, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.href = url
        a.download = `lianghua-diagnostics-${new Date().toISOString().slice(0, 10)}.json`
        a.click()
        URL.revokeObjectURL(url)
      }
    }
  }

  return (
    <div style={{ padding: 16, maxWidth: 1200, margin: '0 auto' }}>
      <Title level={4}><ThunderboltOutlined style={{ marginRight: 8 }} />性能监控仪表板</Title>

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        {
          key: 'api',
          label: <span><ApiOutlined /> API 监控</span>,
          children: (
            <>
              {/* 统计概览 */}
              <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总请求数"
              value={stats.total}
              prefix={<ApiOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均响应"
              value={stats.avgDuration}
              suffix="ms"
              valueStyle={{ color: stats.avgDuration > 1000 ? '#ff4d4f' : '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="最大响应"
              value={stats.maxDuration}
              suffix="ms"
              valueStyle={{ color: stats.maxDuration > 3000 ? '#ff4d4f' : '#faad14' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="异常请求"
              value={stats.warningCount + stats.criticalCount}
              suffix={`/ ${stats.total}`}
              valueStyle={{ color: stats.criticalCount > 0 ? '#ff4d4f' : '#faad14' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 响应时间分布 */}
      {distribution && (
        <Card title="响应时间分布" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            {distribution.map((bucket, i) => (
              <Col span={4} key={i} style={{ textAlign: 'center' }}>
                <Tooltip title={`${bucket.count} 次请求`}>
                  <div style={{ marginBottom: 8 }}>
                    <Progress
                      type="circle"
                      percent={stats.total > 0 ? Math.round((bucket.count / stats.total) * 100) : 0}
                      strokeColor={bucket.color}
                      size={80}
                    />
                  </div>
                </Tooltip>
                <Text type="secondary">{bucket.label}</Text>
              </Col>
            ))}
          </Row>
        </Card>
      )}

      {/* 存储统计 */}
      <Card title="存储统计" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic title="存储键数" value={storageStats.totalKeys} />
          </Col>
          <Col span={6}>
            <Statistic title="压缩键数" value={storageStats.compressedKeys} />
          </Col>
          <Col span={6}>
            <Statistic title="估算大小" value={storageStats.estimatedSize} suffix="KB" />
          </Col>
          <Col span={6}>
            <Statistic title="节省空间" value={storageStats.estimatedSavings} suffix="KB" valueStyle={{ color: '#52c41a' }} />
          </Col>
        </Row>
      </Card>

      {/* 告警配置 */}
      <Card title="告警配置" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>警告阈值 (ms)</Text>
            </div>
            <Select
              value={config.warningThreshold}
              onChange={(v) => handleConfigChange('warningThreshold', v)}
              style={{ width: '100%' }}
              options={[
                { value: 500, label: '500ms' },
                { value: 1000, label: '1000ms (1秒)' },
                { value: 2000, label: '2000ms (2秒)' },
                { value: 3000, label: '3000ms (3秒)' },
              ]}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>严重阈值 (ms)</Text>
            </div>
            <Select
              value={config.criticalThreshold}
              onChange={(v) => handleConfigChange('criticalThreshold', v)}
              style={{ width: '100%' }}
              options={[
                { value: 2000, label: '2000ms (2秒)' },
                { value: 3000, label: '3000ms (3秒)' },
                { value: 5000, label: '5000ms (5秒)' },
                { value: 10000, label: '10000ms (10秒)' },
              ]}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>通知设置</Text>
            </div>
            <Space>
              <Select
                value={config.enableNotifications ? 'on' : 'off'}
                onChange={(v) => handleConfigChange('enableNotifications', v === 'on')}
                style={{ width: 120 }}
                options={[
                  { value: 'on', label: '开启通知' },
                  { value: 'off', label: '关闭通知' },
                ]}
              />
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 请求记录 */}
      <Card
        title="请求记录"
        extra={
          <Space>
            <Select
              value={timeRange}
              onChange={setTimeRange}
              style={{ width: 120 }}
              options={[
                { value: 'today', label: '今天' },
                { value: 'week', label: '近一周' },
                { value: 'all', label: '全部' },
              ]}
            />
            <Button icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
            <Button icon={<DownloadOutlined />} onClick={handleExport}>导出报告</Button>
            <Button icon={<DeleteOutlined />} danger onClick={handleClearRecords}>清除记录</Button>
          </Space>
        }
      >
        {loading ? (
          <Spin />
        ) : records.length === 0 ? (
          <Empty description="暂无请求记录" />
        ) : (
          <Table
            dataSource={records}
            columns={columns}
            rowKey={(r) => `${r.timestamp}-${r.api}`}
            pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }}
            size="small"
          />
        )}
      </Card>
            </>
          ),
        },
        {
          key: 'system',
          label: <span><DashboardOutlined /> 系统指标</span>,
          children: electronMetrics ? (
            <>
              <Row gutter={16} style={{ marginBottom: 16 }}>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="应用运行时间"
                      value={formatUptime(electronMetrics.uptime)}
                      valueStyle={{ color: '#1890ff' }}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="后端就绪耗时"
                      value={electronMetrics.backendReadyTime > 0 ? `${((electronMetrics.backendReadyTime - electronMetrics.startupTime) / 1000).toFixed(1)}s` : '-'}
                      valueStyle={{ color: electronMetrics.backendReadyTime > 0 ? '#52c41a' : '#faad14' }}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="前端加载耗时"
                      value={electronMetrics.frontendLoadTime > 0 ? `${((electronMetrics.frontendLoadTime - electronMetrics.startupTime) / 1000).toFixed(1)}s` : '-'}
                      valueStyle={{ color: electronMetrics.frontendLoadTime > 0 ? '#52c41a' : '#faad14' }}
                    />
                  </Card>
                </Col>
                <Col span={6}>
                  <Card>
                    <Statistic
                      title="崩溃次数"
                      value={electronMetrics.crashCount}
                      valueStyle={{ color: electronMetrics.crashCount > 0 ? '#ff4d4f' : '#52c41a' }}
                    />
                  </Card>
                </Col>
              </Row>

              <Card title="内存使用" style={{ marginBottom: 16 }}>
                <Row gutter={16}>
                  <Col span={6}>
                    <Statistic title="RSS" value={formatBytes(electronMetrics.memoryUsage.rss)} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="堆总量" value={formatBytes(electronMetrics.memoryUsage.heapTotal)} />
                  </Col>
                  <Col span={6}>
                    <Statistic title="堆已用" value={formatBytes(electronMetrics.memoryUsage.heapUsed)} />
                  </Col>
                  <Col span={6}>
                    <Statistic
                      title="堆使用率"
                      value={electronMetrics.memoryUsage.heapTotal > 0 ? Math.round((electronMetrics.memoryUsage.heapUsed / electronMetrics.memoryUsage.heapTotal) * 100) : 0}
                      suffix="%"
                      valueStyle={{ color: (electronMetrics.memoryUsage.heapTotal > 0 ? electronMetrics.memoryUsage.heapUsed / electronMetrics.memoryUsage.heapTotal : 0) > 0.9 ? '#ff4d4f' : '#52c41a' }}
                    />
                  </Col>
                </Row>
              </Card>

              <Card title="启动时间线" style={{ marginBottom: 16 }}>
                <Descriptions column={2} size="small">
                  <Descriptions.Item label="应用启动">{electronMetrics.startupTime > 0 ? new Date(electronMetrics.startupTime).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                  <Descriptions.Item label="后端就绪">{electronMetrics.backendReadyTime > 0 ? new Date(electronMetrics.backendReadyTime).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                  <Descriptions.Item label="前端加载">{electronMetrics.frontendLoadTime > 0 ? new Date(electronMetrics.frontendLoadTime).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                  <Descriptions.Item label="最后崩溃">{electronMetrics.lastCrashTime ? new Date(electronMetrics.lastCrashTime).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
                </Descriptions>
              </Card>

              <Space>
                <Button icon={<ReloadOutlined />} onClick={loadElectronMetrics}>刷新指标</Button>
                <Button icon={<DownloadOutlined />} onClick={handleExportDiagnostics}>导出诊断日志</Button>
              </Space>
            </>
          ) : (
            <Empty description="Electron 性能指标不可用（当前为 Web 模式）" />
          ),
        },
        {
          key: 'crashes',
          label: <span><BugOutlined /> 崩溃报告 {crashReports.length > 0 && <Tag color="error">{crashReports.length}</Tag>}</span>,
          children: (
            <>
              {crashReports.length === 0 ? (
                <Empty description="暂无崩溃报告" />
              ) : (
                <>
                  <Card title="崩溃列表" extra={
                    <Space>
                      <Button icon={<ReloadOutlined />} onClick={loadCrashReports}>刷新</Button>
                      <Button icon={<DeleteOutlined />} danger onClick={handleClearCrashReports}>清除所有</Button>
                    </Space>
                  }>
                    <Table
                      dataSource={crashReports}
                      columns={[
                        {
                          title: '时间',
                          dataIndex: 'timestamp',
                          key: 'timestamp',
                          width: 180,
                          render: (ts: number) => new Date(ts).toLocaleString('zh-CN'),
                        },
                        {
                          title: '类型',
                          dataIndex: 'type',
                          key: 'type',
                          width: 100,
                          render: (type: string) => {
                            const colors: Record<string, string> = { renderer: 'error', backend: 'warning', gpu: 'processing', main: 'error' }
                            return <Tag color={colors[type] || 'default'}>{type}</Tag>
                          },
                        },
                        {
                          title: '消息',
                          dataIndex: 'message',
                          key: 'message',
                          ellipsis: true,
                        },
                        {
                          title: '运行时间',
                          dataIndex: 'uptime',
                          key: 'uptime',
                          width: 120,
                          render: (ut: number) => formatUptime(ut),
                        },
                        {
                          title: '内存',
                          dataIndex: 'memoryUsage',
                          key: 'memory',
                          width: 120,
                          render: (mu: { rss: number }) => formatBytes(mu.rss),
                        },
                      ]}
                      rowKey={(r) => `${r.timestamp}-${r.type}`}
                      pagination={{ pageSize: 10 }}
                      size="small"
                      expandable={{
                        expandedRowRender: (record: CrashReport) => (
                          <Descriptions column={2} size="small">
                            <Descriptions.Item label="应用版本">{record.appVersion}</Descriptions.Item>
                            <Descriptions.Item label="Electron 版本">{record.electronVersion}</Descriptions.Item>
                            <Descriptions.Item label="平台">{record.platform} / {record.arch}</Descriptions.Item>
                            <Descriptions.Item label="堆使用">{formatBytes(record.memoryUsage?.heapUsed || 0)}</Descriptions.Item>
                            {record.stack && <Descriptions.Item label="堆栈" span={2}><pre style={{ fontSize: 11, maxHeight: 200, overflow: 'auto' }}>{record.stack}</pre></Descriptions.Item>}
                          </Descriptions>
                        ),
                      }}
                    />
                  </Card>
                </>
              )}
            </>
          ),
        },
      ]} />
    </div>
  )
}
