import React, { useState, useEffect, useCallback, useMemo } from 'react'
import { Card, Table, Tag, Empty, message, Space, Button, Progress, Select, Input, Row, Col, Badge, Slider, Statistic, Popconfirm, Modal, Descriptions, DatePicker } from 'antd'
import { ReloadOutlined, WifiOutlined, DisconnectOutlined, SettingOutlined, CloudOutlined, PlayCircleOutlined, ThunderboltOutlined, LineChartOutlined, DownloadOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import {
  fetchAvailableSignalsStrategies,
  setActiveStrategies, setStrategyParams, invalidateSignalCache,
  fetchDedupConfig, setDedupConfig, fetchDedupPresets,
  fetchSignalHistory, fetchWsStats, fetchSignalsHealth, setAutoExecuteConfig, executeSignal, verifyStrategy,
  fetchExecutedPositions,
  type TradeSignal, type StrategyInfoItem, type SignalHistoryItem, type DedupPreset, type WsStats, type SignalsHealth, type StrategyVerifyResult, type ExecutedPosition,
} from '../../services/api'
import { useSignalStore } from '../../stores/useSignalStore'
import { signalsWs } from '../../utils/wsInstances'
import type { WsLogEntry } from '../../utils/wsReconnect'
import ReactEChartsCore from 'echarts-for-react/lib/core'
import echarts from '../../utils/echarts'

export default React.memo(function SignalStrategyTab() {
  const {
    signals, activeStrategies, wsConnected,
    loadSignals, setStrategies, connectWs,
  } = useSignalStore()

  const [availableStrategies, setAvailableStrategies] = useState<StrategyInfoItem[]>([])
  const [strategyParamJson, setStrategyParamJson] = useState('{}')
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>('')
  const [dedupWindow, setDedupWindow] = useState(300)
  const [dedupThreshold, setDedupThreshold] = useState(0.02)
  const [signalHistory, setSignalHistory] = useState<SignalHistoryItem[]>([])
  const [historyLoading, setHistoryLoading] = useState(false)
  const [historyStrategy, setHistoryStrategy] = useState('')
  const [historyCode, setHistoryCode] = useState('')
  const [historyDateRange, setHistoryDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null)
  const [historyTotal, setHistoryTotal] = useState(0)
  const [historyPage, setHistoryPage] = useState(1)
  const historyPageSize = 20
  const [historySelected, setHistorySelected] = useState<Set<string>>(new Set())
  const [dedupPresets, setDedupPresets] = useState<Record<string, DedupPreset>>({})
  const [wsStats, setWsStats] = useState<WsStats | null>(null)
  const [health, setHealth] = useState<SignalsHealth | null>(null)
  const [wsLog, setWsLog] = useState<WsLogEntry[]>([])
  const [autoExecuteThreshold, setAutoExecuteThreshold] = useState(0)
  const [executedCodes, setExecutedCodes] = useState<Set<string>>(new Set())
  const [wsStatsHistory, setWsStatsHistory] = useState<{ ts: string; market: number; signal: number; latency: number }[]>([])
  const [verifyResult, setVerifyResult] = useState<StrategyVerifyResult | null>(null)
  const [verifyVisible, setVerifyVisible] = useState(false)
  const [verifyLoading, setVerifyLoading] = useState(false)
  const [wsLatency, setWsLatency] = useState(0)
  const [executedPositions, setExecutedPositions] = useState<ExecutedPosition[]>([])
  const [executedTotal, setExecutedTotal] = useState(0)
  const [executedPage, setExecutedPage] = useState(1)
  const executedPageSize = 10
  const [executedCodeFilter, setExecutedCodeFilter] = useState('')
  const [executedSideFilter, setExecutedSideFilter] = useState('')
  const [executedDateRange, setExecutedDateRange] = useState<[dayjs.Dayjs | null, dayjs.Dayjs | null] | null>(null)

  const loadData = useCallback(async () => {
    try {
      await loadSignals()
      const stratRes = await fetchAvailableSignalsStrategies()
      setAvailableStrategies(stratRes.strategies)
    } catch (e) { console.error('加载信号失败', e) }
    fetchWsStats().then(s => { setWsStats(s); setWsStatsHistory(prev => [...prev.slice(-19), { ts: new Date().toLocaleTimeString(), market: s.messages.market_messages_sent, signal: s.messages.signal_messages_sent, latency: signalsWs.getLatency() }]) }).catch(() => {})
    fetchSignalsHealth().then(h => { setHealth(h); if (h.auto_execute_threshold != null) setAutoExecuteThreshold(h.auto_execute_threshold) }).catch(() => {})
    setWsLatency(signalsWs.getLatency())
    setWsLog(signalsWs.getEventLog())
    loadExecutedPositions()
  }, [loadSignals])

  const loadSignalHistory = useCallback(async (page?: number) => {
    setHistoryLoading(true)
    const p = page ?? historyPage
    try {
      const offset = (p - 1) * historyPageSize
      const res = await fetchSignalHistory(historyStrategy || undefined, historyCode || undefined, historyPageSize, offset)
      setSignalHistory(res.signals)
      setHistoryTotal(res.total)
      setHistoryPage(p)
    } catch {
      message.error('加载信号历史失败')
    } finally {
      setHistoryLoading(false)
    }
  }, [historyStrategy, historyCode, historyPage])

  // Initial load + WebSocket auto-connect + load dedup config
  useEffect(() => {
    loadData()
    loadSignalHistory()
    const cleanup = connectWs()
    fetchDedupConfig().then(c => { setDedupWindow(c.window_seconds); setDedupThreshold(c.price_threshold) }).catch(() => {})
    fetchDedupPresets().then(p => setDedupPresets(p)).catch(() => {})
    return cleanup
  }, [loadData, connectWs, loadSignalHistory])

  // Debounce search: auto-query when strategy or code changes
  useEffect(() => {
    const timer = setTimeout(() => loadSignalHistory(1), 300)
    return () => clearTimeout(timer)
  }, [historyStrategy, historyCode])

  // Auto-refresh WS stats every 30s
  useEffect(() => {
    const timer = setInterval(() => {
      fetchWsStats().then(s => { setWsStats(s); setWsStatsHistory(prev => [...prev.slice(-19), { ts: new Date().toLocaleTimeString(), market: s.messages.market_messages_sent, signal: s.messages.signal_messages_sent, latency: signalsWs.getLatency() }]) }).catch(() => {})
      fetchSignalsHealth().then(h => { setHealth(h); if (h.auto_execute_threshold != null) setAutoExecuteThreshold(h.auto_execute_threshold) }).catch(() => {})
      setWsLatency(signalsWs.getLatency())
    }, 30000)
    return () => clearInterval(timer)
  }, [])

  const handleSetActiveStrategies = useCallback(async (ids: string[]) => {
    try {
      await setStrategies(ids)
      message.success('活跃策略已更新')
      // 联动去重预设：匹配第一个策略的推荐配置
      if (ids.length > 0 && Object.keys(dedupPresets).length > 0) {
        const preset = dedupPresets[ids[0]] || dedupPresets['default']
        if (preset && (dedupWindow !== preset.window_seconds || Math.abs(dedupThreshold - preset.price_threshold) > 0.001)) {
          setDedupWindow(preset.window_seconds)
          setDedupThreshold(preset.price_threshold)
          message.info(`已自动匹配 ${ids[0]} 去重预设: ${preset.window_seconds}s / ${(preset.price_threshold * 100).toFixed(0)}%`, 3)
        }
      }
    } catch { message.error('更新策略失败') }
  }, [setStrategies, dedupPresets, dedupWindow, dedupThreshold])

  const handleSetStrategyParams = useCallback(async () => {
    if (!selectedStrategyId) { message.warning('请先选择策略'); return }
    try {
      const params = JSON.parse(strategyParamJson)
      await setStrategyParams(selectedStrategyId, params)
      message.success('策略参数已更新')
    } catch (e: unknown) { message.error('参数格式错误或更新失败: ' + (e instanceof Error ? e.message : String(e))) }
  }, [selectedStrategyId, strategyParamJson])

  const handleInvalidateCache = useCallback(async (strategy?: string) => {
    try { await invalidateSignalCache(strategy); message.success(strategy ? `${strategy} 缓存已清除` : '所有策略缓存已清除') }
    catch { message.error('清除缓存失败') }
  }, [])

  const handleSaveDedupConfig = useCallback(async () => {
    try {
      const res = await setDedupConfig({ window_seconds: dedupWindow, price_threshold: dedupThreshold })
      setDedupWindow(res.window_seconds)
      setDedupThreshold(res.price_threshold)
      message.success('去重配置已更新')
    } catch {
      message.error('更新去重配置失败')
    }
  }, [dedupWindow, dedupThreshold])

  const handleSetAutoExecute = useCallback(async () => {
    try {
      const res = await setAutoExecuteConfig(autoExecuteThreshold)
      setAutoExecuteThreshold(res.auto_execute_min_confidence)
      message.success(`自动执行阈值已设为 ${(res.auto_execute_min_confidence * 100).toFixed(0)}%`)
    } catch {
      message.error('更新自动执行阈值失败')
    }
  }, [autoExecuteThreshold])

  const loadExecutedPositions = useCallback(async (page?: number) => {
    const p = page ?? executedPage
    const offset = (p - 1) * executedPageSize
    try {
      const r = await fetchExecutedPositions(executedPageSize, offset)
      setExecutedPositions(r.positions)
      setExecutedTotal(r.total)
      setExecutedPage(p)
    } catch {}
  }, [executedPage])

  const handleVerifyStrategy = useCallback(async () => {
    if (!selectedStrategyId) { message.warning('请先选择策略'); return }
    setVerifyLoading(true)
    try {
      const res = await verifyStrategy(selectedStrategyId)
      setVerifyResult(res)
      setVerifyVisible(true)
    } catch { message.error('策略验证失败') }
    finally { setVerifyLoading(false) }
  }, [selectedStrategyId])

  const handleExecuteSignal = useCallback(async (code: string, action: string) => {
    try {
      const res = await executeSignal(code)
      message.success(`${code} ${action === 'buy' ? '买入' : '卖出'}执行成功，${res.executed} 笔委托`)
      setExecutedCodes(prev => new Set(prev).add(code))
      loadSignals()
      loadExecutedPositions()
      setTimeout(() => setExecutedCodes(prev => { const next = new Set(prev); next.delete(code); return next }), 5000)
    } catch {
      message.error(`${code} 执行失败`)
    }
  }, [loadSignals])

  const signalColumns = useMemo(() => [
    { title: '策略', dataIndex: 'strategy', width: 100, render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '代码', dataIndex: 'code', width: 100 },
    { title: '名称', dataIndex: 'name', width: 120, ellipsis: true },
    { title: '动作', dataIndex: 'action', width: 80, render: (v: string) => <Tag color={v === 'buy' ? 'green' : 'red'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', width: 80, render: (v: number) => v?.toFixed(3) },
    { title: '置信度', dataIndex: 'confidence', width: 100, render: (v: number) => <Progress percent={v * 100} size="small" strokeColor={v >= 0.7 ? '#52c41a' : v >= 0.5 ? '#1677ff' : '#faad14'} /> },
    { title: '原因', dataIndex: 'reason', width: 200, ellipsis: true },
    { title: '时间', dataIndex: 'ts', width: 140, render: (v: string) => dayjs(v).format('HH:mm:ss') },
    { title: '已执行', dataIndex: 'executed', width: 70, render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag> },
    { title: '操作', width: 80, render: (_: unknown, r: TradeSignal) => !r.executed ? (
      <Popconfirm title={(() => {
        const slippage = r.action === 'buy' ? 0.05 : 0.05
        const estPrice = r.price * (r.action === 'buy' ? 1 + slippage / 100 : 1 - slippage / 100)
        return <div>
          <div>确认执行 {r.code} {r.action === 'buy' ? '买入' : '卖出'}？</div>
          <div style={{ fontSize: 12, color: '#999', marginTop: 4 }}>
            委托价: {r.price?.toFixed(3)} → 预估成交: {estPrice.toFixed(3)}
          </div>
          <div style={{ fontSize: 11, color: '#faad14' }}>预估滑点: ~{slippage}%</div>
        </div>
      })()} onConfirm={() => handleExecuteSignal(r.code, r.action)} okText="执行" cancelText="取消">
        <Button type="link" size="small" icon={<PlayCircleOutlined />} style={{ color: r.action === 'buy' ? '#52c41a' : '#ff4d4f' }}>执行</Button>
      </Popconfirm>
    ) : <span style={{ color: '#999', fontSize: 12 }}>已执行</span> },
  ], [handleExecuteSignal])

  const filteredHistory = useMemo(() => {
    if (!historyDateRange || (!historyDateRange[0] && !historyDateRange[1])) return signalHistory
    return signalHistory.filter(s => {
      const d = dayjs(s.ts)
      if (historyDateRange[0] && d.isBefore(historyDateRange[0], 'day')) return false
      if (historyDateRange[1] && d.isAfter(historyDateRange[1], 'day')) return false
      return true
    })
  }, [signalHistory, historyDateRange])

  const filteredExecuted = useMemo(() => {
    return executedPositions.filter(p => {
      if (executedCodeFilter && !p.code.includes(executedCodeFilter)) return false
      if (executedSideFilter && p.side !== executedSideFilter) return false
      if (executedDateRange) {
        const d = dayjs(p.ts)
        if (executedDateRange[0] && d.isBefore(executedDateRange[0], 'day')) return false
        if (executedDateRange[1] && d.isAfter(executedDateRange[1], 'day')) return false
      }
      return true
    })
  }, [executedPositions, executedCodeFilter, executedSideFilter, executedDateRange])

  const historyColumns = useMemo(() => [
    { title: '', width: 40, render: (_: unknown, r: SignalHistoryItem) => (
      <Checkbox checked={historySelected.has(r.code)} onChange={e => {
        setHistorySelected(prev => { const next = new Set(prev); e.target.checked ? next.add(r.code) : next.delete(r.code); return next })
      }} />
    )},
    { title: '策略', dataIndex: 'strategy', width: 90, render: (v: string) => <Tag color="blue">{v}</Tag> },
    { title: '代码', dataIndex: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', width: 110, ellipsis: true },
    { title: '动作', dataIndex: 'action', width: 70, render: (v: string) => <Tag color={v === 'buy' ? 'green' : 'red'}>{v === 'buy' ? '买入' : '卖出'}</Tag> },
    { title: '价格', dataIndex: 'price', width: 75, render: (v: number) => v?.toFixed(3), sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => (a.price ?? 0) - (b.price ?? 0) },
    { title: '置信度', dataIndex: 'confidence', width: 80, render: (v: number) => (v * 100).toFixed(0) + '%', sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => a.confidence - b.confidence },
    { title: '原因', dataIndex: 'reason', width: 180, ellipsis: true },
    { title: '时间', dataIndex: 'ts', width: 130, render: (v: string) => dayjs(v).format('MM-DD HH:mm'), sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => new Date(a.ts).getTime() - new Date(b.ts).getTime() },
    { title: '已执行', dataIndex: 'executed', width: 60, render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '是' : '否'}</Tag>, sorter: (a: SignalHistoryItem, b: SignalHistoryItem) => Number(a.executed) - Number(b.executed) },
  ], [])

  return (
    <div style={{ padding: 16 }}>
      <Card size="small" title="活跃策略" style={{ marginBottom: 16 }} extra={
        <Space size="small">
          {health && (
            <Space size={4}>
              <Badge status={health.engine_available ? 'success' : 'error'} style={{ fontSize: 10 }} />
              <span style={{ fontSize: 11, color: '#666' }}>引擎</span>
              <Badge status={health.storage_available ? 'success' : 'error'} style={{ fontSize: 10 }} />
              <span style={{ fontSize: 11, color: '#666' }}>存储</span>
              <span style={{ fontSize: 11, color: '#999' }}>缓存{health.cache_entries}</span>
            </Space>
          )}
          <Badge status={wsConnected ? 'success' : 'error'} text={
            <span style={{ fontSize: 12, color: wsConnected ? '#52c41a' : '#ff4d4f' }}>
              {wsConnected ? <><WifiOutlined /> 实时</> : <><DisconnectOutlined /> 离线</>}
            </span>
          } />
          <Button size="small" icon={<ReloadOutlined />} onClick={loadData}>刷新</Button>
        </Space>
      }>
        <Select
          mode="multiple"
          style={{ width: '100%' }}
          value={activeStrategies}
          onChange={handleSetActiveStrategies}
          options={availableStrategies.map(s => ({ value: s.id, label: `${s.name} - ${s.description}` }))}
          placeholder="选择活跃策略"
        />
        {signalHistory.length > 0 && (() => {
          const stratReturns = new Map<string, number[]>()
          for (const s of signalHistory) {
            const arr = stratReturns.get(s.strategy) || []
            arr.push(s.confidence)
            stratReturns.set(s.strategy, arr)
          }
          const sharpeList = Array.from(stratReturns.entries()).map(([name, confs]) => {
            const mean = confs.reduce((a, b) => a + b, 0) / confs.length
            const std = Math.sqrt(confs.reduce((s, c) => s + (c - mean) ** 2, 0) / confs.length)
            const sharpe = std > 0 ? mean / std : 0
            return { name, sharpe, count: confs.length }
          })
          if (sharpeList.length < 2) return null
          return (
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              <span style={{ marginRight: 8 }}>策略置信度 Sharpe:</span>
              {sharpeList.sort((a, b) => b.sharpe - a.sharpe).map(s => (
                <Tag key={s.name} color={s.sharpe >= 1 ? 'green' : s.sharpe >= 0.5 ? 'blue' : 'orange'} style={{ fontSize: 11 }}>
                  {s.name}: {s.sharpe.toFixed(2)} ({s.count}信号)
                </Tag>
              ))}
            </div>
          )
        })()}
        {signalHistory.length > 0 && (() => {
          const stratCounts = new Map<string, number>()
          for (const s of signalHistory) stratCounts.set(s.strategy, (stratCounts.get(s.strategy) || 0) + 1)
          const entries = Array.from(stratCounts.entries())
          if (entries.length < 2) return null
          const colors = ['#1677ff', '#52c41a', '#faad14', '#722ed1', '#eb2f96']
          return (
            <div style={{ marginTop: 8 }}>
              <ReactEChartsCore echarts={echarts} option={{
                tooltip: { trigger: 'item' as const, formatter: (p: any) => `${p.name}: ${p.value} 信号 (${p.percent}%)` },
                series: [{ type: 'pie', radius: ['30%', '55%'], center: ['50%', '50%'], data: entries.map(([name, count], i) => ({ value: count, name, itemStyle: { color: colors[i % colors.length] } })), label: { fontSize: 10, formatter: '{b}: {d}%' } }],
              }} style={{ height: 100 }} />
            </div>
          )
        })()}
      </Card>
      <Card size="small" title={<Space><SettingOutlined /> 信号去重配置</Space>} style={{ marginBottom: 16 }}>
        {Object.keys(dedupPresets).length > 0 && (
          <div style={{ marginBottom: 8 }}>
            <span style={{ fontSize: 12, color: '#666', marginRight: 8 }}>策略预设:</span>
            <Space size={4} wrap>
              {Object.entries(dedupPresets).map(([key, preset]) => (
                <Button key={key} size="small"
                  type={dedupWindow === preset.window_seconds && Math.abs(dedupThreshold - preset.price_threshold) < 0.001 ? 'primary' : 'default'}
                  onClick={() => { setDedupWindow(preset.window_seconds); setDedupThreshold(preset.price_threshold) }}
                  title={preset.reason}
                  style={{ fontSize: 11, padding: '0 6px' }}
                >{key === 'default' ? '默认' : key}</Button>
              ))}
            </Space>
          </div>
        )}
        <Row gutter={16} align="middle">
          <Col span={10}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>去重窗口 ({dedupWindow >= 60 ? `${(dedupWindow / 60).toFixed(dedupWindow % 60 === 0 ? 0 : 1)}分钟` : `${dedupWindow}秒`})</div>
            <Slider min={0} max={3600} step={30} value={dedupWindow} onChange={v => setDedupWindow(v)}
              marks={{ 0: '0', 300: '5分', 600: '10分', 900: '15分', 1800: '30分', 3600: '1时' }} />
          </Col>
          <Col span={10}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>价格变化阈值 ({(dedupThreshold * 100).toFixed(0)}%)</div>
            <Slider min={0} max={20} step={1} value={Math.round(dedupThreshold * 100)} onChange={v => setDedupThreshold(v / 100)}
              marks={{ 0: '0%', 2: '2%', 5: '5%', 10: '10%', 20: '20%' }} />
          </Col>
          <Col span={4}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>&nbsp;</div>
            <Button type="primary" size="small" onClick={handleSaveDedupConfig}>应用</Button>
          </Col>
        </Row>
      </Card>
      <Card size="small" title="策略参数配置" style={{ marginBottom: 16 }}>
        <Space direction="vertical" style={{ width: '100%' }}>
          <Row gutter={8}>
            <Col span={8}>
              <Select
                style={{ width: '100%' }}
                value={selectedStrategyId || undefined}
                onChange={v => { setSelectedStrategyId(v); setStrategyParamJson('{}') }}
                options={availableStrategies.map(s => ({ value: s.id, label: s.name }))}
                placeholder="选择策略"
              />
              {selectedStrategyId && (() => {
                const strat = availableStrategies.find(s => s.id === selectedStrategyId)
                if (!strat || !strat.params || strat.params.length === 0) return null
                const defaultParams: Record<string, number> = {}
                for (const p of strat.params) defaultParams[p.name] = p.default
                const conservativeParams: Record<string, number> = {}
                for (const p of strat.params) conservativeParams[p.name] = p.max_val != null ? Math.round((p.default + p.max_val) / 2) : p.default
                const aggressiveParams: Record<string, number> = {}
                for (const p of strat.params) aggressiveParams[p.name] = p.min_val != null ? Math.round((p.default + p.min_val) / 2) : p.default
                return (
                  <div style={{ marginTop: 4 }}>
                    <span style={{ fontSize: 11, color: '#999', marginRight: 4 }}>预设:</span>
                    <Space size={4}>
                      <Button size="small" style={{ fontSize: 10, padding: '0 4px' }}
                        onClick={() => setStrategyParamJson(JSON.stringify(defaultParams))}>默认</Button>
                      <Button size="small" style={{ fontSize: 10, padding: '0 4px' }}
                        onClick={() => setStrategyParamJson(JSON.stringify(conservativeParams))}>保守</Button>
                      <Button size="small" style={{ fontSize: 10, padding: '0 4px' }}
                        onClick={() => setStrategyParamJson(JSON.stringify(aggressiveParams))}>激进</Button>
                    </Space>
                  </div>
                )
              })()}
            </Col>
            <Col span={12}>
              <Input.TextArea
                rows={2}
                value={strategyParamJson}
                onChange={e => setStrategyParamJson(e.target.value)}
                placeholder='{"threshold": 130}'
              />
            </Col>
            <Col span={4}>
              <Space direction="vertical">
                <Button type="primary" size="small" onClick={handleSetStrategyParams} disabled={!selectedStrategyId}>应用参数</Button>
                <Space size={4}>
                  <Button size="small" onClick={() => handleInvalidateCache(selectedStrategyId || undefined)} disabled={!selectedStrategyId}>清除缓存</Button>
                  <Button size="small" icon={<LineChartOutlined />} onClick={handleVerifyStrategy} loading={verifyLoading} disabled={!selectedStrategyId}>验证</Button>
                </Space>
              </Space>
            </Col>
          </Row>
        </Space>
      </Card>
      <Card size="small" title="自动执行配置" style={{ marginBottom: 16 }}>
        <Row gutter={16} align="middle">
          <Col span={18}>
            <div style={{ marginBottom: 4, fontSize: 12, color: '#666' }}>最低置信度 ({(autoExecuteThreshold * 100).toFixed(0)}%) — 仅自动执行置信度高于此值的信号</div>
            <Slider min={0} max={100} step={5} value={Math.round(autoExecuteThreshold * 100)} onChange={v => setAutoExecuteThreshold(v / 100)}
              marks={{ 0: '关闭', 50: '50%', 70: '70%', 90: '90%', 100: '100%' }} />
          </Col>
          <Col span={6}>
            <Button type="primary" size="small" onClick={handleSetAutoExecute}>应用</Button>
          </Col>
        </Row>
      </Card>
      <Card size="small" title={`实时信号 (${signals.length})`}>
        {signals.length > 0 ? (
          <Table dataSource={signals} rowKey="code" size="small" pagination={{ pageSize: 10 }} columns={signalColumns}
            rowClassName={(r) => executedCodes.has(r.code) ? 'signal-executed-row' : ''} />
        ) : <Empty description="暂无信号，WebSocket连接后实时推送" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>
      <Card
        size="small"
        title={`信号历史 (${filteredHistory.length}${filteredHistory.length !== signalHistory.length ? `/${signalHistory.length}` : ''})`}
        style={{ marginTop: 16 }}
        extra={
          <Space size="small">
            <Select
              size="small"
              allowClear
              placeholder="策略"
              value={historyStrategy || undefined}
              onChange={v => setHistoryStrategy(v || '')}
              options={availableStrategies.map(s => ({ value: s.id, label: s.name }))}
              style={{ width: 120 }}
            />
            <DatePicker.RangePicker
              size="small"
              value={historyDateRange}
              onChange={v => { setHistoryDateRange(v); setHistoryPage(1) }}
              style={{ width: 180 }}
              placeholder={['开始', '结束']}
              allowClear
            />
            <Input
              size="small"
              placeholder="代码"
              value={historyCode}
              onChange={e => setHistoryCode(e.target.value)}
              style={{ width: 100 }}
              allowClear
            />
            <Button size="small" icon={<ReloadOutlined />} onClick={() => loadSignalHistory(1)} loading={historyLoading}>查询</Button>
            <Popconfirm title={`确认批量执行选中的 ${historySelected.size} 个信号？`} onConfirm={async () => {
              let ok = 0, fail = 0
              for (const code of historySelected) {
                try { await executeSignal(code); ok++ } catch { fail++ }
              }
              message.success(`批量执行完成: ${ok} 成功, ${fail} 失败`)
              setHistorySelected(new Set())
              loadSignalHistory()
              loadSignals()
            }} disabled={historySelected.size === 0} okText="执行" cancelText="取消">
              <Button size="small" type="primary" icon={<ThunderboltOutlined />} disabled={historySelected.size === 0}>
                批量执行 ({historySelected.size})
              </Button>
            </Popconfirm>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => {
              const header = '策略,代码,名称,动作,价格,置信度,原因,时间,已执行'
              const rows = filteredHistory.map(s => `${s.strategy},${s.code},${s.name},${s.action},${s.price},${s.confidence},${s.reason?.replace(/,/g, '，')},${s.ts},${s.executed ? '是' : '否'}`)
              const csv = [header, ...rows].join('\n')
              const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = `signal_history_${dayjs().format('YYYYMMDD_HHmm')}.csv`
              a.click()
              URL.revokeObjectURL(url)
            }} disabled={signalHistory.length === 0}>导出</Button>
          </Space>
        }
      >
        {signalHistory.length > 0 ? (
          <Table
            dataSource={filteredHistory}
            rowKey="ts"
            size="small"
            columns={historyColumns}
            pagination={{
              current: historyPage,
              pageSize: historyPageSize,
              total: historyTotal,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p) => loadSignalHistory(p),
            }}
          />
        ) : <Empty description="暂无信号历史记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>
      <Card
        size="small"
        title={`执行记录 (${executedTotal})`}
        style={{ marginTop: 16 }}
        extra={
          <Space size="small">
            <Input size="small" placeholder="代码" value={executedCodeFilter} onChange={e => setExecutedCodeFilter(e.target.value)} style={{ width: 80 }} allowClear />
            <Select size="small" placeholder="方向" value={executedSideFilter || undefined} onChange={v => setExecutedSideFilter(v || '')} style={{ width: 70 }} allowClear options={[{ value: 'BUY', label: '买入' }, { value: 'SELL', label: '卖出' }]} />
            <DatePicker.RangePicker size="small" value={executedDateRange} onChange={v => setExecutedDateRange(v)} style={{ width: 170 }} placeholder={['开始', '结束']} allowClear />
            <Button size="small" icon={<ReloadOutlined />} onClick={() => loadExecutedPositions()}>刷新</Button>
            <Button size="small" icon={<DownloadOutlined />} onClick={() => {
              const header = '代码,名称,方向,价格,数量,时间'
              const rows = filteredExecuted.map(p => `${p.code},${p.name},${p.side === 'BUY' ? '买入' : '卖出'},${p.price},${p.volume},${p.ts}`)
              const csv = [header, ...rows].join('\n')
              const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
              const url = URL.createObjectURL(blob)
              const a = document.createElement('a')
              a.href = url
              a.download = `executed_positions_${dayjs().format('YYYYMMDD_HHmm')}.csv`
              a.click()
              URL.revokeObjectURL(url)
            }} disabled={filteredExecuted.length === 0}>导出</Button>
          </Space>
        }
      >
        {executedPositions.length > 0 && (() => {
          const totalAmount = filteredExecuted.reduce((s, p) => s + p.price * p.volume, 0)
          const buyCount = filteredExecuted.filter(p => p.side === 'BUY').length
          const sellCount = filteredExecuted.filter(p => p.side === 'SELL').length
          const commissionRate = 0.0003
          const minCommission = 1
          const totalCommission = filteredExecuted.reduce((s, p) => s + Math.max(minCommission, p.price * p.volume * commissionRate), 0)
          const slippageRate = 0.0005
          const totalSlippage = totalAmount * slippageRate
          return (
            <Row gutter={12} style={{ marginBottom: 8 }}>
              <Col span={4}><Statistic title="成交金额" value={totalAmount.toFixed(0)} suffix="元" valueStyle={{ fontSize: 14 }} /></Col>
              <Col span={3}><Statistic title="买入" value={buyCount} suffix="笔" valueStyle={{ fontSize: 14, color: '#52c41a' }} /></Col>
              <Col span={3}><Statistic title="卖出" value={sellCount} suffix="笔" valueStyle={{ fontSize: 14, color: '#cf1322' }} /></Col>
              <Col span={4}><Statistic title="预估佣金" value={totalCommission.toFixed(2)} suffix="元" valueStyle={{ fontSize: 14, color: '#faad14' }} /></Col>
              <Col span={4}><Statistic title="预估滑点" value={totalSlippage.toFixed(2)} suffix="元" valueStyle={{ fontSize: 14, color: '#faad14' }} /></Col>
              <Col span={6}><Statistic title="总成本占比" value={((totalCommission + totalSlippage) / Math.max(totalAmount, 1) * 100).toFixed(3)} suffix="%" valueStyle={{ fontSize: 14, color: ((totalCommission + totalSlippage) / Math.max(totalAmount, 1)) > 0.002 ? '#cf1322' : '#3f8600' }} /></Col>
            </Row>
          )
        })()}
        {executedPositions.length > 0 ? (
          <Table
            dataSource={filteredExecuted}
            rowKey="ts"
            size="small"
            pagination={{
              current: executedPage,
              pageSize: executedPageSize,
              total: executedTotal,
              showTotal: (t) => `共 ${t} 条`,
              onChange: (p) => loadExecutedPositions(p),
              size: 'small',
            }}
            columns={[
              { title: '代码', dataIndex: 'code', width: 80 },
              { title: '名称', dataIndex: 'name', width: 100, ellipsis: true },
              { title: '方向', dataIndex: 'side', width: 60, render: (v: string) => <Tag color={v === 'BUY' ? 'green' : 'red'}>{v === 'BUY' ? '买入' : '卖出'}</Tag> },
              { title: '价格', dataIndex: 'price', width: 75, render: (v: number) => v?.toFixed(3) },
              { title: '数量', dataIndex: 'volume', width: 60 },
              { title: '时间', dataIndex: 'ts', width: 130, render: (v: string) => dayjs(v).format('MM-DD HH:mm:ss') },
            ]}
          />
        ) : <Empty description="暂无执行记录" image={Empty.PRESENTED_IMAGE_SIMPLE} />}
      </Card>
      {wsStats && (
        <Card size="small" title={<Space><CloudOutlined /> WS 传输统计</Space>} style={{ marginTop: 16 }}
          extra={<Button size="small" icon={<ReloadOutlined />} onClick={() => fetchWsStats().then(s => setWsStats(s)).catch(() => {})}>刷新</Button>}
        >
          <Row gutter={12}>
            <Col span={4}>
              <Statistic title="行情消息" value={wsStats.messages.market_messages_sent} />
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                增量 {wsStats.messages.market_delta_messages} / 全量 {wsStats.messages.market_full_messages}
                {wsStats.messages.market_compressed_messages ? ` / 压缩 ${wsStats.messages.market_compressed_messages}` : ''}
              </div>
            </Col>
            <Col span={3}>
              <Statistic title="行情流量" value={(wsStats.messages.market_bytes_sent / 1024).toFixed(1)} suffix="KB" />
            </Col>
            <Col span={4}>
              <Statistic title="信号消息" value={wsStats.messages.signal_messages_sent} />
              {wsStats.messages.signal_compressed_messages && (
                <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>压缩 {wsStats.messages.signal_compressed_messages}</div>
              )}
            </Col>
            <Col span={3}>
              <Statistic title="信号流量" value={(wsStats.messages.signal_bytes_sent / 1024).toFixed(1)} suffix="KB" />
            </Col>
            <Col span={5}>
              {(() => {
                const mTotal = wsStats.messages.market_messages_sent || 1
                const sTotal = wsStats.messages.signal_messages_sent || 1
                const mComp = wsStats.messages.market_compressed_messages || 0
                const sComp = wsStats.messages.signal_compressed_messages || 0
                const compRate = ((mComp + sComp) / (mTotal + sTotal) * 100).toFixed(0)
                return <Statistic title="压缩率" value={compRate} suffix="%" valueStyle={{ color: Number(compRate) > 30 ? '#52c41a' : '#faad14' }} />
              })()}
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>{'压缩消息占比，>30% 为优'}</div>
            </Col>
            <Col span={5}>
              {(() => {
                const connectLog = wsLog.filter(e => e.event === 'connect')
                const now = Date.now()
                const duration = connectLog.length > 0 ? (now - connectLog[connectLog.length - 1].ts) / 1000 : 0
                const total = (wsStats.messages.market_messages_sent || 0) + (wsStats.messages.signal_messages_sent || 0)
                const rate = duration > 0 ? (total / duration).toFixed(1) : '0'
                const isHigh = Number(rate) > 50
                return <Statistic title="消息速率" value={rate} suffix="/s" valueStyle={{ color: isHigh ? '#faad14' : undefined }} />
              })()}
              <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>{'行情+信号合计，>50/s 偏高'}</div>
            </Col>
            <Col span={4}>
              {(() => {
                const history = signalsWs.getLatencyHistory()
                const avgLatency = history.length > 0 ? Math.round(history.reduce((a, b) => a + b, 0) / history.length) : 0
                const color = wsLatency > 500 ? '#cf1322' : wsLatency > 200 ? '#faad14' : wsLatency > 0 ? '#52c41a' : undefined
                return (
                  <>
                    <Statistic title="WS 延迟" value={wsLatency} suffix="ms" valueStyle={{ color }} />
                    <div style={{ fontSize: 11, color: '#999', marginTop: 2 }}>
                      平均: {avgLatency}ms{wsLatency > 500 ? ' ⚠ 延迟过高' : ''}
                    </div>
                  </>
                )
              })()}
            </Col>
          </Row>
          {(() => {
            const connectLog = wsLog.filter(e => e.event === 'connect')
            const now = Date.now()
            const currentDuration = connectLog.length > 0 ? Math.round((now - connectLog[connectLog.length - 1].ts) / 1000) : 0
            const durations: number[] = []
            for (let i = 1; i < wsLog.length; i++) {
              if (wsLog[i].event === 'disconnect' && wsLog[i - 1].event === 'connect') {
                durations.push(Math.round((wsLog[i].ts - wsLog[i - 1].ts) / 1000))
              }
            }
            const avgDuration = durations.length > 0 ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : 0
            const fmt = (s: number) => s >= 3600 ? `${Math.floor(s / 3600)}时${Math.round((s % 3600) / 60)}分` : s >= 60 ? `${Math.floor(s / 60)}分${s % 60}秒` : `${s}秒`
            return (
              <div style={{ marginTop: 8, fontSize: 12, color: '#666', display: 'flex', gap: 16 }}>
                <span>当前连接: <b style={{ color: wsConnected ? '#52c41a' : '#ff4d4f' }}>{currentDuration > 0 ? fmt(currentDuration) : '未连接'}</b></span>
                {avgDuration > 0 && <span>历史平均: {fmt(avgDuration)}</span>}
                {durations.length > 0 && <span>断线次数: {durations.length}</span>}
              </div>
            )
          })()}
          {Object.values(wsStats.messages.disconnect_reasons).some(v => v > 0) && (
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              断线: {Object.entries(wsStats.messages.disconnect_reasons).filter(([, v]) => v > 0).map(([k, v]) => `${k}=${v}`).join(', ')}
            </div>
          )}
          {wsStatsHistory.length >= 2 && (
            <div style={{ marginTop: 12 }}>
              <ReactEChartsCore echarts={echarts} option={{
                tooltip: { trigger: 'axis' as const },
                legend: { data: ['行情消息', '信号消息'], bottom: 0, textStyle: { fontSize: 10 } },
                grid: { left: 40, right: 10, top: 10, bottom: 28 },
                xAxis: { type: 'category' as const, data: wsStatsHistory.map(h => h.ts), axisLabel: { fontSize: 9, interval: Math.max(0, wsStatsHistory.length - 5) } },
                yAxis: { type: 'value' as const, splitLine: { show: false } },
                series: [
                  { name: '行情消息', type: 'line', data: wsStatsHistory.map(h => h.market), smooth: true, symbol: 'none', lineStyle: { width: 1.5 }, itemStyle: { color: '#1677ff' } },
                  { name: '信号消息', type: 'line', data: wsStatsHistory.map(h => h.signal), smooth: true, symbol: 'none', lineStyle: { width: 1.5 }, itemStyle: { color: '#52c41a' } },
                ],
              }} style={{ height: 100 }} />
            </div>
          )}
          {wsStatsHistory.length >= 2 && wsStatsHistory.some(h => h.latency > 0) && (
            <div style={{ marginTop: 12 }}>
              <ReactEChartsCore echarts={echarts} option={{
                tooltip: { trigger: 'axis' as const, formatter: (ps: any) => `${ps[0].name}<br/>延迟: ${ps[0].value}ms` },
                grid: { left: 50, right: 10, top: 10, bottom: 24 },
                xAxis: { type: 'category' as const, data: wsStatsHistory.map(h => h.ts), axisLabel: { fontSize: 9, interval: Math.max(0, wsStatsHistory.length - 5) } },
                yAxis: { type: 'value' as const, name: 'ms', splitLine: { show: false } },
                visualMap: { show: false, pieces: [{ lte: 200, color: '#52c41a' }, { gt: 200, lte: 500, color: '#faad14' }, { gt: 500, color: '#cf1322' }] },
                series: [{
                  type: 'line', data: wsStatsHistory.map(h => h.latency), smooth: true, symbol: 'circle', symbolSize: 6,
                  lineStyle: { width: 1.5, color: '#722ed1' },
                  markLine: { silent: true, data: [{ yAxis: 500, lineStyle: { color: '#cf1322', type: 'dashed', width: 1 }, label: { formatter: '500ms 警戒线', fontSize: 9 } }] },
                }],
              }} style={{ height: 80 }} />
            </div>
          )}
          {wsLog.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 11, color: '#666', maxHeight: 100, overflowY: 'auto' }}>
              <div style={{ fontWeight: 600, marginBottom: 2 }}>WS 事件日志:</div>
              {wsLog.slice().reverse().map((e, i) => (
                <div key={i} style={{ color: e.event === 'disconnect' || e.event === 'error' ? '#cf1322' : '#666' }}>
                  {dayjs(e.ts).format('HH:mm:ss')} [{e.event}] {e.detail}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}
      <Modal
        title={`策略验证: ${verifyResult?.strategy || ''}`}
        open={verifyVisible}
        onCancel={() => setVerifyVisible(false)}
        footer={null}
        width={640}
      >
        {verifyResult && verifyResult.summary && (
          <>
            <Descriptions size="small" bordered column={2} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="测试期数">{verifyResult.summary.total_periods}</Descriptions.Item>
              <Descriptions.Item label="过拟合期数">
                <span style={{ color: verifyResult.summary.overfit_ratio > 0.5 ? '#cf1322' : '#3f8600' }}>{verifyResult.summary.overfit_periods} ({(verifyResult.summary.overfit_ratio * 100).toFixed(0)}%)</span>
              </Descriptions.Item>
              <Descriptions.Item label="平均年化收益">
                <span style={{ color: verifyResult.summary.avg_test_return > 0 ? '#cf1322' : '#3f8600' }}>{(verifyResult.summary.avg_test_return * 100).toFixed(2)}%</span>
              </Descriptions.Item>
              <Descriptions.Item label="收益标准差">{(verifyResult.summary.std_test_return * 100).toFixed(2)}%</Descriptions.Item>
              <Descriptions.Item label="平均回撤">{(verifyResult.summary.avg_test_drawdown * 100).toFixed(2)}%</Descriptions.Item>
              <Descriptions.Item label="平均夏普">{verifyResult.summary.avg_test_sharpe.toFixed(2)}</Descriptions.Item>
              <Descriptions.Item label="平均胜率">{(verifyResult.summary.avg_test_win_rate * 100).toFixed(1)}%</Descriptions.Item>
              <Descriptions.Item label="最佳时段">{verifyResult.summary.best_period}</Descriptions.Item>
            </Descriptions>
            {Object.keys(verifyResult.yearly).length > 0 && (
              <>
                <Row gutter={16} style={{ marginBottom: 16 }}>
                  <Col span={14}>
                    <Card size="small" title="年化收益">
                      <ReactEChartsCore echarts={echarts} option={{
                        tooltip: { trigger: 'axis' as const, formatter: (ps: any) => `${ps[0].name}<br/>年化收益: ${(ps[0].value * 100).toFixed(2)}%` },
                        grid: { left: 50, right: 10, top: 10, bottom: 24 },
                        xAxis: { type: 'category' as const, data: Object.keys(verifyResult.yearly) },
                        yAxis: { type: 'value' as const, axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
                        series: [{ type: 'bar', data: Object.values(verifyResult.yearly).map((d: any) => ({
                          value: d.annual_return, itemStyle: { color: d.annual_return >= 0 ? '#cf1322' : '#3f8600' }
                        })) }],
                      }} style={{ height: 160 }} />
                    </Card>
                  </Col>
                  <Col span={10}>
                    <Card size="small" title="最大回撤">
                      <ReactEChartsCore echarts={echarts} option={{
                        tooltip: { trigger: 'axis' as const, formatter: (ps: any) => `${ps[0].name}<br/>回撤: -${(Math.abs(ps[0].value) * 100).toFixed(2)}%` },
                        grid: { left: 50, right: 10, top: 10, bottom: 24 },
                        xAxis: { type: 'category' as const, data: Object.keys(verifyResult.yearly) },
                        yAxis: { type: 'value' as const, max: 0, axisLabel: { formatter: (v: number) => `${(v * 100).toFixed(0)}%` } },
                        series: [{ type: 'bar', data: Object.values(verifyResult.yearly).map((d: any) => ({
                          value: -d.max_drawdown, itemStyle: { color: '#3f8600' }
                        })) }],
                      }} style={{ height: 160 }} />
                    </Card>
                  </Col>
                </Row>
                <Card size="small" title="分年度表现">
                  <Table
                  dataSource={Object.entries(verifyResult.yearly).map(([year, d]) => ({ year, ...d }))}
                  rowKey="year"
                  size="small"
                  pagination={false}
                  columns={[
                    { title: '年份', dataIndex: 'year', width: 80 },
                    { title: '年化收益', dataIndex: 'annual_return', width: 100, render: (v: number) => <span style={{ color: v > 0 ? '#cf1322' : '#3f8600' }}>{(v * 100).toFixed(2)}%</span> },
                    { title: '最大回撤', dataIndex: 'max_drawdown', width: 100, render: (v: number) => <span style={{ color: '#3f8600' }}>-{(v * 100).toFixed(2)}%</span> },
                    { title: '夏普', dataIndex: 'sharpe_ratio', width: 70, render: (v: number) => v.toFixed(2) },
                    { title: '期数', dataIndex: 'periods', width: 60 },
                  ]}
                />
              </Card>
            </>
            )}
          </>
        )}
      </Modal>
    </div>
  )
})
