import { useState, useEffect, useCallback } from 'react'
import { Row, Col, Typography, message } from 'antd'
import { BarChartOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import { fetchStrategies, runBacktest, runOptimization } from '../services/api'
import type { BacktestResult, StrategyInfo, BacktestConfig, OptimizationConfig, OptimizationParamRange, OptimizationResult } from '../services/api'
import BacktestConfigPanel from '../components/backtest/BacktestConfigPanel'
import BacktestResultsPanel from '../components/backtest/BacktestResultsPanel'
import OptimizationResultsTable from '../components/backtest/OptimizationResultsTable'

const { Title } = Typography

const DEFAULT_CONFIG: BacktestConfig = {
  commission_pct: 0.001,
  slippage_pct: 0.001,
  min_commission: 5,
  risk_free_rate: 0.02,
}

export default function Backtest() {
  const [strategies, setStrategies] = useState<StrategyInfo[]>([])
  const [selectedStrategy, setSelectedStrategy] = useState<string>('')
  const [strategyParams, setStrategyParams] = useState<Record<string, number>>({})
  const [dateRange, setDateRange] = useState<[dayjs.Dayjs, dayjs.Dayjs]>([
    dayjs('2024-01-01'),
    dayjs('2024-12-31'),
  ])
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [optResult, setOptResult] = useState<OptimizationResult | null>(null)
  const [strategiesLoading, setStrategiesLoading] = useState(true)

  // ---- 交易成本参数 ----
  const [config, setConfig] = useState<BacktestConfig>({ ...DEFAULT_CONFIG })

  // ---- 参数优化状态 ----
  const [optEnabled, setOptEnabled] = useState(false)
  const [optMetric, setOptMetric] = useState('sharpe_ratio')
  const [optMaxIter, setOptMaxIter] = useState(100)
  const [optTopN, setOptTopN] = useState(10)
  const [optRanges, setOptRanges] = useState<OptimizationParamRange[]>([])

  useEffect(() => {
    fetchStrategies()
      .then((list) => {
        setStrategies(list)
        if (list.length > 0 && list[0].id) {
          setSelectedStrategy(list[0].id)
          const defaults: Record<string, number> = {}
          for (const p of (list[0].params || [])) {
            defaults[p.name] = p.default ?? 0
          }
          setStrategyParams(defaults)
        }
      })
      .catch(() => message.error('策略列表加载失败'))
      .finally(() => setStrategiesLoading(false))
  }, [])

  // 切换策略时自动初始化优化范围
  const handleStrategyChange = useCallback((id: string) => {
    setSelectedStrategy(id)
    setResult(null)
    setOptResult(null)
    const s = strategies.find((st) => st.id === id)
    if (s) {
      const defaults: Record<string, number> = {}
      const ranges: OptimizationParamRange[] = []
      for (const p of (s.params || [])) {
        const def = p.default ?? 0
        defaults[p.name] = def
        if (p.type === 'int' || p.type === 'float') {
          const min = p.min_val ?? def * 0.5
          const max = p.max_val ?? def * 1.5
          ranges.push({
            name: p.name,
            min_val: min,
            max_val: max,
            step: p.type === 'int' ? 1 : Math.round((max - min) / 5 * 100) / 100 || 1,
          })
        }
      }
      setStrategyParams(defaults)
      setOptRanges(ranges)
    }
  }, [strategies])

  // ---- 运行回测或优化 ----
  const handleRun = async () => {
    if (!selectedStrategy || !dateRange[0] || !dateRange[1]) return
    setLoading(true)
    setResult(null)
    setOptResult(null)

    const payload = {
      strategy: selectedStrategy,
      params: strategyParams,
      start_date: dateRange[0].format('YYYY-MM-DD'),
      end_date: dateRange[1].format('YYYY-MM-DD'),
      config,
      optimization: optEnabled
        ? {
            enabled: true,
            param_ranges: optRanges,
            optimize_metric: optMetric,
            max_iterations: optMaxIter,
            top_n: optTopN,
          } as OptimizationConfig
        : undefined,
    }

    try {
      if (optEnabled) {
        const res = await runOptimization(payload)
        setOptResult(res.result)
        message.success(`参数优化完成，共测试 ${res.result.total_combinations} 种组合`)
      } else {
        const res = await runBacktest(payload)
        setResult(res.result as BacktestResult)
        message.success('回测完成')
      }
    } catch (e: any) {
      message.error('失败: ' + (e.message || '未知错误'))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{ padding: 16 }}>
      <Title level={4} style={{ marginBottom: 16 }}>
        <BarChartOutlined /> 回测中心
      </Title>

      <Row gutter={16}>
        {/* 配置区 */}
        <Col span={8}>
          <BacktestConfigPanel
            strategies={strategies}
            strategiesLoading={strategiesLoading}
            selectedStrategy={selectedStrategy}
            strategyParams={strategyParams}
            dateRange={dateRange}
            config={config}
            optEnabled={optEnabled}
            optMetric={optMetric}
            optMaxIter={optMaxIter}
            optTopN={optTopN}
            optRanges={optRanges}
            loading={loading}
            onStrategyChange={handleStrategyChange}
            onStrategyParamsChange={setStrategyParams}
            onDateRangeChange={setDateRange}
            onConfigChange={setConfig}
            onOptEnabledChange={setOptEnabled}
            onOptMetricChange={setOptMetric}
            onOptMaxIterChange={setOptMaxIter}
            onOptTopNChange={setOptTopN}
            onOptRangesChange={setOptRanges}
            onRun={handleRun}
          />
        </Col>

        {/* 结果区 */}
        <Col span={16}>
          {optResult && !loading ? (
            <OptimizationResultsTable optResult={optResult} />
          ) : (
            <BacktestResultsPanel
              result={result}
              loading={loading}
              optEnabled={optEnabled}
            />
          )}
        </Col>
      </Row>
    </div>
  )
}
