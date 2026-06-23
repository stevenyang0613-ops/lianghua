/**
 * 数据来源标签组件
 *
 * 根据后端返回的 data_source 字段展示对应颜色的 Tag。
 * 数据来源：
 *   - real:      绿色 ✅ 来自真实 API
 *   - estimated: 黄色 ⚠️ 模型估算
 *   - fallback:  橙色 ⚠️ 后端兜底
 *   - mock:      灰色 🔧 仅作演示
 *   - missing:   红色 ❌ 数据缺失
 */

import React from 'react'
import { Tag, Tooltip } from 'antd'

export type DataSourceType = 'real' | 'estimated' | 'fallback' | 'mock' | 'missing' | string

interface DataSourceBadgeProps {
  source: DataSourceType | null | undefined
  size?: 'small' | 'default'
}

const META: Record<string, { color: string; label: string; tip: string }> = {
  real:      { color: 'success', label: '真实',  tip: '来自交易所/官方 API（AKShare/TDX/Sina 等）' },
  estimated: { color: 'warning', label: '估算',  tip: '由模型基于其他字段估算（如 IV/历史波动率）' },
  fallback:  { color: 'orange',  label: '兜底',  tip: '上游数据缺失，后端生成的兜底值' },
  mock:      { color: 'default', label: '演示',  tip: '演示用途的合成数据，不进入交易/回测' },
  missing:   { color: 'error',   label: '缺失',  tip: '数据源返回空值' },
}

export function DataSourceBadge({ source, size = 'small' }: DataSourceBadgeProps) {
  const meta = source ? META[source] : null
  if (!meta) {
    return (
      <Tooltip title="未标记数据源（后端响应缺少 data_source 字段）">
        <Tag color="default" style={{ margin: 0 }}>未知</Tag>
      </Tooltip>
    )
  }
  return (
    <Tooltip title={meta.tip}>
      <Tag color={meta.color} style={{ margin: 0 }} data-testid={`data-source-${source}`}>
        {meta.label}
      </Tag>
    </Tooltip>
  )
}

/**
 * 整批数据源标签（用于表格顶部展示）
 */
export function DataSourcePanel({ source, count }: { source: DataSourceType | null | undefined; count?: number }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#666' }}>
      <span>数据来源：</span>
      <DataSourceBadge source={source} />
      {typeof count === 'number' && <span>共 {count} 条</span>}
    </div>
  )
}
