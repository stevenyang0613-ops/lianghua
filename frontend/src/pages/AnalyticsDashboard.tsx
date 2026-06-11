/**
 * 使用统计分析仪表板
 * 展示用户使用数据、页面访问统计、功能使用情况
 */

import { useEffect, useState } from 'react'
import { Card, Row, Col, Statistic, Typography, Progress, List, Tag, Button, Space, Empty, Tooltip, Divider, Select, message } from 'antd'
import {
  DashboardOutlined, EyeOutlined, ClockCircleOutlined,
  ThunderboltOutlined, DownloadOutlined, DeleteOutlined,
  BarChartOutlined, LineChartOutlined, PieChartOutlined,
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import { useAnalyticsStore, initAnalyticsTracking } from '../stores/useAnalyticsStore'

const { Title, Text } = Typography

const formatDuration = (ms: number): string => {
  const hours = Math.floor(ms / (1000 * 60 * 60))
  const minutes = Math.floor((ms % (1000 * 60 * 60)) / (1000 * 60))
  if (hours > 0) return `${hours}小时 ${minutes}分钟`
  if (minutes > 0) return `${minutes}分钟`
  return `${Math.floor(ms / 1000)}秒`
}

const PAGE_NAMES: Record<string, string> = {
  '/': '市场行情',
  '/market': '市场行情',
  '/watchlist': '自选股',
  '/backtest': '回测分析',
  '/trade': '交易终端',
  '/analysis': '数据分析',
  '/signals': '信号监控',
  '/strategies': '策略管理',
  '/settings': '系统设置',
  '/score-ranking': '评分排名',
  '/alerts': '预警管理',
  '/accounts': '账户管理',
  '/reports': '报告中心',
  '/risk': '风险控制',
  '/performance': '性能监控',
}

export default function AnalyticsDashboard() {
  const {
    getStats,
    getTopPages,
    getTopFeatures,
    getDailyStats,
    exportData,
    clearData,
    trackPageView,
  } = useAnalyticsStore()

  const [timeRange, setTimeRange] = useState<'7d' | '30d' | 'all'>('7d')
  const stats = getStats()
  const topPages = getTopPages(10)
  const topFeatures = getTopFeatures(10)
  const dailyStats = getDailyStats(timeRange === 'all' ? 90 : timeRange === '30d' ? 30 : 7)

  useEffect(() => {
    trackPageView('/analytics', '使用统计')
  }, [trackPageView])

  // 页面访问趋势图
  const pageViewsChartOption = {
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: dailyStats.map((d) => d.date.slice(5)),
    },
    yAxis: { type: 'value' },
    series: [
      {
        name: '页面浏览量',
        type: 'line',
        smooth: true,
        data: dailyStats.map((d) => d.pageViews),
        areaStyle: { opacity: 0.3 },
        lineStyle: { width: 2 },
        itemStyle: { color: '#1890ff' },
      },
    ],
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  }

  // 会话时长分布图
  const durationChartOption = {
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: dailyStats.map((d) => d.date.slice(5)),
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        formatter: (value: number) => `${Math.round(value / 60000)}m`,
      },
    },
    series: [
      {
        name: '使用时长',
        type: 'bar',
        data: dailyStats.map((d) => d.totalDuration),
        itemStyle: { color: '#52c41a', borderRadius: [4, 4, 0, 0] },
      },
    ],
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  }

  // 页面访问分布饼图
  const pagesPieOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: { orient: 'vertical', right: 10, top: 'center' },
    series: [
      {
        type: 'pie',
        radius: ['40%', '70%'],
        avoidLabelOverlap: false,
        itemStyle: { borderRadius: 10, borderColor: '#fff', borderWidth: 2 },
        label: { show: false },
        emphasis: { label: { show: true, fontSize: 14, fontWeight: 'bold' } },
        labelLine: { show: false },
        data: topPages.slice(0, 6).map((p) => ({
          name: PAGE_NAMES[p.path] || p.path,
          value: p.count,
        })),
      },
    ],
  }

  // 功能使用柱状图
  const featuresBarOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    xAxis: { type: 'value' },
    yAxis: {
      type: 'category',
      data: topFeatures.map((f) => f.feature).reverse(),
    },
    series: [
      {
        type: 'bar',
        data: topFeatures.map((f) => f.count).reverse(),
        itemStyle: {
          color: '#722ed1',
          borderRadius: [0, 4, 4, 0],
        },
      },
    ],
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
  }

  const handleExport = () => {
    const data = exportData()
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lianghua-analytics-${new Date().toISOString().split('T')[0]}.json`
    a.click()
    URL.revokeObjectURL(url)
    message.success('数据已导出')
    trackPageView('export-analytics', '导出统计数据')
  }

  const handleClear = () => {
    clearData()
    message.success('数据已清除')
  }

  return (
    <div style={{ padding: 24 }}>
      <Row justify="space-between" align="middle" style={{ marginBottom: 24 }}>
        <Col>
          <Title level={4} style={{ margin: 0 }}>
            <DashboardOutlined /> 使用统计分析
          </Title>
        </Col>
        <Col>
          <Space>
            <Select
              value={timeRange}
              onChange={setTimeRange}
              style={{ width: 120 }}
              options={[
                { label: '最近7天', value: '7d' },
                { label: '最近30天', value: '30d' },
                { label: '全部', value: 'all' },
              ]}
            />
            <Button icon={<DownloadOutlined />} onClick={handleExport}>
              导出数据
            </Button>
            <Button icon={<DeleteOutlined />} danger onClick={handleClear}>
              清除数据
            </Button>
          </Space>
        </Col>
      </Row>

      {/* 总览统计 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="总会话数"
              value={stats.totalSessions}
              prefix={<ThunderboltOutlined />}
              valueStyle={{ color: '#1890ff' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="页面浏览量"
              value={stats.totalPagesViews}
              prefix={<EyeOutlined />}
              valueStyle={{ color: '#52c41a' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="总使用时长"
              value={formatDuration(stats.totalDuration)}
              prefix={<ClockCircleOutlined />}
              valueStyle={{ color: '#722ed1' }}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="平均会话时长"
              value={formatDuration(stats.avgSessionDuration)}
              prefix={<BarChartOutlined />}
              valueStyle={{ color: '#fa8c16' }}
            />
          </Card>
        </Col>
      </Row>

      {/* 图表区域 */}
      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={12}>
          <Card title={<><LineChartOutlined /> 页面浏览趋势</>}>
            {dailyStats.length > 0 ? (
              <ReactECharts option={pageViewsChartOption} style={{ height: 250 }} />
            ) : (
              <Empty description="暂无数据" />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title={<><BarChartOutlined /> 使用时长趋势</>}>
            {dailyStats.length > 0 ? (
              <ReactECharts option={durationChartOption} style={{ height: 250 }} />
            ) : (
              <Empty description="暂无数据" />
            )}
          </Card>
        </Col>
      </Row>

      <Row gutter={16} style={{ marginBottom: 24 }}>
        <Col span={12}>
          <Card title={<><PieChartOutlined /> 页面访问分布</>}>
            {topPages.length > 0 ? (
              <ReactECharts option={pagesPieOption} style={{ height: 300 }} />
            ) : (
              <Empty description="暂无数据" />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card title={<><BarChartOutlined /> 功能使用排行</>}>
            {topFeatures.length > 0 ? (
              <ReactECharts option={featuresBarOption} style={{ height: 300 }} />
            ) : (
              <Empty description="暂无数据" />
            )}
          </Card>
        </Col>
      </Row>

      {/* 详细列表 */}
      <Row gutter={16}>
        <Col span={12}>
          <Card title="热门页面" extra={<Tag color="blue">{topPages.length} 个</Tag>}>
            <List
              size="small"
              dataSource={topPages}
              renderItem={(item, index) => (
                <List.Item>
                  <List.Item.Meta
                    avatar={
                      <Tag color={index < 3 ? 'gold' : 'default'}>
                        {index + 1}
                      </Tag>
                    }
                    title={PAGE_NAMES[item.path] || item.path}
                    description={`${item.count} 次访问`}
                  />
                  <Progress
                    percent={Math.round((item.count / (topPages[0]?.count || 1)) * 100)}
                    showInfo={false}
                    style={{ width: 100 }}
                    strokeColor="#1890ff"
                  />
                </List.Item>
              )}
              locale={{ emptyText: '暂无数据' }}
            />
          </Card>
        </Col>
        <Col span={12}>
          <Card title="最近活动" extra={<Tag color="green">{stats.recentActivity.length} 条</Tag>}>
            <List
              size="small"
              dataSource={stats.recentActivity.slice(0, 10)}
              renderItem={(item) => (
                <List.Item>
                  <List.Item.Meta
                    title={PAGE_NAMES[item.path] || item.path}
                    description={new Date(item.timestamp).toLocaleString('zh-CN')}
                  />
                  <Text type="secondary">
                    {item.duration > 0 ? formatDuration(item.duration) : '访问中'}
                  </Text>
                </List.Item>
              )}
              locale={{ emptyText: '暂无数据' }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
