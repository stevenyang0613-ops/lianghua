/**
 * 数据回放页面
 */

import { useEffect, useState, useCallback } from 'react'
import { Card, Button, Space, Slider, Typography, Row, Col, Statistic, Select, DatePicker, Empty, Spin, Table } from 'antd'
import { PlayCircleOutlined, PauseCircleOutlined, StepBackwardOutlined, StepForwardOutlined, StopOutlined, FastForwardOutlined, BackwardOutlined } from '@ant-design/icons'
import { dataPlayer, generateMockFrames, type MarketFrame, type PlayerState, type DataPlayerConfig } from '../utils/dataPlayer'
import dayjs from 'dayjs'
import echarts from '../utils/echarts'
import { useRef } from 'react'

const { Title, Text } = Typography
const { RangePicker } = DatePicker

export default function DataPlayer() {
  const [config, setConfig] = useState<DataPlayerConfig>({
    dataType: 'day',
    startDate: '2024-01-01',
    endDate: '2024-12-31',
    speed: 1,
    autoPlay: false,
    showIndicators: true,
    initialCash: 1000000,
  })
  const [frames, setFrames] = useState<MarketFrame[]>([])
  const [currentFrame, setCurrentFrame] = useState<MarketFrame | null>(null)
  const [state, setState] = useState<PlayerState>({
    isPlaying: false,
    isPaused: false,
    currentIndex: 0,
    totalFrames: 0,
    currentDate: '',
    currentTime: '',
    progress: 0,
  })
  const [loading, setLoading] = useState(false)
  const chartRef = useRef<HTMLDivElement>(null)
  const chartInstance = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    const unsubscribeFrame = dataPlayer.onFrame((frame, st) => {
      setCurrentFrame(frame)
      setState(st)
      updateChart(frame)
    })

    const unsubscribeState = dataPlayer.onStateChange(setState)

    return () => {
      unsubscribeFrame()
      unsubscribeState()
    }
  }, [])

  useEffect(() => {
    if (chartRef.current && !chartInstance.current) {
      chartInstance.current = echarts.init(chartRef.current, 'dark')
    }
  }, [frames.length > 0])

  const updateChart = (frame: MarketFrame | null) => {
    if (!chartInstance.current || !frame) return

    const startIdx = Math.max(0, state.currentIndex - 50)
    const visibleFrames = frames.slice(startIdx, state.currentIndex + 1)

    const option: echarts.EChartsCoreOption = {
      backgroundColor: 'transparent',
      animation: false,
      xAxis: {
        type: 'category',
        data: visibleFrames.map(f => f.date),
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#aaa', fontSize: 10 },
      },
      yAxis: {
        type: 'value',
        scale: true,
        axisLine: { lineStyle: { color: '#333' } },
        axisLabel: { color: '#aaa' },
        splitLine: { lineStyle: { color: '#222' } },
      },
      series: [
        {
          type: 'candlestick',
          data: visibleFrames.map(f => [f.open, f.close, f.low, f.high]),
          itemStyle: {
            color: '#ef5350',
            color0: '#26a69a',
            borderColor: '#ef5350',
            borderColor0: '#26a69a',
          },
        },
        {
          type: 'line',
          data: visibleFrames.map(f => f.close),
          smooth: true,
          lineStyle: { width: 1, color: '#1890ff' },
          symbol: 'none',
        },
      ],
      grid: {
        left: 60,
        right: 40,
        top: 20,
        bottom: 30,
      },
    }

    chartInstance.current.setOption(option, true)
  }

  const handleLoadData = useCallback(() => {
    setLoading(true)
    setTimeout(() => {
      const data = generateMockFrames(config)
      setFrames(data)
      dataPlayer.loadFrames(data)
      setLoading(false)
    }, 500)
  }, [config])

  const handlePlay = () => {
    if (state.isPlaying) {
      dataPlayer.pause()
    } else {
      dataPlayer.play(config.speed)
    }
  }

  const handleStop = () => {
    dataPlayer.stop()
    setCurrentFrame(frames[0] || null)
  }

  const handleSpeedChange = (speed: number) => {
    setConfig({ ...config, speed })
    if (state.isPlaying) {
      dataPlayer.pause()
      dataPlayer.play(speed)
    }
  }

  const handleProgressChange = (value: number) => {
    dataPlayer.goToFrame(value)
  }

  const bidAskColumns = [
    { title: '买价', dataIndex: 'price', width: 80, render: (v: number) => v.toFixed(2) },
    { title: '买量', dataIndex: 'volume', width: 80 },
  ]

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}>数据回放</Title>

      {/* 控制面板 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col>
            <Space>
              <Select
                value={config.dataType}
                onChange={(v) => setConfig({ ...config, dataType: v })}
                style={{ width: 100 }}
                options={[
                  { value: 'day', label: '日K' },
                  { value: 'minute', label: '分钟' },
                  { value: 'tick', label: 'Tick' },
                ]}
              />
              <RangePicker
                value={[config.startDate, config.endDate].map(d => d ? dayjs(d) : null) as [dayjs.Dayjs, dayjs.Dayjs]}
                onChange={(dates) => {
                  if (dates && dates[0] && dates[1]) {
                    setConfig({
                      ...config,
                      startDate: dates[0].format('YYYY-MM-DD'),
                      endDate: dates[1].format('YYYY-MM-DD'),
                    })
                  }
                }}
              />
              <Button type="primary" onClick={handleLoadData} loading={loading}>
                加载数据
              </Button>
            </Space>
          </Col>
          {frames.length > 0 && (
            <>
              <Col>
                <Space>
                  <Button icon={<StopOutlined />} onClick={handleStop}>停止</Button>
                  <Button icon={<BackwardOutlined />} onClick={() => dataPlayer.rewind(10)} />
                  <Button icon={<StepBackwardOutlined />} onClick={() => dataPlayer.prevFrame()} />
                  <Button
                    type="primary"
                    icon={state.isPlaying ? <PauseCircleOutlined /> : <PlayCircleOutlined />}
                    onClick={handlePlay}
                  >
                    {state.isPlaying ? '暂停' : '播放'}
                  </Button>
                  <Button icon={<StepForwardOutlined />} onClick={() => dataPlayer.nextFrame()} />
                  <Button icon={<FastForwardOutlined />} onClick={() => dataPlayer.fastForward(10)} />
                </Space>
              </Col>
              <Col>
                <Space>
                  <Text>速度:</Text>
                  <Select
                    value={config.speed}
                    onChange={handleSpeedChange}
                    style={{ width: 80 }}
                    options={[
                      { value: 0.5, label: '0.5x' },
                      { value: 1, label: '1x' },
                      { value: 2, label: '2x' },
                      { value: 5, label: '5x' },
                      { value: 10, label: '10x' },
                    ]}
                  />
                </Space>
              </Col>
              <Col flex="auto">
                <Slider
                  min={0}
                  max={state.totalFrames - 1}
                  value={state.currentIndex}
                  onChange={handleProgressChange}
                  tooltip={{ formatter: (v) => frames[v || 0]?.date }}
                />
              </Col>
            </>
          )}
        </Row>
      </Card>

      {loading ? (
        <Spin style={{ display: 'flex', justifyContent: 'center', padding: 100 }} />
      ) : frames.length === 0 ? (
        <Empty description="请选择时间范围并加载数据" style={{ padding: 100 }} />
      ) : (
        <>
          {/* 当前帧信息 */}
          {currentFrame && (
            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={4}>
                <Card>
                  <Statistic title="日期" value={currentFrame.date} valueStyle={{ fontSize: 14 }} />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="开盘" value={currentFrame.open} precision={2} />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="最高" value={currentFrame.high} precision={2} valueStyle={{ color: '#ef5350' }} />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="最低" value={currentFrame.low} precision={2} valueStyle={{ color: '#26a69a' }} />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="收盘" value={currentFrame.close} precision={2} />
                </Card>
              </Col>
              <Col span={4}>
                <Card>
                  <Statistic title="成交量" value={currentFrame.volume} />
                </Card>
              </Col>
            </Row>
          )}

          {/* K线图 */}
          <Card style={{ marginBottom: 16 }}>
            <div ref={chartRef} style={{ height: 400 }} />
          </Card>

          {/* 五档行情 */}
          {currentFrame && (
            <Row gutter={16}>
              <Col span={12}>
                <Card title="买盘" size="small">
                  <Table
                    dataSource={currentFrame.bids.map((b, i) => ({ ...b, key: i }))}
                    columns={bidAskColumns}
                    pagination={false}
                    size="small"
                  />
                </Card>
              </Col>
              <Col span={12}>
                <Card title="卖盘" size="small">
                  <Table
                    dataSource={currentFrame.asks.map((a, i) => ({ ...a, key: i }))}
                    columns={bidAskColumns}
                    pagination={false}
                    size="small"
                  />
                </Card>
              </Col>
            </Row>
          )}

          {/* 进度信息 */}
          <Card style={{ marginTop: 16 }}>
            <Row gutter={16}>
              <Col span={8}>
                <Text>当前帧: {state.currentIndex + 1} / {state.totalFrames}</Text>
              </Col>
              <Col span={8}>
                <Text>进度: {state.progress.toFixed(1)}%</Text>
              </Col>
              <Col span={8}>
                <Text>状态: {state.isPlaying ? '播放中' : state.isPaused ? '已暂停' : '已停止'}</Text>
              </Col>
            </Row>
          </Card>
        </>
      )}
    </div>
  )
}

