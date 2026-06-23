import React, { useState } from 'react'
import { Card, Typography, InputNumber } from 'antd'

const { Text } = Typography

export const SignalConfigCard = React.memo(function SignalConfigCard() {
  const [minConfidence, setMinConfidence] = useState(() => {
    const raw = localStorage.getItem('signal_min_confidence') || '0'
    const val = Number.isFinite(Number(raw)) ? Number(raw) : 0
    return val
  })
  const [maxSignals, setMaxSignals] = useState(() => {
    const raw = localStorage.getItem('signal_max_signals') || '20'
    const val = Number.isFinite(Number(raw)) ? Number(raw) : 20
    return val
  })

  return (
    <Card title="信号配置" style={{ marginBottom: 16 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <div>
          <Text>最小置信度阈值</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>低于此值的信号不显示 (0.0 ~ 1.0)</Text>
        </div>
        <InputNumber min={0} max={1} step={0.05} value={minConfidence} onChange={v => { const val = v ?? 0; setMinConfidence(val); localStorage.setItem('signal_min_confidence', String(val)) }} style={{ width: 120 }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <Text>最大信号数量</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>单次刷新显示的最大信号数</Text>
        </div>
        <InputNumber min={5} max={100} step={5} value={maxSignals} onChange={v => { const val = v ?? 20; setMaxSignals(val); localStorage.setItem('signal_max_signals', String(val)) }} style={{ width: 120 }} />
      </div>
    </Card>
  )
})
