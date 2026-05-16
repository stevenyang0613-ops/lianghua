import { memo, useCallback } from 'react'
import { Form, Select, InputNumber, Collapse, Switch, Typography, Divider, Row, Col } from 'antd'
import { ThunderboltOutlined, ExperimentOutlined } from '@ant-design/icons'
import { METRIC_OPTIONS } from './BacktestConfigPanel'
import type { OptimizationParamRange } from '../../services/api'

const { Text } = Typography
const { Panel } = Collapse

interface OptimizationConfigSectionProps {
  optEnabled: boolean
  optMetric: string
  optMaxIter: number
  optTopN: number
  optRanges: OptimizationParamRange[]
  onOptEnabledChange: (enabled: boolean) => void
  onOptMetricChange: (metric: string) => void
  onOptMaxIterChange: (val: number) => void
  onOptTopNChange: (val: number) => void
  onOptRangesChange: (ranges: OptimizationParamRange[]) => void
}

const OptimizationConfigSection = memo(function OptimizationConfigSection({
  optEnabled,
  optMetric,
  optMaxIter,
  optTopN,
  optRanges,
  onOptEnabledChange,
  onOptMetricChange,
  onOptMaxIterChange,
  onOptTopNChange,
  onOptRangesChange,
}: OptimizationConfigSectionProps) {
  const updateOptRange = useCallback(
    (idx: number, field: keyof OptimizationParamRange, value: number) => {
      onOptRangesChange(
        optRanges.map((r, i) => (i === idx ? { ...r, [field]: value } : r))
      )
    },
    [optRanges, onOptRangesChange]
  )

  return (
    <>
      {/* 参数优化开关 */}
      <div style={{ marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
        <ExperimentOutlined />
        <Switch checked={optEnabled} onChange={onOptEnabledChange} checkedChildren="优化开" unCheckedChildren="优化关" />
        <Text type="secondary" style={{ fontSize: 12 }}>参数优化</Text>
      </div>

      {optEnabled && (
        <Collapse ghost defaultActiveKey="opt" style={{ marginBottom: 8 }}>
          <Panel header={<span><ThunderboltOutlined /> 优化设置</span>} key="opt">
            <Form.Item label="优化目标">
              <Select value={optMetric} onChange={onOptMetricChange}>
                {METRIC_OPTIONS.map((m) => (
                  <Select.Option key={m.value} value={m.value}>{m.label}</Select.Option>
                ))}
              </Select>
            </Form.Item>
            <Form.Item label="最大迭代">
              <InputNumber style={{ width: '100%' }} min={1} max={10000} value={optMaxIter}
                onChange={(v) => onOptMaxIterChange(v ?? 100)} />
            </Form.Item>
            <Form.Item label="Top N">
              <InputNumber style={{ width: '100%' }} min={1} max={100} value={optTopN}
                onChange={(v) => onOptTopNChange(v ?? 10)} />
            </Form.Item>
            <Divider style={{ margin: '8px 0' }} />
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>
              参数搜索范围:
            </Text>
            {optRanges.map((r, idx) => (
              <div key={r.name} style={{ marginBottom: 8, padding: 8, background: '#f5f5f5', borderRadius: 4 }}>
                <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>{r.name}</Text>
                <Row gutter={4}>
                  <Col span={8}>
                    <InputNumber size="small" style={{ width: '100%' }} placeholder="min"
                      value={r.min_val}
                      onChange={(v) => updateOptRange(idx, 'min_val', v ?? 0)} />
                  </Col>
                  <Col span={8}>
                    <InputNumber size="small" style={{ width: '100%' }} placeholder="max"
                      value={r.max_val}
                      onChange={(v) => updateOptRange(idx, 'max_val', v ?? 0)} />
                  </Col>
                  <Col span={8}>
                    <InputNumber size="small" style={{ width: '100%' }} placeholder="step"
                      value={r.step}
                      onChange={(v) => updateOptRange(idx, 'step', v ?? 1)} />
                  </Col>
                </Row>
              </div>
            ))}
          </Panel>
        </Collapse>
      )}
    </>
  )
})

export default OptimizationConfigSection
