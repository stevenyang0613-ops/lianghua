import { memo, useCallback } from 'react'
import { Form, InputNumber, Collapse } from 'antd'
import { SettingOutlined } from '@ant-design/icons'
import type { BacktestConfig } from '../../services/api'

const { Panel } = Collapse

interface CostConfigSectionProps {
  config: BacktestConfig
  onConfigChange: (config: BacktestConfig) => void
}

const CostConfigSection = memo(function CostConfigSection({
  config,
  onConfigChange,
}: CostConfigSectionProps) {
  const handleFieldChange = useCallback(
    (field: keyof BacktestConfig, value: number | null, fallback: number) => {
      onConfigChange({ ...config, [field]: value ?? fallback })
    },
    [config, onConfigChange]
  )

  return (
    <Collapse ghost style={{ marginBottom: 8 }}>
      <Panel header={<span><SettingOutlined /> 交易成本参数</span>} key="cost">
        <Form.Item label="佣金率" tooltip="每笔交易佣金比例">
          <InputNumber
            style={{ width: '100%' }}
            min={0} max={0.03}
            step={0.0001}
            value={config.commission_pct}
            onChange={(v) => handleFieldChange('commission_pct', v, 0.001)}
          />
        </Form.Item>
        <Form.Item label="滑点率" tooltip="买卖价格滑点比例">
          <InputNumber
            style={{ width: '100%' }}
            min={0} max={0.05}
            step={0.0001}
            value={config.slippage_pct}
            onChange={(v) => handleFieldChange('slippage_pct', v, 0.001)}
          />
        </Form.Item>
        <Form.Item label="最低佣金(元)" tooltip="单笔最低佣金">
          <InputNumber
            style={{ width: '100%' }}
            min={0}
            value={config.min_commission}
            onChange={(v) => handleFieldChange('min_commission', v, 5)}
          />
        </Form.Item>
        <Form.Item label="无风险利率" tooltip="年化无风险利率, 用于Sharpe/Sortino计算">
          <InputNumber
            style={{ width: '100%' }}
            min={0} max={0.1}
            step={0.005}
            value={config.risk_free_rate}
            onChange={(v) => handleFieldChange('risk_free_rate', v, 0.02)}
          />
        </Form.Item>
      </Panel>
    </Collapse>
  )
})

export default CostConfigSection
