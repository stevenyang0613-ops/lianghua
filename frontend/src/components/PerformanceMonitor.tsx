/**
 * 性能监控面板组件
 * 实时展示 FPS、内存、网络状态
 * 支持崩溃报告查看和诊断日志导出
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { Card, Row, Col, Statistic, Progress, Tag, Space, Button, Typography, Tooltip, Drawer, List, Badge, Modal, message, Descriptions } from 'antd'
import {
  DashboardOutlined,
  ApiOutlined,
  DatabaseOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  CloseOutlined,
  WarningOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  BugOutlined,
  ExportOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import { memoryMonitor } from '../utils/memoryManager'
import { usePerformanceStore } from '../stores/usePerformanceStore'

const { Text, Paragraph } = Typography

// Electron API 类型声明
interface ElectronAPI {
  isElectron: boolean
  getPerformanceMetrics: () => Promise<{
    startupTime: number
    backendReadyTime: number
    memoryUsage: { rss: number; heapTotal: number; heapUsed: number; external: number }
    cpuUsage: { user: number; system: number }
    crashCount: number
    lastCrashTime: number | null
    uptime: number
  }>
  getCrashReports: (limit?: number) => Promise<CrashReport[]>
  clearCrashReports: () => Promise<{ success: boolean }>
  exportDiagnosticLogs: () => Promise<{ path: string }>
}

interface CrashReport {
  timestamp: number
  type: 'renderer' | 'main' | 'backend' | 'gpu'
  message: string
  stack?: string
  appVersion: string
  electronVersion: string
  platform: string
  arch: string
  uptime: number
}


interface PerformanceMetrics {
  fps: number
  memory: {
    used: number
    total: number
    trend: 'increasing' | 'decreasing' | 'stable'
    pressure: 'low' | 'medium' | 'high'
  }
  network: {
    latency: number
    requests: number
    failures: number
    bandwidth: number
  }
  cache: {
    hits: number
    misses: number
    size: number
  }
  render: {
    components: number
    rerenders: number
    slowRenders: number
  }
}

interface NetworkLog {
  timestamp: number
  url: string
  method: string
  status: number
  duration: number
  size?: number
}

export default function PerformanceMonitor() {
  const { enabled } = usePerformanceStore()
  const [metrics, setMetrics] = useState<PerformanceMetrics>({
    fps: 60,
    memory: { used: 0, total: 0, trend: 'stable', pressure: 'low' },
    network: { latency: 0, requests: 0, failures: 0, bandwidth: 0 },
    cache: { hits: 0, misses: 0, size: 0 },
    render: { components: 0, rerenders: 0, slowRenders: 0 },
  })
  const [visible, setVisible] = useState(false)
  const [networkLogs, setNetworkLogs] = useState<NetworkLog[]>([])
  const [fpsHistory, setFpsHistory] = useState<number[]>(new Array(60).fill(60))

  // Electron 特有功能状态
  const [crashReports, setCrashReports] = useState<CrashReport[]>([])
  const [crashModalVisible, setCrashModalVisible] = useState(false)
  const [electronMetrics, setElectronMetrics] = useState<{
    uptime: number
    crashCount: number
    lastCrashTime: number | null
    startupTime: number
  } | null>(null)
  const isElectron = typeof window !== 'undefined' && window.electronAPI?.isElectron === true

  const frameCount = useRef(0)
  const lastTime = useRef(performance.now())
  const animationId = useRef<number>()

  // FPS 监控
  useEffect(() => {
    const measureFPS = () => {
      frameCount.current++
      const now = performance.now()
      const delta = now - lastTime.current

      if (delta >= 1000) {
        const fps = Math.round((frameCount.current * 1000) / delta)
        frameCount.current = 0
        lastTime.current = now

        setFpsHistory(prev => [...prev.slice(1), fps])
        setMetrics(prev => ({ ...prev, fps }))
      }

      animationId.current = requestAnimationFrame(measureFPS)
    }

    animationId.current = requestAnimationFrame(measureFPS)

    return () => {
      if (animationId.current) {
        cancelAnimationFrame(animationId.current)
      }
    }
  }, [])

  // 内存监控
  useEffect(() => {
    const interval = setInterval(() => {
      const memory = memoryMonitor.record()
      const trend = memoryMonitor.getTrend()
      const pressure = memoryMonitor.getPressure()

      if (memory) {
        setMetrics(prev => ({
          ...prev,
          memory: {
            used: Math.round(memory.used / (1024 * 1024)),
            total: Math.round(memory.total / (1024 * 1024)),
            trend: trend.trend,
            pressure,
          },
        }))
      }
    }, 2000)

    return () => clearInterval(interval)
  }, [])

  // 网络监控 — 仅在启用时拦截 fetch
  useEffect(() => {
    if (!enabled) return

    const originalFetch = window.fetch
    let requestCount = 0
    let failureCount = 0

    window.fetch = async (...args) => {
      const startTime = performance.now()
      requestCount++

      try {
        const response = await originalFetch(...args)
        const duration = performance.now() - startTime

        const log: NetworkLog = {
          timestamp: Date.now(),
          url: args[0] as string,
          method: 'GET',
          status: response.status,
          duration: Math.round(duration),
        }

        setNetworkLogs(prev => [log, ...prev].slice(0, 100))

        if (!response.ok) {
          failureCount++
        }

        setMetrics(prev => ({
          ...prev,
          network: {
            ...prev.network,
            latency: Math.round(duration),
            requests: requestCount,
            failures: failureCount,
          },
        }))

        return response
      } catch (error) {
        failureCount++
        throw error
      }
    }

    return () => {
      window.fetch = originalFetch
    }
  }, [enabled])

  // Electron 性能监控
  useEffect(() => {
    if (!isElectron || !window.electronAPI) return

    const fetchElectronMetrics = async () => {
      try {
        const data = await window.electronAPI!.getPerformanceMetrics()
        setElectronMetrics({
          uptime: data.uptime,
          crashCount: data.crashCount,
          lastCrashTime: data.lastCrashTime,
          startupTime: data.startupTime,
        })
      } catch (e) {
        console.error('Failed to fetch Electron metrics:', e)
      }
    }

    fetchElectronMetrics()
    const interval = setInterval(fetchElectronMetrics, 10000)
    return () => clearInterval(interval)
  }, [isElectron])

  // 获取崩溃报告
  const fetchCrashReports = useCallback(async () => {
    if (!window.electronAPI) return
    try {
      const reports = await window.electronAPI.getCrashReports(20)
      setCrashReports(reports)
    } catch (e) {
      console.error('Failed to fetch crash reports:', e)
    }
  }, [])

  // 清除崩溃报告
  const handleClearCrashReports = useCallback(async () => {
    if (!window.electronAPI) return
    try {
      await window.electronAPI.clearCrashReports()
      setCrashReports([])
      message.success('崩溃报告已清除')
    } catch (e) {
      message.error('清除失败')
    }
  }, [])

  // 导出诊断日志
  const handleExportLogs = useCallback(async () => {
    if (!window.electronAPI) return
    try {
      const result = await window.electronAPI.exportDiagnosticLogs()
      message.success(`诊断日志已导出到: ${result.path}`)
    } catch (e) {
      message.error('导出失败')
    }
  }, [])

  // 格式化运行时间
  const formatUptime = (ms: number): string => {
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    if (hours > 0) return `${hours}h ${minutes % 60}m`
    if (minutes > 0) return `${minutes}m ${seconds % 60}s`
    return `${seconds}s`
  }

  // 清除日志
  const clearLogs = useCallback(() => {
    setNetworkLogs([])
  }, [])

  // 强制 GC（如果可用）
  const forceGC = useCallback(() => {
    if ('gc' in window) {
      (window as any).gc()
    }
    memoryMonitor.clear()
  }, [])

  // FPS 颜色
  const fpsColor = metrics.fps >= 50 ? '#52c41a' : metrics.fps >= 30 ? '#faad14' : '#ff4d4f'
  const fpsPercent = Math.min(100, (metrics.fps / 60) * 100)

  // 内存颜色
  const memoryColor =
    metrics.memory.pressure === 'low' ? '#52c41a' :
    metrics.memory.pressure === 'medium' ? '#faad14' : '#ff4d4f'

  // 渲染迷你 FPS 图表
  const renderFPSChart = () => {
    const height = 30
    const width = 80
    const maxFPS = 60

    const points = fpsHistory.map((fps, i) => {
      const x = (i / (fpsHistory.length - 1)) * width
      const y = height - (fps / maxFPS) * height
      return `${x},${y}`
    }).join(' ')

    return (
      <svg width={width} height={height} style={{ background: '#f5f5f5', borderRadius: 4 }}>
        <polyline
          points={points}
          fill="none"
          stroke={fpsColor}
          strokeWidth="1.5"
        />
      </svg>
    )
  }

  // 如果未启用，不渲染
  if (!enabled) {
    return null
  }

  return (
    <>
      {/* 迷你状态栏 */}
      <div
        style={{
          position: 'fixed',
          bottom: 16,
          right: 16,
          zIndex: 1000,
          background: 'rgba(0, 0, 0, 0.8)',
          borderRadius: 8,
          padding: '8px 12px',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}
        onClick={() => setVisible(true)}
      >
        <Space size={8}>
          <Tooltip title="FPS">
            <Tag color={fpsColor}>{metrics.fps} FPS</Tag>
          </Tooltip>
          <Tooltip title="内存">
            <Tag color={memoryColor}>
              {metrics.memory.used} / {metrics.memory.total} MB
            </Tag>
          </Tooltip>
          <Tooltip title="网络请求">
            <Tag color="blue">{metrics.network.requests}</Tag>
          </Tooltip>
        </Space>
        <DashboardOutlined style={{ color: '#fff' }} />
      </div>

      {/* 详细面板 */}
      <Drawer
        title={
          <Space>
            <DashboardOutlined />
            性能监控面板
          </Space>
        }
        placement="right"
        width={500}
        open={visible}
        onClose={() => setVisible(false)}
        extra={
          <Space>
            {isElectron && (
              <Button icon={<ExportOutlined />} onClick={handleExportLogs} size="small">
                导出日志
              </Button>
            )}
            {isElectron && (
              <Button
                icon={<BugOutlined />}
                onClick={() => { setCrashModalVisible(true); fetchCrashReports() }}
                size="small"
              >
                崩溃报告
              </Button>
            )}
            <Button icon={<ReloadOutlined />} onClick={forceGC} size="small">
              清理内存
            </Button>
            <Button icon={<CloseOutlined />} onClick={clearLogs} size="small">
              清除日志
            </Button>
          </Space>
        }
      >
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          {/* FPS 卡片 */}
          <Card size="small" title={<Space><ThunderboltOutlined /> 帧率监控</Space>}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="当前 FPS"
                  value={metrics.fps}
                  suffix="/ 60"
                  valueStyle={{ color: fpsColor }}
                />
              </Col>
              <Col span={16}>
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">历史趋势</Text>
                </div>
                {renderFPSChart()}
              </Col>
            </Row>
            <Progress percent={fpsPercent} strokeColor={fpsColor} showInfo={false} />
          </Card>

          {/* 内存卡片 */}
          <Card size="small" title={<Space><DatabaseOutlined /> 内存使用</Space>}>
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="已使用"
                  value={metrics.memory.used}
                  suffix="MB"
                  valueStyle={{ color: memoryColor }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="总分配"
                  value={metrics.memory.total}
                  suffix="MB"
                />
              </Col>
              <Col span={8}>
                <div style={{ marginBottom: 8 }}>
                  <Text type="secondary">内存压力</Text>
                </div>
                <Tag color={memoryColor}>
                  {metrics.memory.pressure === 'low' ? '低' :
                   metrics.memory.pressure === 'medium' ? '中' : '高'}
                </Tag>
                <div style={{ marginTop: 4 }}>
                  <Tag icon={
                    metrics.memory.trend === 'increasing' ? <WarningOutlined /> :
                    metrics.memory.trend === 'decreasing' ? <CheckCircleOutlined /> :
                    <ClockCircleOutlined />
                  }>
                    {metrics.memory.trend === 'increasing' ? '增长中' :
                     metrics.memory.trend === 'decreasing' ? '下降中' : '稳定'}
                  </Tag>
                </div>
              </Col>
            </Row>
            <Progress
              percent={metrics.memory.total > 0 ? Math.round((metrics.memory.used / metrics.memory.total) * 100) : 0}
              strokeColor={memoryColor}
            />
          </Card>

          {/* 网络卡片 */}
          <Card size="small" title={<Space><ApiOutlined /> 网络状态</Space>}>
            <Row gutter={16}>
              <Col span={6}>
                <Statistic title="请求次数" value={metrics.network.requests} />
              </Col>
              <Col span={6}>
                <Statistic title="失败次数" value={metrics.network.failures} valueStyle={{ color: metrics.network.failures > 0 ? '#ff4d4f' : undefined }} />
              </Col>
              <Col span={6}>
                <Statistic title="延迟" value={metrics.network.latency} suffix="ms" />
              </Col>
              <Col span={6}>
                <Statistic title="成功率" value={metrics.network.requests > 0 ? Math.round((1 - metrics.network.failures / metrics.network.requests) * 100) : 100} suffix="%" />
              </Col>
            </Row>
          </Card>

          {/* 网络日志 */}
          <Card size="small" title="网络日志" extra={<Badge count={networkLogs.length} />}>
            <List
              size="small"
              dataSource={networkLogs.slice(0, 10)}
              renderItem={(log) => (
                <List.Item>
                  <List.Item.Meta
                    title={
                      <Space>
                        <Tag color={log.status < 300 ? 'green' : log.status < 400 ? 'blue' : 'red'}>
                          {log.status}
                        </Tag>
                        <Text ellipsis style={{ maxWidth: 200 }}>{log.url.split('/').pop()}</Text>
                      </Space>
                    }
                    description={
                      <Space>
                        <Text type="secondary">{log.duration}ms</Text>
                        <Text type="secondary">{new Date(log.timestamp).toLocaleTimeString()}</Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
              locale={{ emptyText: '暂无网络请求' }}
            />
          </Card>

          {/* Electron 诊断工具 */}
          {isElectron && electronMetrics && (
            <Card size="small" title={<Space><BugOutlined /> Electron 诊断</Space>}>
              <Descriptions column={2} size="small">
                <Descriptions.Item label="运行时间">{formatUptime(electronMetrics.uptime)}</Descriptions.Item>
                <Descriptions.Item label="崩溃次数">
                  <Tag color={electronMetrics.crashCount > 0 ? 'red' : 'green'}>
                    {electronMetrics.crashCount}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="启动时间">
                  {new Date(electronMetrics.startupTime).toLocaleTimeString()}
                </Descriptions.Item>
                <Descriptions.Item label="最后崩溃">
                  {electronMetrics.lastCrashTime
                    ? new Date(electronMetrics.lastCrashTime).toLocaleTimeString()
                    : '无'}
                </Descriptions.Item>
              </Descriptions>
            </Card>
          )}
        </Space>
      </Drawer>

      {/* 崩溃报告 Modal */}
      <Modal
        title={<Space><BugOutlined /> 崩溃报告</Space>}
        open={crashModalVisible}
        onCancel={() => setCrashModalVisible(false)}
        footer={[
          <Button key="close" onClick={() => setCrashModalVisible(false)}>
            关闭
          </Button>,
          <Button
            key="clear"
            danger
            icon={<DeleteOutlined />}
            onClick={handleClearCrashReports}
          >
            清除所有
          </Button>,
        ]}
        width={700}
      >
        <List
          dataSource={crashReports}
          locale={{ emptyText: '暂无崩溃报告' }}
          renderItem={(report) => (
            <List.Item>
              <List.Item.Meta
                title={
                  <Space>
                    <Tag color={report.type === 'renderer' ? 'orange' : report.type === 'gpu' ? 'purple' : 'red'}>
                      {report.type}
                    </Tag>
                    <Text>{report.message.substring(0, 60)}{report.message.length > 60 ? '...' : ''}</Text>
                  </Space>
                }
                description={
                  <>
                    <Text type="secondary">
                      {new Date(report.timestamp).toLocaleString('zh-CN')} · 运行 {formatUptime(report.uptime)}
                    </Text>
                    {report.stack && (
                      <Paragraph
                        ellipsis={{ rows: 2, expandable: true }}
                        style={{ marginTop: 8, marginBottom: 0, fontSize: 11, background: '#f5f5f5', padding: 8, borderRadius: 4 }}
                      >
                        <code>{report.stack}</code>
                      </Paragraph>
                    )}
                  </>
                }
              />
            </List.Item>
          )}
        />
      </Modal>
    </>
  )
}
