import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Card, Row, Col, Statistic, Button, Tabs, Table, Space, message, Spin, Tag, Empty, Form, InputNumber, Select, Input, Popconfirm, Alert, Typography, Steps } from 'antd'
import { PlayCircleOutlined, PauseCircleOutlined, ReloadOutlined, RiseOutlined, FallOutlined, FundOutlined, SettingOutlined, DeleteOutlined, RocketOutlined, ThunderboltOutlined, LineChartOutlined } from '@ant-design/icons'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { fetchPaperAccounts, createPaperAccount, startPaperAccount, stopPaperAccount, resetPaperAccount, fetchPaperPositions, fetchPaperOrders, fetchPaperEquityCurve, fetchPaperSignals, updatePaperParams, deletePaperAccount, forceRebalancePaperAccount, fetchStrategies } from '../services/api'
import { useEverRun } from '../hooks/useEverRun'
import { useElectron } from '../hooks/useElectron'

// StrategyInfo 用于动态 tab
interface StrategyInfo { id: string; name: string; description?: string }

echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

interface ParamDef { name: string; label: string; type: string; default: any; min_val?: number; max_val?: number; options?: string[]; description?: string }
interface PaperAccountData { id: string; strategy_id: string; strategy_name: string; is_running: boolean; initial_cash: number; total_asset: number; cash: number; market_value: number; total_profit: number; total_profit_pct: number; params: Record<string, any>; param_defs: ParamDef[]; created_at: string; trade_day_count: number; rebalance_days: number; next_rebalance_idx?: number }
interface PositionData { code: string; name: string; volume: number; cost_price: number; current_price: number; market_value: number; profit_pct: number; profit_amount: number }
interface OrderData { id: string; code: string; name: string; side: string; price: number; volume: number; filled_volume: number; status: string; created_at: string; reject_reason: string }
interface EquityPoint { ts: string; total_asset: number; cash: number; market_value: number; total_profit: number; total_profit_pct: number }
interface SignalData { id: string; code: string; name: string; action: string; price: number; reason: string; confidence: number; ts: string; executed: boolean }

function StrategyTab({ strategyId, accounts, onRefresh }: { strategyId: string; accounts: PaperAccountData[]; onRefresh: () => void }) {
  const account = accounts.find(a => a.strategy_id === strategyId)
  const [positions, setPositions] = useState<PositionData[]>([])
  const [orders, setOrders] = useState<OrderData[]>([])
  const [equity, setEquity] = useState<EquityPoint[]>([])
  const [signals, setSignals] = useState<SignalData[]>([])
  const [loading, setLoading] = useState(false)
  const [subTab, setSubTab] = useState('positions')
  const [paramsForm] = Form.useForm()
  const [createForm] = Form.useForm()
  const [creating, setCreating] = useState(false)
  const accountId = account?.id

  const isMountedRef = useRef(true)

  const loadData = useCallback(async () => {
    if (!isMountedRef.current) return
    if (!accountId) return
    setLoading(true)
    try {
      const [posRes, ordRes, eqRes, sigRes] = await Promise.all([
        fetchPaperPositions(accountId), fetchPaperOrders(accountId),
        fetchPaperEquityCurve(accountId), fetchPaperSignals(accountId),
      ])
      if (!isMountedRef.current) return
      setPositions(posRes.positions || [])
      setOrders(ordRes.orders || [])
      setEquity(eqRes.points || [])
      setSignals(sigRes.signals || [])
    } catch (e: unknown) { console.warn('Load paper trade data failed:', e) }
    finally { if (isMountedRef.current) setLoading(false) }
  }, [accountId])

  useEffect(() => {
    isMountedRef.current = true
    if (accountId) {
      loadData()
      const t = setInterval(loadData, 30000)
      return () => { isMountedRef.current = false; clearInterval(t) }
    }
    return () => { isMountedRef.current = false }
  }, [loadData, accountId])
  useEffect(() => { if (account?.params) paramsForm.setFieldsValue(account.params) }, [account?.params, paramsForm])

  const handleStart = async () => {
    if (!accountId) return
    try { await startPaperAccount(accountId); message.success('模拟交易已启动'); onRefresh() }
    catch (e: unknown) { message.error('启动失败: ' + (e instanceof Error ? e.message : String(e))) }
  }
  const handleStop = async () => {
    if (!accountId) return
    try { await stopPaperAccount(accountId); message.success('模拟交易已停止'); onRefresh() }
    catch (e: unknown) { message.error('停止失败: ' + (e instanceof Error ? e.message : String(e))) }
  }
  const handleReset = async () => {
    if (!accountId) return
    try { await resetPaperAccount(accountId); message.success('账户已重置'); onRefresh(); loadData() }
    catch (e: unknown) { message.error('重置失败: ' + (e instanceof Error ? e.message : String(e))) }
  }
  const handleForceRebalance = async () => {
    if (!accountId) return
    try {
      const result = await forceRebalancePaperAccount(accountId)
      if (result.status === 'ok') {
        const posCount = result.positions?.length || 0
        const sigCount = result.signals?.length || 0
        message.success(`立即调仓成功！产生 ${sigCount} 个信号，买入 ${posCount} 只债券`)
        onRefresh()
        loadData()
      } else {
        message.info(`立即调仓：${result.message || '策略未产生买入信号'}`)
      }
    } catch (e: unknown) {
      message.error('调仓失败: ' + (e instanceof Error ? e.message : String(e)))
    }
  }
  const handleDelete = async () => {
    if (!accountId) return
    try { await deletePaperAccount(accountId); message.success('账户已删除'); onRefresh() }
    catch (e: unknown) { message.error('删除失败: ' + (e instanceof Error ? e.message : String(e))) }
  }
  const handleSaveParams = async () => {
    if (!accountId) return
    try {
      const values = await paramsForm.validateFields()
      await updatePaperParams(accountId, values)
      message.success('参数已保存')
    } catch (e: unknown) { message.error('保存参数失败: ' + (e instanceof Error ? e.message : String(e))) }
  }
  const handleCreate = async () => {
    try {
      const values = await createForm.validateFields()
      setCreating(true)
      await createPaperAccount({ strategy_id: strategyId, initial_cash: values.initial_cash })
      message.success('账户创建成功')
      createForm.resetFields()
      onRefresh()
    } catch (e: unknown) {
      message.error('创建失败: ' + (e instanceof Error ? e.message : String(e)))
    } finally {
      setCreating(false)
    }
  }

  // 新手引导：账户从未运行过且无数据时显示
  // useEverRun hook：后端驱动优先（account.created_at / is_running），localStorage 辅助缓存
  // 建议10: strategyId 为空时使用固定 key，避免 undefined 导致多策略共享标记
  // ⚠️ 必须放在 if (!account) 之前，确保每次渲染都调用相同数量的 hooks（React Hooks 规则）
  const hasEverRun = useEverRun(
    strategyId ? `lianghua_paper_trade_ever_run_${strategyId}` : 'lianghua_paper_trade_ever_run_unknown',
    [!!account?.created_at, account?.is_running ?? false]
  )

  if (!account) {
    return (
      <Card>
        <Empty
          description="账户未创建"
          image={Empty.PRESENTED_IMAGE_SIMPLE}
        >
          <Form form={createForm} layout="inline" style={{ marginTop: 16 }} initialValues={{ initial_cash: 100000000 }}>
            <Form.Item
              name="initial_cash"
              label="初始资金"
              rules={[{ required: true, message: '请输入初始资金' }]}
            >
              <InputNumber
                style={{ width: 240 }}
                min={10000}
                step={1000000}
                formatter={(value: number | undefined) => `¥ ${value}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}
                parser={(value: string | undefined) => Number(value?.replace(/[¥,\s]/g, '') || 0)}
              />
            </Form.Item>
            <Form.Item>
              <Button type="primary" onClick={handleCreate} loading={creating} icon={<RocketOutlined />}>
                创建账户
              </Button>
            </Form.Item>
          </Form>
        </Empty>
      </Card>
    )
  }

  const showOnboarding = !hasEverRun && !account.is_running && positions.length === 0 && signals.length === 0 && orders.length === 0 && equity.length === 0

  const profitColor = account.total_profit >= 0 ? '#cf1322' : '#3f8600'
  const equityOption = {
    tooltip: { trigger: 'axis' as const },
    legend: { data: ['总资产'] },
    grid: { left: 60, right: 20, top: 30, bottom: 30 },
    xAxis: { type: 'category' as const, data: equity.map(p => {
      // 格式化为 MM-DD HH:mm
      const s = p.ts || ''
      if (s.length >= 16) return s.slice(5, 16).replace('T', ' ')
      return s.slice(0, 16)
    }) },
    yAxis: { type: 'value' as const, scale: true },
    series: [{ name: '总资产', type: 'line', data: equity.map(p => p.total_asset), smooth: true,
      lineStyle: { width: 2 }, itemStyle: { color: '#1890ff' },
      areaStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
        { offset: 0, color: 'rgba(24,144,255,0.3)' }, { offset: 1, color: 'rgba(24,144,255,0.02)' }
      ]) },
    }],
  }

  const posColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    { title: '数量', dataIndex: 'volume', key: 'volume', width: 70, align: 'right' as const },
    { title: '成本', dataIndex: 'cost_price', key: 'cost_price', width: 70, align: 'right' as const, render: (v: number) => v?.toFixed(2) },
    { title: '现价', dataIndex: 'current_price', key: 'current_price', width: 70, align: 'right' as const, render: (v: number) => v?.toFixed(2) },
    { title: '市值', dataIndex: 'market_value', key: 'market_value', width: 90, align: 'right' as const, render: (v: number) => v?.toFixed(0) },
    { title: '盈亏%', dataIndex: 'profit_pct', key: 'profit_pct', width: 80, align: 'right' as const,
      render: (v: number) => <span style={{ color: v >= 0 ? '#cf1322' : '#3f8600' }}>{v >= 0 ? '+' : ''}{v?.toFixed(2)}%</span> },
  ]
  const sigColumns = [
    { title: '时间', dataIndex: 'ts', key: 'ts', width: 140, render: (v: string) => v?.slice(0, 16) },
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name', width: 100 },
    { title: '方向', dataIndex: 'action', key: 'action', width: 60,
      render: (v: string) => <Tag color={v === 'buy' ? 'red' : 'green'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 70, align: 'right' as const, render: (v: number) => v?.toFixed(2) },
    { title: '原因', dataIndex: 'reason', key: 'reason', ellipsis: true },
  ]
  const ordColumns = [
    { title: '时间', dataIndex: 'created_at', key: 'created_at', width: 140, render: (v: string) => v?.slice(0, 16) },
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '方向', dataIndex: 'side', key: 'side', width: 60,
      render: (v: string) => <Tag color={v === 'buy' ? 'red' : 'green'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', key: 'price', width: 70, align: 'right' as const },
    { title: '数量', dataIndex: 'volume', key: 'volume', width: 60, align: 'right' as const },
    { title: '状态', dataIndex: 'status', key: 'status', width: 70,
      render: (v: string) => <Tag color={v === 'filled' ? 'green' : v === 'rejected' ? 'red' : 'blue'}>{v}</Tag> },
  ]

  const paramDefs = account.param_defs || []

  const renderParamInput = (p: ParamDef) => {
    if (p.type === 'select' && p.options) {
      return <Select size="small" style={{ width: 120 }} options={p.options.map(o => ({ value: o, label: o, key: o }))} />
    }
    if (p.type === 'str') {
      return <Input size="small" style={{ width: 120 }} />
    }
    // int / float → InputNumber with min/max
    return (
      <InputNumber
        size="small" style={{ width: 100 }}
        min={p.min_val} max={p.max_val}
        step={p.type === 'int' ? 1 : 0.1}
      />
    )
  }

  return (
    <Spin spinning={loading}>
      {showOnboarding && (
        <Alert
          type="info"
          showIcon
          icon={<RocketOutlined />}
          style={{ marginBottom: 12 }}
          message="欢迎使用模拟交易"
          description={
            <div>
              <Typography.Paragraph style={{ marginBottom: 12, color: 'rgba(0,0,0,0.65)' }}>
                模拟交易会在虚拟账户中自动执行策略信号，无需真实资金即可验证策略效果。
              </Typography.Paragraph>
              <Steps
                size="small"
                current={-1}
                items={[
                  { title: '启动账户', description: '点击上方「启动」按钮开始运行策略', icon: <PlayCircleOutlined /> },
                  { title: '等待信号', description: '策略自动检测买卖信号（约5-10分钟）', icon: <ThunderboltOutlined /> },
                  { title: '查看收益', description: '在权益曲线和持仓中查看运行效果', icon: <LineChartOutlined /> },
                ]}
              />
            </div>
          }
        />
      )}
      <Row gutter={16}>
        <Col xs={24} md={8}>
          <Card title="账户概览" size="small" extra={
            <Space>
              {!account.is_running ? (
                <Button type="primary" size="small" icon={<PlayCircleOutlined />} onClick={handleStart}>启动</Button>
              ) : (
                <Button size="small" icon={<PauseCircleOutlined />} onClick={handleStop} danger>停止</Button>
              )}
              <Button size="small" icon={<ReloadOutlined />} onClick={handleReset}>重置</Button>
              <Button type="primary" size="small" icon={<ThunderboltOutlined />} onClick={handleForceRebalance}
                style={{ background: '#fa8c16', borderColor: '#fa8c16' }}>立即调仓</Button>
              <Popconfirm title="确定删除该模拟交易账户？" onConfirm={handleDelete} okText="确定" cancelText="取消">
                <Button size="small" icon={<DeleteOutlined />} danger>删除</Button>
              </Popconfirm>
            </Space>
          }>
            <Statistic title="总资产" value={account.total_asset} precision={2} prefix="¥" valueStyle={{ color: profitColor, fontSize: 14 }} />
            <Row gutter={16} style={{ marginTop: 12 }}>
              <Col span={12}><Statistic title="可用资金" value={account.cash} precision={2} prefix="¥" valueStyle={{ fontSize: 14 }} /></Col>
              <Col span={12}><Statistic title="持仓市值" value={account.market_value} precision={2} prefix="¥" valueStyle={{ fontSize: 14 }} /></Col>
            </Row>
            <Row gutter={16} style={{ marginTop: 8 }}>
              <Col span={12}>
                <Statistic title="总收益" value={account.total_profit} precision={2}
                  prefix={account.total_profit >= 0 ? <RiseOutlined /> : <FallOutlined />}
                  valueStyle={{ color: profitColor, fontSize: 14 }} />
              </Col>
              <Col span={12}>
                <Statistic title="收益率" value={account.total_profit_pct} precision={2} suffix="%" valueStyle={{ color: profitColor, fontSize: 14 }} />
              </Col>
            </Row>
            <div style={{ marginTop: 8 }}>
              <Tag color={account.is_running ? 'green' : 'default'}>{account.is_running ? '运行中' : '已停止'}</Tag>
              <span style={{ color: '#999', fontSize: 12 }}>初始资金: ¥{account.initial_cash?.toLocaleString()}</span>
            </div>
            {account.is_running && (
              <div style={{ marginTop: 8, padding: '4px 8px', background: '#f6ffed', borderRadius: 4, border: '1px solid #b7eb8f' }}>
                <span style={{ color: '#52c41a', fontSize: 12 }}>
                  {(() => {
                    const rd = account.rebalance_days || account.params?.rebalance_days || 7
                    const simIdx = account.trade_day_count || 0
                    const nextRebalance = account.next_rebalance_idx ?? simIdx + (rd - simIdx % rd) % rd
                    const d = nextRebalance - simIdx
                    return d <= 1 ? '⚡ 距离调仓还有 1 个交易日' : `⏳ 距离调仓还有 ${d} 个交易日`
                  })()}
                </span>
              </div>
            )}
            {account.is_running && positions.length === 0 && orders.length === 0 && (
              <div style={{ marginTop: 6, padding: '4px 8px', background: '#e6f7ff', borderRadius: 4, border: '1px solid #91d5ff' }}>
                <span style={{ color: '#1890ff', fontSize: 12 }}>
                  💡 策略采用周频调仓，启动后会自动对齐到最近的调仓日。首次调仓通常需要等待 {(() => {
                    const rd = account.rebalance_days || account.params?.rebalance_days || 7
                    const simIdx = account.trade_day_count || 0
                    const nextRebalance = account.next_rebalance_idx ?? simIdx + (rd - simIdx % rd) % rd
                    const d = nextRebalance - simIdx
                    return d <= 1 ? '1' : String(d)
                  })()} 个交易日
                </span>
              </div>
            )}
          </Card>
        </Col>
        <Col xs={24} md={16}>
          <Card title="权益曲线" size="small" extra={<FundOutlined />}>
            {equity.length > 0 ? (
              <ReactEChartsCore echarts={echarts} option={equityOption} style={{ height: 240 }} />
            ) : (
              <Empty description={account.is_running ? "权益数据生成中，通常需要5分钟后显示" : "暂无权益数据，请先启动模拟盘"} image={Empty.PRESENTED_IMAGE_SIMPLE} />
            )}
          </Card>
        </Col>
      </Row>

      <Card title="策略参数" size="small" style={{ marginTop: 12 }} extra={<SettingOutlined />}>
        <Form form={paramsForm} onFinish={handleSaveParams}>
          <Row gutter={[16, 8]}>
            {paramDefs.map(p => (
              <Col xs={24} sm={12} md={8} key={p.name}>
                <Form.Item name={p.name} label={p.label} tooltip={p.description}
                  style={{ marginBottom: 8 }}>
                  {renderParamInput(p)}
                </Form.Item>
              </Col>
            ))}
            {paramDefs.length > 0 && (
              <Col xs={24} sm={12} md={8}>
                <Form.Item style={{ marginBottom: 8 }}>
                  <Button type="primary" size="small" htmlType="submit">保存参数</Button>
                </Form.Item>
              </Col>
            )}
          </Row>
          {paramDefs.length === 0 && <span style={{ color: '#999' }}>使用默认参数</span>}
        </Form>
      </Card>

      <Card size="small" style={{ marginTop: 12 }}>
        <Tabs activeKey={subTab} onChange={setSubTab} items={[
          { key: 'positions', label: `持仓 (${positions.length})`, children: (
            <Table dataSource={positions} columns={posColumns} rowKey="code" size="small" pagination={false} />
          )},
          { key: 'signals', label: `信号 (${signals.length})`, children: (
            <Table dataSource={signals} columns={sigColumns} rowKey="id" size="small" pagination={{ pageSize: 20 }} />
          )},
          { key: 'orders', label: `委托 (${orders.length})`, children: (
            <Table dataSource={orders} columns={ordColumns} rowKey="id" size="small" pagination={{ pageSize: 20 }} />
          )},
        ]} />
      </Card>
    </Spin>
  )
}

export default function PaperTrade() {
  const [accounts, setAccounts] = useState<PaperAccountData[]>([])
  const [refreshFailCount, setRefreshFailCount] = useState(0)
  const [refreshTotalFails, setRefreshTotalFails] = useState(0)
  const [refreshTotalFailThreshold, setRefreshTotalFailThreshold] = useState(30)
  const [warningShownAt, setWarningShownAt] = useState<number | null>(null)
  const [dismissRefreshWarning, setDismissRefreshWarning] = useState(() => {
    try { return localStorage.getItem(storageKey('dismiss_refresh_warning')) === 'true' } catch { return true }
  })
  // 标签页隔离：每个标签页有独立的 load_fail_count，避免跨标签页污染
  const tabIdRef = useRef((() => {
    try {
      let id = sessionStorage.getItem('lianghua_tab_id')
      if (!id) {
        id = 'tab_' + Date.now().toString(36) + '_' + Math.random().toString(36).slice(2, 6)
        sessionStorage.setItem('lianghua_tab_id', id)
      }
      return id
    } catch { return 'tab_default' }
  })())
  const storageKey = useCallback((suffix: string) => `${tabIdRef.current}_${suffix}`, [])
  // 不能加入 useCallback deps（否则无限循环），用 ref 避免 stale closure
  const warningShownRef = useRef(warningShownAt)
  warningShownRef.current = warningShownAt
  // loadAccounts 失败防抖：首次网络抖动不弹错误，连续失败 >=2 次才提示
  // 用 localStorage + 标签页隔离持久化，避免页面刷新后重置，且不同标签页互不干扰
  const loadFailCountRef = useRef((() => {
    try {
      const raw = localStorage.getItem(storageKey('load_fail_count'))
      const ts = localStorage.getItem(storageKey('load_fail_ts'))
      if (!raw || !ts) return 0
      const age = Date.now() - Number(ts)
      if (age > 5 * 60 * 1000) return 0  // 超过 5 分钟过期重置
      return Number(raw)
    } catch { return 0 }
  })())
  const { isElectron, showNotification, restartBackend } = useElectron()

  // 清理其他标签页过期的 localStorage key（避免累积废弃 key）
  useEffect(() => {
    try {
      const now = Date.now()
      const expireMs = 5 * 60 * 1000
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i)
        if (!key) continue
        if (key.endsWith('_load_fail_ts')) {
          const ts = Number(localStorage.getItem(key))
          if (!isNaN(ts) && now - ts > expireMs) {
            const prefix = key.replace('_load_fail_ts', '')
            localStorage.removeItem(key)
            localStorage.removeItem(prefix + '_load_fail_count')
            localStorage.removeItem(prefix + '_dismiss_refresh_warning')
          }
        }
      }
    } catch { /* ignore */ }
    // 卸载时清理当前标签页的 key（避免关闭标签页后残留 5 分钟）
    return () => {
      try {
        const prefix = tabIdRef.current
        localStorage.removeItem(`${prefix}_load_fail_ts`)
        localStorage.removeItem(`${prefix}_load_fail_count`)
        localStorage.removeItem(`${prefix}_dismiss_refresh_warning`)
      } catch { /* ignore */ }
    }
  }, [])

  // setState 函数是稳定引用，无需列入 useCallback 依赖
  const handleDismissWarning = useCallback(() => {
    setDismissRefreshWarning(true)
    setWarningShownAt(null)
    try { localStorage.setItem(storageKey('dismiss_refresh_warning'), 'true') } catch { /* ignore */ }
  }, [])

  // warningShownAt 由 useEffect 的 setTimeout 在 10 秒后清除，无需在此检查 Date.now()
  const showRefreshWarning = (refreshFailCount >= 5 || warningShownAt !== null) && !dismissRefreshWarning
  const [loadingAccounts, setLoadingAccounts] = useState(true)
  const [activeTab, setActiveTab] = useState('')
  const [strategyList, setStrategyList] = useState<StrategyInfo[]>([])
  const [loadingStrategies, setLoadingStrategies] = useState(false)

  // 加载策略列表（动态 tab）
  useEffect(() => {
    let cancelled = false
    setLoadingStrategies(true)
    fetchStrategies().then(list => {
      if (cancelled) return
      // 过滤只保留支持模拟交易的策略（params 中有 rebalance_days 的）
      const supported = list.filter((s: any) => s.id && s.name)
      setStrategyList(supported)
      // 默认选中第一个
      if (supported.length > 0 && !activeTab) {
        setActiveTab(supported[0].id)
      }
    }).catch(() => {}).finally(() => {
      if (!cancelled) setLoadingStrategies(false)
    })
    return () => { cancelled = true }
  }, [])

  // useRef 缓存上次响应值，避免 30s 轮询导致 React 重渲染波纹
  const prevSnapshotRef = useRef<{ accounts: PaperAccountData[]; failCount: number; totalFails: number; threshold: number } | null>(null)

  const isMountedRef = useRef(true)

  const loadAccounts = useCallback(async () => {
    if (!isMountedRef.current) return
    setLoadingAccounts(true) // 显式开始加载，避免闪烁
    try {
      const res = await fetchPaperAccounts()
      const accounts = res.accounts || []
      const newFailCount = res.refresh_fail_count || 0
      const newTotalFails = res.refresh_total_fails || 0
      const newThreshold = res.refresh_total_fail_threshold || 30

      // 仅数值变化时 setState，避免每次 API 调用都触发重渲染
      const prev = prevSnapshotRef.current
      if (
        !prev ||
        prev.accounts.length !== accounts.length ||
        prev.failCount !== newFailCount ||
        prev.totalFails !== newTotalFails ||
        prev.threshold !== newThreshold
      ) {
        setAccounts(accounts)
        setRefreshFailCount(newFailCount)
        setRefreshTotalFails(newTotalFails)
        setRefreshTotalFailThreshold(newThreshold)
        prevSnapshotRef.current = {
          accounts,
          failCount: newFailCount,
          totalFails: newTotalFails,
          threshold: newThreshold,
        }
      }
      if (import.meta.env.DEV && res.refresh_total_fail_threshold) {
        console.debug('[PaperTrade] Threshold synced:', res.refresh_total_fail_threshold, 'total fails:', newTotalFails)
      }

      // 桌面原生通知：连续失败首次达到 5 次时弹出
      if (newFailCount === 5 && isElectron) {
        showNotification?.(
          '持仓价格刷新异常',
          `行情刷新已连续失败 5 次，持仓价格可能不是最新。累计失败 ${newTotalFails} 次。`
        )
      }
      // 严重异常：累计失败达到阈值时弹出
      if (newTotalFails >= (res.refresh_total_fail_threshold || 30) && newFailCount > 0 && isElectron) {
        showNotification?.(
          '持仓价格刷新严重异常',
          `累计失败已达 ${newTotalFails} 次，建议重启后端服务。`
        )
      }

      // 记录警告首次出现的时间（用 ref 避免闭包过期）
      if (newFailCount >= 5 && warningShownRef.current === null) {
        setWarningShownAt(Date.now())
      }
      // 成功加载，重置失败计数
      loadFailCountRef.current = 0
      try { localStorage.setItem(storageKey('load_fail_count'), '0') } catch { /* ignore */ }
    } catch (e: unknown) {
      console.warn('Load paper accounts failed:', e)
      loadFailCountRef.current += 1
      try {
        localStorage.setItem(storageKey('load_fail_count'), String(loadFailCountRef.current))
        localStorage.setItem(storageKey('load_fail_ts'), String(Date.now()))
      } catch { /* ignore */ }
      // 首次失败不弹错误（避免网络抖动），连续失败 >=2 次才提示
      if (isMountedRef.current && loadFailCountRef.current >= 2) {
        message.error('加载账户失败，请检查网络连接')
      }
    }
    finally { if (isMountedRef.current) setLoadingAccounts(false) }
  }, [isElectron, showNotification])

  useEffect(() => {
    isMountedRef.current = true
    loadAccounts()
    return () => { isMountedRef.current = false }
  }, [loadAccounts])

  // 10秒后自动关闭 warningShownAt（确保 Alert 不会无限停留）
  // 同时：如果 refreshFailCount 恢复到 <5 且已过 10 秒，也清除 warningShownAt
  useEffect(() => {
    if (warningShownAt === null) return
    // 如果问题已恢复且已过最小显示时间，立即清除
    if (refreshFailCount < 5) {
      const remaining = 10000 - (Date.now() - warningShownAt)
      if (remaining <= 0) {
        setWarningShownAt(null)
        return
      }
      const timer = setTimeout(() => setWarningShownAt(null), remaining)
      return () => clearTimeout(timer)
    }
    // 问题仍存在，保持显示（不做超时清除，等恢复后再计时）
  }, [warningShownAt, refreshFailCount])

  return (
    <div style={{ padding: 16 }}>
      {showRefreshWarning && (
        <Alert
          type={refreshTotalFails >= refreshTotalFailThreshold ? "error" : "warning"}
          showIcon
          closable
          onClose={handleDismissWarning}
          message={refreshTotalFails >= refreshTotalFailThreshold ? "持仓价格刷新严重异常" : "持仓价格刷新连续失败"}
          description={
            <span>
              行情数据刷新已连续失败 {refreshFailCount} 次{refreshTotalFails >= Math.floor(refreshTotalFailThreshold / 3) ? `，累计失败 ${refreshTotalFails} 次` : ''}，持仓价格可能不是最新。请检查网络连接或重启应用。
              {refreshTotalFails >= refreshTotalFailThreshold && isElectron && (
                <Button size="small" danger style={{ marginLeft: 12 }} onClick={async () => { try { await restartBackend() } catch {} }}>
                  重启后端
                </Button>
              )}
            </span>
          }
          style={{ marginBottom: 12 }}
        />
      )}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={strategyList.map((s: StrategyInfo) => ({
          key: s.id,
          label: (
            <span>
              {s.name}
              {loadingAccounts && s.id === activeTab && (
                <Spin size="small" style={{ marginLeft: 8 }} />
              )}
            </span>
          ),
          children: <StrategyTab strategyId={s.id} accounts={accounts} onRefresh={loadAccounts} />,
        }))}
      />
    </div>
  )
}
