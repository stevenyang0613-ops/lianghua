/**
 * 自动交易配置页面
 */

import { useEffect, useState, useCallback } from 'react'
import { Card, Switch, Button, Space, Typography, Row, Col, Statistic, Tag, Table, InputNumber, Select, Input, List, Alert, Popconfirm, message, Modal, TimePicker } from 'antd'
import { RobotOutlined, PauseCircleOutlined, HistoryOutlined, CheckCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import { getAutoTradeConfig, updateAutoTradeConfig, getAutoTradeOrders, getAutoTradeLogs, clearAutoTradeLogs, getAutoTradeStats, batchExecutePendingSignals, type AutoTradeConfig, type AutoTradeOrder, type AutoTradeLog, VALID_STRATEGIES } from '../utils/autoTrader'
import type { ColumnsType } from 'antd/es/table'
import dayjs from 'dayjs'
import { fmt } from '../utils/format'
import { useSignalStore } from '../stores/useSignalStore'
import { setActiveStrategies, fetchAvailableSignalsStrategies } from '../services/api'

const { Title, Text, Paragraph } = Typography

// 与后端 STRATEGY_REGISTRY 对齐的合法策略列表
const STRATEGY_OPTIONS = [
  { value: 'dual_low', label: '双低策略' },
  { value: 'low_premium', label: '低溢价策略' },
  { value: 'momentum', label: '动量策略' },
  { value: 'xuanji_v8', label: '璇玑V8策略' },
  { value: 'multi_factor', label: '多因子策略' },
  { value: 'xibu_seven', label: '西部七维策略' },
  { value: 'xuanji_twelve', label: '璇玑十二因子' },
  { value: 'sector_rotation', label: '板块轮动策略' },
  { value: 'fusion', label: '融合策略' },
]

export default function AutoTrade() {
  const [config, setConfig] = useState<AutoTradeConfig>(() => getAutoTradeConfig())
  const [orders, setOrders] = useState<AutoTradeOrder[]>([])
  const [logs, setLogs] = useState<AutoTradeLog[]>([])
  const [stats, setStats] = useState(getAutoTradeStats())
  const [logsVisible, setLogsVisible] = useState(false)
  const [batchLoading, setBatchLoading] = useState(false)
  const [availableStrategies, setAvailableStrategies] = useState<string[]>([])

  const signalStore = useSignalStore()

  const loadData = useCallback(() => {
    setConfig(getAutoTradeConfig())
    setOrders(getAutoTradeOrders())
    setLogs(getAutoTradeLogs())
    setStats(getAutoTradeStats())
  }, [])

  useEffect(() => {
    loadData()

    // 检查 localStorage 原始策略是否被回退，显示一次提示
    try {
      const raw = localStorage.getItem('auto_trade_config')
      if (raw) {
        const parsed = JSON.parse(raw)
        if (parsed.strategy && parsed.strategy !== config.strategy && !VALID_STRATEGIES.has(parsed.strategy)) {
          message.warning(
            `检测到非法策略 key「${parsed.strategy}」已自动回退为「${STRATEGY_OPTIONS.find(o => o.value === config.strategy)?.label || config.strategy}」`
          )
        }
      }
    } catch { /* ignore parse errors */ }

    // 加载后端可用策略列表，并同步到信号系统
    fetchAvailableSignalsStrategies().then((data) => {
      const ids = data.strategies.map(s => s.id)
      setAvailableStrategies(ids)
    }).catch(() => {
      // 后端不可用时回退到硬编码列表
      setAvailableStrategies(STRATEGY_OPTIONS.map(o => o.value))
    })
  }, [loadData])

  // 当自动交易页面切换策略时，同步到信号系统的活跃策略（追加模式，不覆盖其他策略）
  useEffect(() => {
    if (!availableStrategies.length) return

    const strategy = config.strategy
    if (!availableStrategies.includes(strategy)) return

    // 追加模式：如果信号系统的活跃策略不包含当前策略，则追加而非替换
    const signalActive = signalStore.activeStrategies
    if (!signalActive.includes(strategy)) {
      const combined = [...signalActive, strategy]
      setActiveStrategies(combined).catch(() => { /* ignore */ })
    }
  }, [config.strategy, availableStrategies, signalStore.activeStrategies])

  const handleToggle = (checked: boolean) => {
    const newConfig = updateAutoTradeConfig({ enabled: checked })
    loadData()

    // 如果策略被自动回退，显示警告
    if (newConfig.strategy !== config.strategy && !VALID_STRATEGIES.has(config.strategy)) {
      message.warning(`策略配置已回退为「${STRATEGY_OPTIONS.find(o => o.value === newConfig.strategy)?.label || newConfig.strategy}」`)
    }

    message.success(checked ? '自动交易已启用' : '自动交易已禁用')
  }

  const handleConfigChange = (key: keyof AutoTradeConfig, value: unknown) => {
    const newConfig = updateAutoTradeConfig({ [key]: value })
    loadData()

    // 策略切换时，追加到信号系统的活跃策略（不覆盖其他策略）
    if (key === 'strategy' && typeof value === 'string') {
      const signalActive = signalStore.activeStrategies
      if (!signalActive.includes(value)) {
        const combined = [...signalActive, value]
        setActiveStrategies(combined).catch(() => {
          message.warning('信号系统策略同步失败')
        })
      }
    }

    // 如果策略被自动回退，显示警告
    if (key === 'strategy' && newConfig.strategy !== value) {
      message.warning(`策略已回退为「${STRATEGY_OPTIONS.find(o => o.value === newConfig.strategy)?.label || newConfig.strategy}」`)
    }
  }

  const handleClearLogs = () => {
    clearAutoTradeLogs()
    loadData()
    message.success('日志已清除')
  }

  const handleBatchExecute = async () => {
    const pendingCount = orders.filter(o => o.status === 'pending').length
    if (pendingCount === 0) {
      message.info('没有待执行的订单')
      return
    }
    setBatchLoading(true)
    try {
      const result = await batchExecutePendingSignals(config)
      loadData()
      if (result.executed > 0) {
        message.success(`成功执行 ${result.executed} 笔订单`)
      }
      if (result.failed > 0) {
        message.warning(`${result.failed} 笔订单执行失败`)
      }
    } catch (e) {
      message.error(`批量执行失败: ${e}`)
    } finally {
      setBatchLoading(false)
    }
  }

  const orderColumns: ColumnsType<AutoTradeOrder> = [
    {
      title: '时间',
      dataIndex: 'createdAt',
      width: 150,
      render: (v: number) => new Date(v).toLocaleString('zh-CN'),
    },
    {
      title: '代码',
      dataIndex: 'code',
      width: 80,
    },
    {
      title: '名称',
      dataIndex: 'name',
      width: 100,
    },
    {
      title: '操作',
      dataIndex: 'action',
      width: 60,
      render: (v: string) => (
        <Tag color={v === 'buy' ? 'green' : 'red'}>{v === 'buy' ? '买入' : '卖出'}</Tag>
      ),
    },
    {
      title: '价格',
      dataIndex: 'price',
      width: 80,
      render: (v: number) => fmt(v),
    },
    {
      title: '数量',
      dataIndex: 'quantity',
      width: 60,
    },
    {
      title: '置信度',
      dataIndex: 'confidence',
      width: 80,
      render: (v: number) => `${fmt(v == null ? null : v * 100, 0)}%`,
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 80,
      render: (v: string) => (
        <Tag color={v === 'executed' ? 'success' : v === 'pending' ? 'processing' : 'error'}>
          {v === 'executed' ? '已执行' : v === 'pending' ? '待执行' : v === 'cancelled' ? '已取消' : '失败'}
        </Tag>
      ),
    },
    {
      title: '策略',
      dataIndex: 'strategy',
      width: 120,
      render: (v: string) => {
        const label = STRATEGY_OPTIONS.find(o => o.value === v)?.label || v
        return <Tag>{label}</Tag>
      },
    },
  ]

  const statusColors = {
    info: 'blue',
    warning: 'orange',
    error: 'red',
    trade: 'green',
  }

  const pendingCount = orders.filter(o => o.status === 'pending').length

  return (
    <div style={{ padding: 16, maxWidth: 1400, margin: '0 auto' }}>
      <Title level={4}><RobotOutlined style={{ marginRight: 8 }} />自动交易</Title>

      {/* 警告提示 */}
      {!config.autoExecute && (
        <Alert
          type="info"
          message="安全模式"
          description="当前为安全模式，交易信号将生成订单但不会自动执行。如需自动执行，请在下方开启「自动执行」选项。"
          showIcon
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 状态概览 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col span={6}>
            <div style={{ textAlign: 'center' }}>
              <Switch
                checked={config.enabled}
                onChange={handleToggle}
                checkedChildren="运行中"
                unCheckedChildren="已停止"
                style={{ marginBottom: 8 }}
              />
              <Paragraph style={{ marginBottom: 0 }}>
                {config.enabled ? <CheckCircleOutlined style={{ color: '#52c41a' }} /> : <PauseCircleOutlined style={{ color: '#999' }} />}
                <Text style={{ marginLeft: 4 }}>{config.enabled ? '自动交易运行中' : '自动交易已停止'}</Text>
              </Paragraph>
            </div>
          </Col>
          <Col span={18}>
            <Row gutter={16}>
              <Col span={4}>
                <Statistic title="总订单" value={stats.totalOrders} />
              </Col>
              <Col span={4}>
                <Statistic title="已执行" value={stats.executedOrders} valueStyle={{ color: '#52c41a' }} />
              </Col>
              <Col span={4}>
                <Statistic title="待执行" value={stats.pendingOrders} valueStyle={{ color: '#1890ff' }} />
              </Col>
              <Col span={4}>
                <Statistic title="失败" value={stats.failedOrders} valueStyle={{ color: stats.failedOrders > 0 ? '#ff4d4f' : undefined }} />
              </Col>
              <Col span={4}>
                <Statistic title="买入/卖出" value={`${stats.buyOrders}/${stats.sellOrders}`} />
              </Col>
              <Col span={4}>
                <Statistic title="平均置信度" value={fmt((stats.avgConfidence ?? 0) * 100, 0)} suffix="%" />
              </Col>
            </Row>
          </Col>
        </Row>
      </Card>

      {/* 配置面板 */}
      <Card title="交易配置" style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]}>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>交易策略</Text>
            </div>
            <Select
              style={{ width: '100%' }}
              value={config.strategy}
              onChange={(v) => handleConfigChange('strategy', v)}
              options={STRATEGY_OPTIONS}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>最大持仓数量</Text>
            </div>
            <InputNumber
              style={{ width: '100%' }}
              min={1}
              max={50}
              value={config.maxPosition}
              onChange={(v) => handleConfigChange('maxPosition', v)}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>最大待执行订单</Text>
            </div>
            <InputNumber
              style={{ width: '100%' }}
              min={1}
              max={20}
              value={config.maxOrders}
              onChange={(v) => handleConfigChange('maxOrders', v)}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>止损线 (%)</Text>
            </div>
            <InputNumber
              style={{ width: '100%' }}
              min={-50}
              max={0}
              value={config.stopLoss}
              onChange={(v) => handleConfigChange('stopLoss', v)}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>止盈线 (%)</Text>
            </div>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              max={100}
              value={config.takeProfit}
              onChange={(v) => handleConfigChange('takeProfit', v)}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>最小置信度</Text>
            </div>
            <InputNumber
              style={{ width: '100%' }}
              min={0}
              max={1}
              step={0.1}
              value={config.minConfidence}
              onChange={(v) => handleConfigChange('minConfidence', v)}
            />
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>交易时段</Text>
            </div>
            <Space>
              <TimePicker
                format="HH:mm"
                value={dayjs(config.tradingHours.start, 'HH:mm')}
                onChange={(v) => handleConfigChange('tradingHours', { ...config.tradingHours, start: v?.format('HH:mm') || '09:30' })}
              />
              <Text>-</Text>
              <TimePicker
                format="HH:mm"
                value={dayjs(config.tradingHours.end, 'HH:mm')}
                onChange={(v) => handleConfigChange('tradingHours', { ...config.tradingHours, end: v?.format('HH:mm') || '15:00' })}
              />
            </Space>
          </Col>
          <Col span={8}>
            <div style={{ marginBottom: 8 }}>
              <Text>排除标的（逗号分隔）</Text>
            </div>
            <Input
              placeholder="如：110001,110002"
              value={config.excludeCodes.join(',')}
              onChange={(e) => handleConfigChange('excludeCodes', e.target.value.split(',').filter(Boolean))}
            />
          </Col>
          <Col span={8}>
            <Space direction="vertical">
              <Switch
                checked={config.autoExecute}
                onChange={(v) => handleConfigChange('autoExecute', v)}
                checkedChildren="自动执行"
                unCheckedChildren="人工确认"
              />
              <Switch
                checked={config.trailingStop}
                onChange={(v) => handleConfigChange('trailingStop', v)}
              />
              <Switch
                checked={config.notifyOnTrade}
                onChange={(v) => handleConfigChange('notifyOnTrade', v)}
              />
            </Space>
          </Col>
        </Row>
      </Card>

      {/* 订单列表 */}
      <Card
        title="订单记录"
        extra={
          <Space>
            {pendingCount > 0 && (
              <Button
                icon={<ThunderboltOutlined />}
                type="primary"
                loading={batchLoading}
                onClick={handleBatchExecute}
              >
                批量执行 ({pendingCount})
              </Button>
            )}
            <Button icon={<HistoryOutlined />} onClick={() => setLogsVisible(true)}>
              查看日志
            </Button>
          </Space>
        }
      >
        {orders.length === 0 ? (
          <Paragraph type="secondary" style={{ textAlign: 'center', padding: 40 }}>
            暂无订单记录
          </Paragraph>
        ) : (
          <Table
            dataSource={orders.slice(0, 20)}
            columns={orderColumns}
            rowKey="id"
            pagination={false}
            size="small"
            scroll={{ x: 900 }}
          />
        )}
      </Card>

      {/* 日志弹窗 */}
      <Modal
        title="交易日志"
        open={logsVisible}
        onCancel={() => setLogsVisible(false)}
        footer={[
          <Popconfirm key="clear" title="确定清除所有日志？" onConfirm={handleClearLogs}>
            <Button danger>清除日志</Button>
          </Popconfirm>,
          <Button key="close" onClick={() => setLogsVisible(false)}>
            关闭
          </Button>,
        ]}
        width={700}
      >
        <List
          dataSource={logs.slice(0, 50)}
          renderItem={(log) => (
            <List.Item>
              <List.Item.Meta
                avatar={
                  <Tag color={statusColors[log.type]}>
                    {log.type === 'info' ? '信息' : log.type === 'warning' ? '警告' : log.type === 'error' ? '错误' : '交易'}
                  </Tag>
                }
                title={log.message}
                description={new Date(log.timestamp).toLocaleString('zh-CN')}
              />
            </List.Item>
          )}
        />
      </Modal>
    </div>
  )
}
