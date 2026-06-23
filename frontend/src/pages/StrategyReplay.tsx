/**
 * 策略回放页面
 * 可视化历史策略执行过程
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { Card, Button, Space, Slider, Typography, Row, Col, Statistic, Tag, Table, Empty, Spin, Select } from 'antd'
import { PlayCircleOutlined, PauseCircleOutlined, StepBackwardOutlined, StepForwardOutlined, StopOutlined, DownloadOutlined, LineChartOutlined } from '@ant-design/icons'
import { replayEngine, generateMockReplayData, fetchRealReplaySteps, type ReplayStep, type ReplayConfig, type ReplayState } from '../utils/strategyReplay'
import type { ColumnsType } from 'antd/es/table'
import { fmt } from '../utils/format'

const { Title, Text } = Typography

export default function StrategyReplay() {
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  const [config, setConfig] = useState<ReplayConfig>({
    code: '',      // 默认空字符串，让用户选择
    strategy: 'macd_cross',
    startDate: '2024-01-01',
    endDate: '2024-12-31',
    initialCash: 100000,
    speed: 'normal',
    showIndicators: true,
  })
  const [steps, setSteps] = useState<ReplayStep[]>([])
  const [currentStep, setCurrentStep] = useState<ReplayStep | null>(null)
  const [state, setState] = useState<ReplayState>({
    isPlaying: false,
    isPaused: false,
    currentStep: 0,
    totalSteps: 0,
    speed: 1000,
  })
  const [loading, setLoading] = useState(false)
  const [speed, setSpeed] = useState<'slow' | 'normal' | 'fast'>('normal')

  const loadTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isLoadingRef = useRef(false)

  useEffect(() => {
    const unsubscribeStep = replayEngine.onStep((step, st) => {
      setCurrentStep(step)
      setState(st)
    })

    const unsubscribeState = replayEngine.onStateChange(setState)

    return () => {
      unsubscribeStep()
      unsubscribeState()
      if (loadTimeoutRef.current) {
        clearTimeout(loadTimeoutRef.current)
        loadTimeoutRef.current = null
      }
      replayEngine.stop()
    }
  }, [])

  const handleLoadReplay = useCallback(() => {
    if (isLoadingRef.current) return
    isLoadingRef.current = true
    setLoading(true)
    // 优先从后端拉取真实历史 K 线并计算技术指标；
    // 失败或数据不足时回退到 mock 兜底（仅作演示）。
    fetchRealReplaySteps(config)
      .then((real) => {
        const data = real.length > 0 ? real : generateMockReplayData(config)
        setSteps(data)
        replayEngine.loadSteps(data)
      })
      .catch(() => {
        const data = generateMockReplayData(config)
        setSteps(data)
        replayEngine.loadSteps(data)
      })
      .finally(() => {
        setLoading(false)
        isLoadingRef.current = false
        loadTimeoutRef.current = null
      })
  }, [config])

  const handlePlay = () => {
    if (state.isPlaying) {
      replayEngine.pause()
    } else {
      replayEngine.play(speed)
    }
  }

  const handleStop = () => {
    replayEngine.stop()
    setCurrentStep(steps[0] || null)
  }

  const handleStepChange = (value: number) => {
    replayEngine.goToStep(value)
  }

  const handleExport = () => {
    const data = replayEngine.exportReplay()
    const blob = new Blob([data], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `strategy-replay-${new Date().toISOString().slice(0, 10)}.json`
    a.click()
    URL.revokeObjectURL(url)
  }

  const stats = replayEngine.getStats()

  const tradeColumns: ColumnsType<ReplayStep> = [
    { title: '日期', dataIndex: 'date', width: 100 },
    {
      title: '操作',
      dataIndex: 'action',
      width: 60,
      render: (action: string) => (
        <Tag color={action === 'buy' ? 'green' : action === 'sell' ? 'red' : 'default'}>
          {action === 'buy' ? '买入' : action === 'sell' ? '卖出' : '持有'}
        </Tag>
      ),
    },
    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => fmt(v) },
    { title: '持仓数量', dataIndex: 'shares', width: 80 },
    { title: '现金', dataIndex: 'cash', width: 100, render: (v: number) => v == null ? '-' : v.toLocaleString() },
    { title: '市值', dataIndex: 'position', width: 100, render: (v: number) => v == null ? '-' : v.toLocaleString() },
    { title: '总资产', dataIndex: 'totalValue', width: 100, render: (v: number) => v == null ? '-' : v.toLocaleString() },
    {
      title: '收益',
      dataIndex: 'profitPct',
      width: 80,
      render: (v: number) => (
        <Text style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v >= 0 ? '+' : ''}{fmt(v)}%
        </Text>
      ),
    },
    { title: '原因', dataIndex: 'reason', ellipsis: true },
  ]

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}><LineChartOutlined style={{ marginRight: 8 }} />策略回放</Title>

      {/* 控制面板 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Space>
              <Select
                value={config.strategy}
                onChange={(v) => setConfig({ ...config, strategy: v })}
                style={{ width: 180 }}
                options={[
                  { value: 'macd_cross', label: 'MACD金叉策略' },
                  { value: 'ma_cross', label: '均线交叉策略' },
                  { value: 'rsi_reversal', label: 'RSI反转策略' },
                  { value: 'bollinger', label: '布林带策略' },
                  { value: 'xuanji_twelve_factor', label: '璇玑十二因子' },
                  { value: 'xibu_seven_dimension', label: '松岗七维打分' },
                  { value: 'fusion_strategy', label: '融合策略' },
                ]}
              />
              <Select
                value={speed}
                onChange={setSpeed}
                style={{ width: 100 }}
                options={[
                  { value: 'slow', label: '慢速' },
                  { value: 'normal', label: '正常' },
                  { value: 'fast', label: '快速' },
                ]}
              />
              <Button type="primary" onClick={handleLoadReplay} loading={loading}>
                加载回放
              </Button>
            </Space>
          </Col>
          {steps.length > 0 && (
            <>
              <Col>
                <Space>
                  <Button
                    icon={state.isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                    onClick={handlePlay}
                    type={state.isPlaying ? 'default' : 'primary'}
                  >
                    {state.isPlaying ? '暂停' : '播放'}
                  </Button>
                  <Button icon={<StopOutlined />} onClick={handleStop}>
                    停止
                  </Button>
                  <Button icon={<StepBackwardOutlined />} onClick={() => replayEngine.prevStep()}>
                    上一步
                  </Button>
                  <Button icon={<StepForwardOutlined />} onClick={() => replayEngine.nextStep()}>
                    下一步
                  </Button>
                </Space>
              </Col>
              <Col flex="auto">
                <Slider
                  min={0}
                  max={state.totalSteps - 1}
                  value={state.currentStep}
                  onChange={handleStepChange}
                  tooltip={{ formatter: (v) => steps[v || 0]?.date }}
                />
              </Col>
              <Col>
                <Button icon={<DownloadOutlined />} onClick={handleExport}>
                  导出
                </Button>
              </Col>
            </>
          )}
        </Row>
      </Card>

      {loading ? (
        <Spin style={{ display: 'flex', justifyContent: 'center', padding: 100 }} />
      ) : steps.length === 0 ? (
        <Empty description="请选择策略并加载回放" style={{ padding: 100 }} />
      ) : (
        <>
          {/* 当前状态 */}
          {currentStep && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={4}>
                <Card>
                  <Statistic title="日期" value={currentStep.date} valueStyle={{ fontSize: 16 }} />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="操作"
                    value={currentStep.action === 'buy' ? '买入' : currentStep.action === 'sell' ? '卖出' : '持有'}
                    valueStyle={{
                      fontSize: 16,
                      color: currentStep.action === 'buy' ? '#52c41a' : currentStep.action === 'sell' ? '#ff4d4f' : '#999',
                    }}
                  />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="现金" value={currentStep.cash} precision={2} prefix="¥" />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="持仓市值" value={currentStep.position} precision={2} prefix="¥" />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="总资产" value={currentStep.totalValue} precision={2} prefix="¥" />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic
                    title="收益率"
                    value={currentStep.profitPct}
                    precision={2}
                    suffix="%"
                    valueStyle={{ color: currentStep.profitPct >= 0 ? '#52c41a' : '#ff4d4f' }}
                  />
                </Card>
              </Col>
            </Row>
          )}

          {/* 回放统计 */}
          <Card title="回放统计" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              <Col span={4}>
                <Statistic title="总交易次数" value={stats.totalTrades} />
              </Col>
              <Col span={4}>
                <Statistic title="买入次数" value={stats.buyCount} valueStyle={{ color: '#52c41a' }} />
              </Col>
              <Col span={4}>
                <Statistic title="卖出次数" value={stats.sellCount} valueStyle={{ color: '#ff4d4f' }} />
              </Col>
              <Col span={4}>
                <Statistic title="胜率" value={stats.winRate * 100} precision={1} suffix="%" />
              </Col>
              <Col span={4}>
                <Statistic title="总收益率" value={stats.totalReturn} precision={2} suffix="%" valueStyle={{ color: stats.totalReturn >= 0 ? '#52c41a' : '#ff4d4f' }} />
              </Col>
              <Col span={4}>
                <Statistic title="最大回撤" value={stats.maxDrawdown} precision={2} suffix="%" valueStyle={{ color: '#ff4d4f' }} />
              </Col>
            </Row>
          </Card>

          {/* 交易记录 */}
          <Card title="交易记录">
            <Table
              dataSource={steps.filter(s => s.action !== 'hold')}
              columns={tradeColumns}
              rowKey="step"
              pagination={{ current: page, pageSize, showSizeChanger: true, showTotal: (t: number) => `共 ${t} 条`, onChange: (p: number, ps: number) => { setPage(p); setPageSize(ps) } }}
              size="small"
              scroll={{ x: 900 }}
              rowClassName={(record) => record.step === state.currentStep ? 'ant-table-row-selected' : ''}
              onRow={(record) => ({
                onClick: () => replayEngine.goToStep(record.step),
                style: { cursor: 'pointer' },
              })}
            />
          </Card>
        </>
      )}
    </div>
  )
}
