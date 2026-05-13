import { useRef, useMemo, useCallback } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Table, Tag, Typography, Spin } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ConvertibleQuote } from '../types'

const { Text } = Typography

interface VirtualTableProps {
  bonds: ConvertibleQuote[]
  loading: boolean
  onRowClick: (code: string) => void
  height?: number
}

export default function VirtualTable({ bonds, loading, onRowClick, height = 600 }: VirtualTableProps) {
  const parentRef = useRef<HTMLDivElement>(null)

  const rowVirtualizer = useVirtualizer({
    count: bonds.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 40,
    overscan: 10,
  })

  const virtualItems = rowVirtualizer.getVirtualItems()

  const getChangeColor = (value: number) => value > 0 ? '#cf1322' : value < 0 ? '#389e0d' : undefined
  const getPremiumColor = (value: number) => value < 0 ? '#52c41a' : value > 50 ? '#faad14' : undefined
  const getDualLowColor = (value: number) => value < 130 ? '#52c41a' : value > 180 ? '#f5222d' : '#faad14'

  if (loading) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <Spin size="large" />
      </div>
    )
  }

  return (
    <div
      ref={parentRef}
      style={{ height, overflow: 'auto', border: '1px solid #f0f0f0', borderRadius: 4 }}
    >
      <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
        <div
          style={{
            position: 'sticky',
            top: 0,
            background: '#fafafa',
            zIndex: 1,
            display: 'flex',
            borderBottom: '2px solid #f0f0f0',
            fontWeight: 600,
            fontSize: 13,
          }}
        >
          <div style={{ width: 80, padding: '8px 12px' }}>代码</div>
          <div style={{ width: 100, padding: '8px 12px' }}>名称</div>
          <div style={{ width: 90, padding: '8px 12px', textAlign: 'right' }}>最新价</div>
          <div style={{ width: 90, padding: '8px 12px', textAlign: 'right' }}>涨跌幅</div>
          <div style={{ width: 80, padding: '8px 12px', textAlign: 'right' }}>正股价</div>
          <div style={{ width: 80, padding: '8px 12px', textAlign: 'right' }}>转股价</div>
          <div style={{ width: 90, padding: '8px 12px', textAlign: 'right' }}>转股价值</div>
          <div style={{ width: 90, padding: '8px 12px', textAlign: 'right' }}>溢价率</div>
          <div style={{ width: 90, padding: '8px 12px', textAlign: 'right' }}>双低值</div>
          <div style={{ width: 100, padding: '8px 12px', textAlign: 'right' }}>成交额(亿)</div>
          <div style={{ width: 90, padding: '8px 12px', textAlign: 'right' }}>剩余年限</div>
        </div>

        {virtualItems.map((virtualRow) => {
          const bond = bonds[virtualRow.index]
          return (
            <div
              key={bond.code}
              style={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                height: virtualRow.size,
                transform: `translateY(${virtualRow.start}px)`,
                display: 'flex',
                borderBottom: '1px solid #f0f0f0',
                cursor: 'pointer',
                background: virtualRow.index % 2 === 0 ? '#fff' : '#fafafa',
              }}
              onClick={() => onRowClick(bond.code)}
              onMouseEnter={(e) => e.currentTarget.style.background = '#e6f7ff'}
              onMouseLeave={(e) => e.currentTarget.style.background = virtualRow.index % 2 === 0 ? '#fff' : '#fafafa'}
            >
              <div style={{ width: 80, padding: '10px 12px', fontFamily: 'monospace' }}>{bond.code}</div>
              <div style={{ width: 100, padding: '10px 12px' }}>{bond.name}</div>
              <div style={{ width: 90, padding: '10px 12px', textAlign: 'right', color: getChangeColor(bond.change_pct), fontWeight: 600, fontFamily: 'monospace' }}>
                {bond.price.toFixed(2)}
              </div>
              <div style={{ width: 90, padding: '10px 12px', textAlign: 'right' }}>
                <Tag color={getChangeColor(bond.change_pct)} style={{ fontFamily: 'monospace' }}>
                  {bond.change_pct > 0 ? '+' : ''}{bond.change_pct.toFixed(2)}%
                </Tag>
              </div>
              <div style={{ width: 80, padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace' }}>{bond.stock_price.toFixed(2)}</div>
              <div style={{ width: 80, padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace' }}>{bond.conversion_price.toFixed(2)}</div>
              <div style={{ width: 90, padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace' }}>{bond.conversion_value.toFixed(2)}</div>
              <div style={{ width: 90, padding: '10px 12px', textAlign: 'right', color: getPremiumColor(bond.premium_ratio), fontWeight: 600 }}>
                {bond.premium_ratio.toFixed(2)}%
              </div>
              <div style={{ width: 90, padding: '10px 12px', textAlign: 'right', color: getDualLowColor(bond.dual_low), fontWeight: 600 }}>
                {bond.dual_low.toFixed(2)}
              </div>
              <div style={{ width: 100, padding: '10px 12px', textAlign: 'right', fontFamily: 'monospace' }}>{bond.volume.toFixed(2)}</div>
              <div style={{ width: 90, padding: '10px 12px', textAlign: 'right' }}>{bond.remaining_years.toFixed(1)}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
