/**
 * 策略回测对比组件
 * 支持多策略回测结果可视化对比
 */

import { useState, useCallback, useMemo } from 'react'
import {
  Card, Row, Col, Select, Button, Space, Table, Statistic, Tag, Tabs,
  Typography, Empty, Progress, Switch, message
} from 'antd'
import {
  LineChartOutlined, BarChartOutlined, PieChartOutlined,
  DownloadOutlined, ReloadOutlined, SwapOutlined,
  FallOutlined
} from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import ReactECharts from 'echarts-for-react'
import { fmt } from '../utils/format'

const { Title, Text } = Typography
const { TabPane } = Tabs




// 回测结果接口
interface BacktestResult {
  id: string
  strategyName: string
  strategyType: string
  parameters: Record<string, number | string | boolean>
  metrics: {
    totalReturn: number
    annualizedReturn: number
    maxDrawdown: number
    sharpeRatio: number
    sortinoRatio: number
    calmarRatio: number
    winRate: number
    profitFactor: number
    avgTradeReturn: number
    maxConsecutiveLoss: number
    volatility: number
    var95: number
  }
  equityCurve: number[]
  drawdownCurve: number[]
  tradeHistory: Array<{
    date: string
    type: 'buy' | 'sell'
    price: number
    quantity: number
    profit: number
  }>
  monthlyReturns: number[]
  assetAllocation?: Record<string, number>
  createdAt: number
}

// 对比配置
interface ComparisonConfig {
  baselineId: string | null
  compareIds: string[]
  chartType: 'equity' | 'drawdown' | 'monthly' | 'distribution'
  normalized: boolean
}

interface Props {
  backtestResults: BacktestResult[]
  onRerun?: (strategyIds: string[]) => void
  onExport?: (resultIds: string[]) => void
}

export default function BacktestComparison({ backtestResults, onRerun, onExport }: Props) {
  const [config, setConfig] = useState<ComparisonConfig>({
    baselineId: null,
    compareIds: [],
    chartType: 'equity',
    normalized: true,
  })
  const [selectedResults, setSelectedResults] = useState<BacktestResult[]>([])
  const [loading, setLoading] = useState(false)

  // 选择策略
  const handleStrategySelect = useCallback((ids: string[]) => {
    const results = backtestResults.filter(r => ids.includes(r.id))
    setSelectedResults(results)

    if (results.length > 0 && !config.baselineId) {
      setConfig(prev => ({ ...prev, baselineId: results[0].id, compareIds: ids }))
    } else {
      setConfig(prev => ({ ...prev, compareIds: ids }))
    }
  }, [backtestResults, config.baselineId])

  // 获取基线策略
  const baseline = useMemo(() => {
    return selectedResults.find(r => r.id === config.baselineId) || selectedResults[0]
  }, [selectedResults, config.baselineId])

  // 计算对比指标
  const comparisonMetrics = useMemo(() => {
    if (!baseline || selectedResults.length === 0) return []

    return selectedResults.map(result => {
      const diff = {
        totalReturn: result.metrics.totalReturn - baseline.metrics.totalReturn,
        annualizedReturn: result.metrics.annualizedReturn - baseline.metrics.annualizedReturn,
        maxDrawdown: result.metrics.maxDrawdown - baseline.metrics.maxDrawdown,
        sharpeRatio: result.metrics.sharpeRatio - baseline.metrics.sharpeRatio,
        winRate: result.metrics.winRate - baseline.metrics.winRate,
      }

      return {
        ...result,
        diff,
        score: calculateOverallScore(result.metrics),
        rank: 0,
      }
    }).sort((a, b) => b.score - a.score)
      .map((item, index) => ({ ...item, rank: index + 1 }))
  }, [baseline, selectedResults])

  // 计算综合评分
  function calculateOverallScore(metrics: BacktestResult['metrics']): number {
    const weights = {
      totalReturn: 0.25,
      sharpeRatio: 0.25,
      maxDrawdown: -0.2,  // 负权重
      winRate: 0.15,
      profitFactor: 0.15,
    }

    return (
      metrics.totalReturn * weights.totalReturn +
      metrics.sharpeRatio * weights.sharpeRatio +
      (100 - metrics.maxDrawdown) * Math.abs(weights.maxDrawdown) +
      metrics.winRate * weights.winRate +
      Math.min(metrics.profitFactor, 5) * 20 * weights.profitFactor
    )
  }

  // 生成权益曲线图配置
  const getEquityChartOption = useCallback(() => {
    if (selectedResults.length === 0) return {}

    const series = selectedResults.map(result => {
      let data = result.equityCurve

      // 归一化
      if (config.normalized) {
        const baseValue = data[0]
        if (baseValue && baseValue !== 0) {
          data = data.map(v => (v / baseValue - 1) * 100)
        }
      }

      return {
        name: result.strategyName,
        type: 'line',
        data,
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2 },
      }
    })

    return {
      title: {
        text: config.normalized ? '归一化收益曲线 (%)' : '权益曲线',
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
      },
      legend: {
        data: selectedResults.map(r => r.strategyName),
        bottom: 0,
        textStyle: { color: '#888' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '15%',
        top: '15%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: Array.from({ length: Math.max(...selectedResults.map(r => r.equityCurve.length)) }, (_, i) => i),
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      series,
    }
  }, [selectedResults, config.normalized])

  // 生成回撤曲线图配置
  const getDrawdownChartOption = useCallback(() => {
    if (selectedResults.length === 0) return {}

    const series = selectedResults.map(result => ({
      name: result.strategyName,
      type: 'line',
      data: result.drawdownCurve,
      smooth: true,
      symbol: 'none',
      lineStyle: { width: 2 },
      areaStyle: { opacity: 0.1 },
    }))

    return {
      title: {
        text: '回撤曲线 (%)',
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
      },
      legend: {
        data: selectedResults.map(r => r.strategyName),
        bottom: 0,
        textStyle: { color: '#888' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '15%',
        top: '15%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: Array.from({ length: Math.max(...selectedResults.map(r => r.drawdownCurve.length)) }, (_, i) => i),
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' },
      },
      yAxis: {
        type: 'value',
        min: (value: { min: number }) => Math.floor(value.min - 5),
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      series,
    }
  }, [selectedResults])

  // 生成月度收益图配置
  const getMonthlyChartOption = useCallback(() => {
    if (selectedResults.length === 0) return {}

    const months = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

    const series = selectedResults.map(result => ({
      name: result.strategyName,
      type: 'bar',
      data: result.monthlyReturns.slice(0, 12),
      barMaxWidth: 20,
    }))

    return {
      title: {
        text: '月度收益对比 (%)',
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
      },
      legend: {
        data: selectedResults.map(r => r.strategyName),
        bottom: 0,
        textStyle: { color: '#888' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '15%',
        top: '15%',
        containLabel: true,
      },
      xAxis: {
        type: 'category',
        data: months,
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888', formatter: '{value}%' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      series,
    }
  }, [selectedResults])

  // 生成收益分布图配置
  const getDistributionChartOption = useCallback(() => {
    if (selectedResults.length === 0) return {}

    const series = selectedResults.map(result => {
      const returns = result.tradeHistory.map(t => t.profit).filter(p => p !== 0)
      return {
        name: result.strategyName,
        type: 'histogram',
        data: returns,
        bins: 30,
      }
    })

    return {
      title: {
        text: '收益分布',
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
      },
      legend: {
        data: selectedResults.map(r => r.strategyName),
        bottom: 0,
        textStyle: { color: '#888' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '15%',
        top: '15%',
        containLabel: true,
      },
      xAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      yAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      series,
    }
  }, [selectedResults])

  // 对比表格列
  const comparisonColumns: ColumnsType<typeof comparisonMetrics[0]> = [
    {
      title: '排名',
      dataIndex: 'rank',
      key: 'rank',
      width: 60,
      render: (rank: number) => (
        <Tag color={rank === 1 ? 'gold' : rank === 2 ? 'silver' : rank === 3 ? '#cd7f32' : 'default'}>
          #{rank}
        </Tag>
      ),
    },
    {
      title: '策略名称',
      dataIndex: 'strategyName',
      key: 'strategyName',
      width: 150,
    },
    {
      title: '总收益',
      key: 'totalReturn',
      width: 120,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text style={{ color: record.metrics.totalReturn >= 0 ? '#52c41a' : '#ff4d4f' }}>
            {fmt(record.metrics.totalReturn)}%
          </Text>
          {baseline && record.id !== baseline.id && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {record.diff.totalReturn >= 0 ? '+' : ''}{fmt(record.diff.totalReturn)}%
            </Text>
          )}
        </Space>
      ),
      sorter: (a, b) => a.metrics.totalReturn - b.metrics.totalReturn,
    },
    {
      title: '夏普比率',
      key: 'sharpeRatio',
      width: 100,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text>{fmt(record.metrics.sharpeRatio)}</Text>
          {baseline && record.id !== baseline.id && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {record.diff.sharpeRatio >= 0 ? '+' : ''}{fmt(record.diff.sharpeRatio)}
            </Text>
          )}
        </Space>
      ),
      sorter: (a, b) => a.metrics.sharpeRatio - b.metrics.sharpeRatio,
    },
    {
      title: '最大回撤',
      key: 'maxDrawdown',
      width: 100,
      render: (_, record) => (
        <Space direction="vertical" size={0}>
          <Text style={{ color: record.metrics.maxDrawdown > 20 ? '#ff4d4f' : undefined }}>
            -{fmt(record.metrics.maxDrawdown)}%
          </Text>
          {baseline && record.id !== baseline.id && (
            <Text type="secondary" style={{ fontSize: 11 }}>
              {record.diff.maxDrawdown >= 0 ? '+' : ''}{fmt(record.diff.maxDrawdown)}%
            </Text>
          )}
        </Space>
      ),
      sorter: (a, b) => a.metrics.maxDrawdown - b.metrics.maxDrawdown,
    },
    {
      title: '胜率',
      key: 'winRate',
      width: 80,
      render: (_, record) => (
        <Text>{fmt(record.metrics.winRate, 1)}%</Text>
      ),
      sorter: (a, b) => a.metrics.winRate - b.metrics.winRate,
    },
    {
      title: '盈亏比',
      key: 'profitFactor',
      width: 80,
      render: (_, record) => (
        <Text>{fmt(record.metrics.profitFactor)}</Text>
      ),
      sorter: (a, b) => a.metrics.profitFactor - b.metrics.profitFactor,
    },
    {
      title: '综合评分',
      dataIndex: 'score',
      key: 'score',
      width: 100,
      render: (score: number) => (
        <Progress
          percent={Math.max(0, Math.min(100, score))}
          size="small"
          strokeColor={score > 80 ? '#52c41a' : score > 50 ? '#faad14' : '#ff4d4f'}
          format={() => fmt(score, 0)}
        />
      ),
      sorter: (a, b) => a.score - b.score,
    },
  ]

  // 导出报告
  const handleExport = useCallback(() => {
    if (onExport) {
      onExport(selectedResults.map(r => r.id))
    } else {
      const data = JSON.stringify(selectedResults, null, 2)
      const blob = new Blob([data], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `backtest_comparison_${new Date().toISOString().split('T')[0]}.json`
      a.click()
      URL.revokeObjectURL(url)
      message.success('报告已导出')
    }
  }, [selectedResults, onExport])

  return (
    <div style={{ padding: 24 }}>
      {/* 选择器 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col span={12}>
            <Space>
              <Text>选择策略对比：</Text>
              <Select
                mode="multiple"
                style={{ minWidth: 400 }}
                placeholder="选择要对比的策略"
                value={config.compareIds}
                onChange={handleStrategySelect}
                options={backtestResults.map(r => ({
                  label: r.strategyName,
                  value: r.id,
                }))}
              />
            </Space>
          </Col>
          <Col span={6}>
            <Space>
              <Text>基线策略：</Text>
              <Select
                style={{ width: 200 }}
                placeholder="选择基线"
                value={config.baselineId}
                onChange={(id) => setConfig(prev => ({ ...prev, baselineId: id }))}
                options={selectedResults.map(r => ({
                  label: r.strategyName,
                  value: r.id,
                }))}
                allowClear
              />
            </Space>
          </Col>
          <Col span={6}>
            <Space>
              <Switch
                checked={config.normalized}
                onChange={(checked) => setConfig(prev => ({ ...prev, normalized: checked }))}
              />
              <Text>归一化</Text>
              <Button icon={<ReloadOutlined />} onClick={() => onRerun?.(config.compareIds)}>
                重新运行
              </Button>
              <Button icon={<DownloadOutlined />} onClick={handleExport}>
                导出报告
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {selectedResults.length === 0 ? (
        <Empty description="请选择要对比的策略" />
      ) : (
        <>
          {/* 概览卡片 */}
          <Row gutter={16} style={{ marginBottom: 16 }}>
            {comparisonMetrics.slice(0, 3).map((result, index) => (
              <Col span={8} key={result.id}>
                <Card size="small">
                  <Space direction="vertical" style={{ width: '100%' }}>
                    <Space>
                      <Tag color={index === 0 ? 'gold' : index === 1 ? 'silver' : '#cd7f32'}>
                        #{result.rank}
                      </Tag>
                      <Text strong>{result.strategyName}</Text>
                    </Space>
                    <Row gutter={8}>
                      <Col span={12}>
                        <Statistic
                          title="总收益"
                          value={result.metrics.totalReturn}
                          suffix="%"
                          valueStyle={{
                            color: result.metrics.totalReturn >= 0 ? '#52c41a' : '#ff4d4f',
                            fontSize: 18,
                          }}
                        />
                      </Col>
                      <Col span={12}>
                        <Statistic
                          title="夏普比率"
                          value={result.metrics.sharpeRatio}
                          precision={2}
                          valueStyle={{ fontSize: 18 }}
                        />
                      </Col>
                    </Row>
                  </Space>
                </Card>
              </Col>
            ))}
          </Row>

          {/* 图表 */}
          <Card style={{ marginBottom: 16 }}>
            <Tabs activeKey={config.chartType} onChange={(key) => setConfig(prev => ({ ...prev, chartType: key as ComparisonConfig['chartType'] }))}>
              <TabPane tab={<span><LineChartOutlined />权益曲线</span>} key="equity">
                <ReactECharts
                  option={getEquityChartOption()}
                  style={{ height: 400 }}
                  notMerge
                />
              </TabPane>
              <TabPane tab={<span><FallOutlined />回撤曲线</span>} key="drawdown">
                <ReactECharts
                  option={getDrawdownChartOption()}
                  style={{ height: 400 }}
                  notMerge
                />
              </TabPane>
              <TabPane tab={<span><BarChartOutlined />月度收益</span>} key="monthly">
                <ReactECharts
                  option={getMonthlyChartOption()}
                  style={{ height: 400 }}
                  notMerge
                />
              </TabPane>
              <TabPane tab={<span><PieChartOutlined />收益分布</span>} key="distribution">
                <ReactECharts
                  option={getDistributionChartOption()}
                  style={{ height: 400 }}
                  notMerge
                />
              </TabPane>
            </Tabs>
          </Card>

          {/* 详细对比表 */}
          <Card title={<span><SwapOutlined />详细指标对比</span>}>
            <Table
              columns={comparisonColumns}
              dataSource={comparisonMetrics}
              rowKey="id"
              pagination={false}
              size="small"
            />
          </Card>
        </>
      )}
    </div>
  )
}
