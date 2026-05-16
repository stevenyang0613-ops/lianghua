import { memo, useCallback } from 'react'
import { Card, Form, Select, InputNumber, DatePicker, Button, Divider, Typography } from 'antd'
import { PlayCircleOutlined, ThunderboltOutlined } from '@ant-design/icons'
import dayjs from 'dayjs'
import type { BacktestConfig, StrategyInfo, OptimizationParamRange } from '../../services/api'
import CostConfigSection from './CostConfigSection'
import OptimizationConfigSection from './OptimizationConfigSection'

const { Text } = Typography
const { RangePicker } = DatePicker

const METRIC_OPTIONS: { value: string; label: string }[] = [
  { value: 'sharpe_ratio', label: 'Sharpe比率' },
  { value: 'total_return_pct', label: '总收益率' },
  { value: 'annual_return_pct', label: '年化收益率' },
  { value: 'calmar_ratio', label: 'Calmar比率' },
  { value: 'sortino_ratio', label: 'Sortino比率' },
  { value: 'win_rate', label: '胜率' },
]

export { METRIC_OPTIONS }

interface BacktestConfigPanelProps {
  strategies: StrategyInfo[]
  strategiesLoading: boolean
  selectedStrategy: string
  strategyParams: Record<string, number>
  dateRange: [dayjs.Dayjs, dayjs.Dayjs]
  config: BacktestConfig
  optEnabled: boolean
  optMetric: string
  optMaxIter: number
  optTopN: number
  optRanges: OptimizationParamRange[]
  loading: boolean
  onStrategyChange: (id: string) => void
  onStrategyParamsChange: (params: Record<string, number>) => void
  onDateRangeChange: (range: [dayjs.Dayjs, dayjs.Dayjs]) => void
  onConfigChange: (config: BacktestConfig) => void
  onOptEnabledChange: (enabled: boolean) => void
  onOptMetricChange: (metric: string) => void
  onOptMaxIterChange: (val: number) => void
  onOptTopNChange: (val: number) => void
  onOptRangesChange: (ranges: OptimizationParamRange[]) => void
  onRun: () => void
}

const BacktestConfigPanel = memo(function BacktestConfigPanel({
  strategies,
  strategiesLoading,
  selectedStrategy,
  strategyParams,
  dateRange,
  config,
  optEnabled,
  optMetric,
  optMaxIter,
  optTopN,
  optRanges,
  loading,
  onStrategyChange,
  onStrategyParamsChange,
  onDateRangeChange,
  onConfigChange,
  onOptEnabledChange,
  onOptMetricChange,
  onOptMaxIterChange,
  onOptTopNChange,
  onOptRangesChange,
  onRun,
}: BacktestConfigPanelProps) {
  const currentStrategy = strategies.find((s) => s.id === selectedStrategy)

  const handleParamChange = useCallback((name: string, value: number | null, defaultVal: number) => {
    onStrategyParamsChange({ ...strategyParams, [name]: value ?? defaultVal })
  }, [strategyParams, onStrategyParamsChange])

  return (
    <Card title="策略配置" size="small" loading={strategiesLoading}>
      <Form layout="vertical" size="small">
        <Form.Item label="策略">
          <Select value={selectedStrategy} onChange={onStrategyChange}>
            {strategies.map((s) => (
              <Select.Option key={s.id} value={s.id}>
                {s.name}
              </Select.Option>
            ))}
          </Select>
        </Form.Item>

        {currentStrategy?.description && (
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 12 }}>
            {currentStrategy.description}
          </Text>
        )}

        {currentStrategy?.params.map((p) => (
          <Form.Item key={p.name} label={p.label}>
            <InputNumber
              style={{ width: '100%' }}
              min={p.min_val}
              max={p.max_val}
              value={strategyParams[p.name]}
              onChange={(v) => handleParamChange(p.name, v, p.default)}
            />
          </Form.Item>
        ))}

        <Form.Item label="回测区间">
          <RangePicker
            style={{ width: '100%' }}
            value={dateRange}
            onChange={(dates) => {
              if (dates && dates[0] && dates[1]) onDateRangeChange([dates[0], dates[1]])
            }}
          />
        </Form.Item>

        <Divider style={{ margin: '8px 0' }} />

        <CostConfigSection config={config} onConfigChange={onConfigChange} />

        <OptimizationConfigSection
          optEnabled={optEnabled}
          optMetric={optMetric}
          optMaxIter={optMaxIter}
          optTopN={optTopN}
          optRanges={optRanges}
          onOptEnabledChange={onOptEnabledChange}
          onOptMetricChange={onOptMetricChange}
          onOptMaxIterChange={onOptMaxIterChange}
          onOptTopNChange={onOptTopNChange}
          onOptRangesChange={onOptRangesChange}
        />

        <Button
          type="primary"
          icon={optEnabled ? <ThunderboltOutlined /> : <PlayCircleOutlined />}
          onClick={onRun}
          loading={loading}
          block
        >
          {optEnabled ? '运行参数优化' : '运行回测'}
        </Button>
      </Form>
    </Card>
  )
})

export default BacktestConfigPanel
