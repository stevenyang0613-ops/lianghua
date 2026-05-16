/**
 * 风险敞口热力图组件
 * 可视化展示投资组合风险分布
 */

import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  Card, Row, Col, Select, Slider, Switch, Space, Button, Typography,
  Tooltip, Empty, Spin, Tabs, Table, Tag, Statistic, Progress
} from 'antd'
import {
  HeatMapOutlined, WarningOutlined, CheckCircleOutlined,
  ReloadOutlined, DownloadOutlined, SettingOutlined,
  AlertOutlined, InfoCircleOutlined
} from '@ant-design/icons'
import ReactECharts from 'echarts-for-react'
import type { EChartsOption } from 'echarts'
import { multiAccountManager } from '../utils/multiAccountManager'

const { Title, Text } = Typography
const { TabPane } = Tabs

// 风险维度
type RiskDimension = 'market' | 'sector' | 'maturity' | 'credit' | 'liquidity' | 'volatility'

// 风险敞口数据
interface RiskExposure {
  dimension: RiskDimension
  category: string
  exposure: number      // 敞口金额
  percentage: number    // 占比
  riskScore: number     // 风险分数 0-100
  limit: number         // 风险限额
  status: 'safe' | 'warning' | 'danger'
}

// 相关性矩阵
interface CorrelationMatrix {
  symbols: string[]
  matrix: number[][]
}

// 风险归因
interface RiskAttribution {
  factor: string
  contribution: number  // 贡献度
  direction: 'positive' | 'negative'
  impact: number        // 影响金额
}

interface Props {
  accountIds?: string[]
  onRiskAlert?: (alert: { dimension: string; message: string }) => void
}

export default function RiskHeatmap({ accountIds, onRiskAlert }: Props) {
  const [loading, setLoading] = useState(false)
  const [selectedDimension, setSelectedDimension] = useState<RiskDimension>('market')
  const [riskThreshold, setRiskThreshold] = useState(70)
  const [showNormalized, setShowNormalized] = useState(true)
  const [riskData, setRiskData] = useState<RiskExposure[]>([])
  const [correlationMatrix, setCorrelationMatrix] = useState<CorrelationMatrix | null>(null)
  const [riskAttribution, setRiskAttribution] = useState<RiskAttribution[]>([])

  // 生成模拟风险数据
  useEffect(() => {
    setLoading(true)

    // 模拟数据生成
    const generateRiskData = (): RiskExposure[] => {
      const dimensions: Record<RiskDimension, string[]> = {
        market: ['股票', '债券', '可转债', '基金', '现金'],
        sector: ['金融', '科技', '消费', '医药', '能源', '制造'],
        maturity: ['0-1年', '1-3年', '3-5年', '5-10年', '10年以上'],
        credit: ['AAA', 'AA+', 'AA', 'AA-', 'A+', 'A'],
        liquidity: ['高流动性', '中流动性', '低流动性', '限制性'],
        volatility: ['低波动', '中波动', '高波动', '极高波动'],
      }

      const categories = dimensions[selectedDimension]
      let totalExposure = 0

      const data = categories.map(category => {
        const exposure = Math.random() * 1000000 + 100000
        totalExposure += exposure

        return {
          dimension: selectedDimension,
          category,
          exposure,
          percentage: 0,
          riskScore: Math.random() * 100,
          limit: 500000,
          status: 'safe' as const,
        }
      })

      // 计算占比和状态
      data.forEach(item => {
        item.percentage = (item.exposure / totalExposure) * 100
        item.status = item.riskScore >= riskThreshold ? 'danger' :
                     item.riskScore >= riskThreshold * 0.7 ? 'warning' : 'safe'
      })

      return data
    }

    // 生成相关性矩阵
    const generateCorrelationMatrix = (): CorrelationMatrix => {
      const symbols = ['128001', '128002', '128003', '128004', '128005', '128006', '128007', '128008']
      const n = symbols.length
      const matrix: number[][] = []

      for (let i = 0; i < n; i++) {
        const row: number[] = []
        for (let j = 0; j < n; j++) {
          if (i === j) {
            row.push(1)
          } else if (j > i) {
            const corr = Math.random() * 2 - 1  // -1 to 1
            row.push(corr)
          } else {
            row.push(matrix[j][i])
          }
        }
        matrix.push(row)
      }

      return { symbols, matrix }
    }

    // 生成风险归因
    const generateRiskAttribution = (): RiskAttribution[] => {
      const factors = ['市场风险', '信用风险', '流动性风险', '利率风险', '汇率风险']
      let total = 0

      const data = factors.map(factor => {
        const contribution = Math.random() * 30 + 5
        total += contribution
        return {
          factor,
          contribution,
          direction: Math.random() > 0.5 ? 'positive' : 'negative' as const,
          impact: (Math.random() - 0.5) * 100000,
        }
      })

      // 归一化
      data.forEach(item => {
        item.contribution = (item.contribution / total) * 100
      })

      return data.sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution))
    }

    setTimeout(() => {
      setRiskData(generateRiskData())
      setCorrelationMatrix(generateCorrelationMatrix())
      setRiskAttribution(generateRiskAttribution())
      setLoading(false)
    }, 500)
  }, [selectedDimension, riskThreshold])

  // 热力图配置
  const heatmapOption = useMemo((): EChartsOption => {
    if (!correlationMatrix) return {}

    const { symbols, matrix } = correlationMatrix

    // 转换数据格式 [x, y, value]
    const data: [number, number, number][] = []
    for (let i = 0; i < symbols.length; i++) {
      for (let j = 0; j < symbols.length; j++) {
        data.push([i, j, matrix[i][j]])
      }
    }

    return {
      title: {
        text: '持仓相关性热力图',
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        position: 'top',
        formatter: (params: { data: [number, number, number] }) => {
          const [x, y, value] = params.data
          return `${symbols[x]} - ${symbols[y]}<br/>相关系数: ${value.toFixed(3)}`
        },
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
      },
      grid: {
        left: '15%',
        right: '5%',
        bottom: '15%',
        top: '15%',
      },
      xAxis: {
        type: 'category',
        data: symbols,
        splitArea: { show: true },
        axisLabel: { color: '#888', rotate: 45 },
        axisLine: { lineStyle: { color: '#444' } },
      },
      yAxis: {
        type: 'category',
        data: symbols,
        splitArea: { show: true },
        axisLabel: { color: '#888' },
        axisLine: { lineStyle: { color: '#444' } },
      },
      visualMap: {
        min: -1,
        max: 1,
        calculable: true,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        inRange: {
          color: ['#ff4d4f', '#fff', '#52c41a'],
        },
        textStyle: { color: '#888' },
      },
      series: [{
        type: 'heatmap',
        data,
        label: {
          show: true,
          formatter: (params: { data: [number, number, number] }) => params.data[2].toFixed(2),
          color: '#333',
          fontSize: 10,
        },
        emphasis: {
          itemStyle: {
            shadowBlur: 10,
            shadowColor: 'rgba(0, 0, 0, 0.5)',
          },
        },
      }],
    }
  }, [correlationMatrix])

  // 风险敞口条形图配置
  const exposureBarOption = useMemo((): EChartsOption => {
    return {
      title: {
        text: `${selectedDimension}维度风险敞口`,
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: 'shadow' },
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
      },
      grid: {
        left: '3%',
        right: '4%',
        bottom: '3%',
        top: '15%',
        containLabel: true,
      },
      xAxis: {
        type: 'value',
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888', formatter: '¥{value}' },
        splitLine: { lineStyle: { color: '#333' } },
      },
      yAxis: {
        type: 'category',
        data: riskData.map(d => d.category),
        axisLine: { lineStyle: { color: '#444' } },
        axisLabel: { color: '#888' },
      },
      series: [
        {
          name: '敞口金额',
          type: 'bar',
          data: riskData.map(d => ({
            value: d.exposure,
            itemStyle: {
              color: d.status === 'danger' ? '#ff4d4f' :
                     d.status === 'warning' ? '#faad14' : '#52c41a',
            },
          })),
          label: {
            show: true,
            position: 'right',
            formatter: (params: { value: number }) => `¥${(params.value / 1000).toFixed(0)}K`,
            color: '#888',
          },
        },
        {
          name: '风险限额',
          type: 'bar',
          data: riskData.map(d => d.limit),
          barWidth: 2,
          itemStyle: { color: '#ff4d4f', opacity: 0.5 },
        },
      ],
    }
  }, [riskData, selectedDimension])

  // 风险归因饼图配置
  const attributionPieOption = useMemo((): EChartsOption => {
    return {
      title: {
        text: '风险归因分析',
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        trigger: 'item',
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
        formatter: '{b}: {c}% ({d}%)',
      },
      legend: {
        orient: 'vertical',
        right: 10,
        top: 'center',
        textStyle: { color: '#888' },
      },
      series: [{
        type: 'pie',
        radius: ['40%', '70%'],
        center: ['40%', '50%'],
        avoidLabelOverlap: false,
        label: {
          show: false,
        },
        emphasis: {
          label: {
            show: true,
            fontSize: 14,
            fontWeight: 'bold',
          },
        },
        labelLine: {
          show: false,
        },
        data: riskAttribution.map(item => ({
          name: item.factor,
          value: Math.abs(item.contribution),
          itemStyle: {
            color: item.direction === 'positive' ? '#52c41a' : '#ff4d4f',
          },
        })),
      }],
    }
  }, [riskAttribution])

  // 风险雷达图配置
  const riskRadarOption = useMemo((): EChartsOption => {
    const indicators = [
      { name: '市场风险', max: 100 },
      { name: '信用风险', max: 100 },
      { name: '流动性风险', max: 100 },
      { name: '操作风险', max: 100 },
      { name: '合规风险', max: 100 },
    ]

    return {
      title: {
        text: '综合风险评估',
        left: 'center',
        textStyle: { color: '#fff', fontSize: 14 },
      },
      tooltip: {
        backgroundColor: 'rgba(0,0,0,0.8)',
        textStyle: { color: '#fff' },
      },
      radar: {
        indicator: indicators,
        axisLine: { lineStyle: { color: '#444' } },
        splitLine: { lineStyle: { color: '#333' } },
        splitArea: { areaStyle: { color: ['rgba(100,100,100,0.1)', 'rgba(100,100,100,0.2)'] } },
        axisName: { color: '#888' },
      },
      series: [{
        type: 'radar',
        data: [{
          value: riskAttribution.map(a => Math.abs(a.contribution) * 2),
          name: '当前风险',
          areaStyle: { color: 'rgba(255, 77, 79, 0.3)' },
          lineStyle: { color: '#ff4d4f' },
          itemStyle: { color: '#ff4d4f' },
        }],
      }],
    }
  }, [riskAttribution])

  // 风险状态统计
  const riskStats = useMemo(() => {
    const safe = riskData.filter(d => d.status === 'safe').length
    const warning = riskData.filter(d => d.status === 'warning').length
    const danger = riskData.filter(d => d.status === 'danger').length

    return { safe, warning, danger, total: riskData.length }
  }, [riskData])

  // 导出报告
  const handleExport = useCallback(() => {
    const report = {
      timestamp: new Date().toISOString(),
      dimension: selectedDimension,
      riskData,
      correlationMatrix,
      riskAttribution,
    }

    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `risk_report_${new Date().toISOString().split('T')[0]}.json`
    a.click()
    URL.revokeObjectURL(url)
  }, [riskData, correlationMatrix, riskAttribution, selectedDimension])

  return (
    <div style={{ padding: 24 }}>
      {/* 控制面板 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col span={6}>
            <Space>
              <Text>风险维度：</Text>
              <Select
                value={selectedDimension}
                onChange={setSelectedDimension}
                style={{ width: 150 }}
                options={[
                  { label: '市场风险', value: 'market' },
                  { label: '行业风险', value: 'sector' },
                  { label: '久期风险', value: 'maturity' },
                  { label: '信用风险', value: 'credit' },
                  { label: '流动性风险', value: 'liquidity' },
                  { label: '波动率风险', value: 'volatility' },
                ]}
              />
            </Space>
          </Col>
          <Col span={8}>
            <Space>
              <Text>风险阈值：</Text>
              <Slider
                value={riskThreshold}
                onChange={setRiskThreshold}
                min={50}
                max={100}
                style={{ width: 150 }}
                marks={{ 50: '50', 70: '70', 100: '100' }}
              />
              <Tag color={riskThreshold >= 80 ? 'red' : riskThreshold >= 60 ? 'orange' : 'green'}>
                {riskThreshold}
              </Tag>
            </Space>
          </Col>
          <Col span={6}>
            <Space>
              <Switch checked={showNormalized} onChange={setShowNormalized} />
              <Text>归一化显示</Text>
            </Space>
          </Col>
          <Col span={4}>
            <Space>
              <Button icon={<ReloadOutlined />} onClick={() => setLoading(true)}>
                刷新
              </Button>
              <Button icon={<DownloadOutlined />} onClick={handleExport}>
                导出
              </Button>
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 概览卡片 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={6}>
          <Card>
            <Statistic
              title="安全敞口"
              value={riskStats.safe}
              suffix={`/ ${riskStats.total}`}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="预警敞口"
              value={riskStats.warning}
              valueStyle={{ color: '#faad14' }}
              prefix={<WarningOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="危险敞口"
              value={riskStats.danger}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<AlertOutlined />}
            />
          </Card>
        </Col>
        <Col span={6}>
          <Card>
            <Statistic
              title="综合风险评分"
              value={riskAttribution.reduce((sum, a) => sum + Math.abs(a.contribution), 0) / riskAttribution.length}
              precision={1}
              suffix="/ 100"
              valueStyle={{
                color: riskStats.danger > 0 ? '#ff4d4f' : riskStats.warning > 0 ? '#faad14' : '#52c41a',
              }}
            />
            <Progress
              percent={riskAttribution.reduce((sum, a) => sum + Math.abs(a.contribution), 0) / riskAttribution.length}
              showInfo={false}
              strokeColor={riskStats.danger > 0 ? '#ff4d4f' : riskStats.warning > 0 ? '#faad14' : '#52c41a'}
            />
          </Card>
        </Col>
      </Row>

      {/* 图表区域 */}
      <Tabs defaultActiveKey="heatmap">
        <TabPane tab={<span><HeatMapOutlined />相关性热力图</span>} key="heatmap">
          <Card>
            <Spin spinning={loading}>
              {correlationMatrix ? (
                <ReactECharts option={heatmapOption} style={{ height: 500 }} notMerge />
              ) : (
                <Empty description="暂无相关性数据" />
              )}
            </Spin>
          </Card>
        </TabPane>

        <TabPane tab={<span>风险敞口</span>} key="exposure">
          <Card>
            <Spin spinning={loading}>
              <ReactECharts option={exposureBarOption} style={{ height: 400 }} notMerge />
            </Spin>
          </Card>
        </TabPane>

        <TabPane tab={<span>风险归因</span>} key="attribution">
          <Row gutter={16}>
            <Col span={12}>
              <Card>
                <ReactECharts option={attributionPieOption} style={{ height: 400 }} notMerge />
              </Card>
            </Col>
            <Col span={12}>
              <Card>
                <ReactECharts option={riskRadarOption} style={{ height: 400 }} notMerge />
              </Card>
            </Col>
          </Row>
        </TabPane>
      </Tabs>

      {/* 风险提示 */}
      {riskStats.danger > 0 && (
        <Card style={{ marginTop: 16, borderColor: '#ff4d4f' }}>
          <Space>
            <AlertOutlined style={{ color: '#ff4d4f' }} />
            <Text type="danger">
              检测到 {riskStats.danger} 个高风险敞口，请及时调整仓位！
            </Text>
            <Button type="link" onClick={() => onRiskAlert?.({ dimension: selectedDimension, message: '高风险敞口警告' })}>
              查看详情
            </Button>
          </Space>
        </Card>
      )}
    </div>
  )
}
