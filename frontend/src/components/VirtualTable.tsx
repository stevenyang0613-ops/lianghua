/**
 * 高性能虚拟滚动表格
 * 支持 10万+ 行数据
 */

import { useEffect, useRef, useState, useCallback, memo, type ReactNode } from 'react'
import { Spin } from 'antd'

interface VirtualColumn<T> {
  key?: string | number
  title?: ReactNode
  dataIndex?: string
  width?: number | string
  render?: (value: unknown, record: T, index: number) => ReactNode
}

interface VirtualTableProps<T> {
  data: readonly T[]
  columns?: VirtualColumn<T>[]
  rowHeight?: number
  visibleRows?: number
  overscan?: number
  onScroll?: (scrollTop: number) => void
  loading?: boolean
  rowKey?: string | ((record: T) => string | number)
}

function VirtualTableInner<T>({
  data,
  rowHeight = 48,
  overscan = 5,
  columns,
  loading,
  onScroll,
  rowKey,
}: VirtualTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [containerHeight, setContainerHeight] = useState(600)

  // 计算可见范围
  const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan)
  const endIndex = Math.min(
    data.length,
    Math.floor((scrollTop + containerHeight) / rowHeight) + overscan
  )

  // 可见数据
  const visibleData = data.slice(startIndex, endIndex)

  // 总高度
  const totalHeight = data.length * rowHeight
  const offsetY = startIndex * rowHeight

  // 滚动处理
  const handleScroll = useCallback((e: React.UIEvent<HTMLDivElement>) => {
    const target = e.currentTarget
    const newScrollTop = target.scrollTop
    setScrollTop(newScrollTop)
    onScroll?.(newScrollTop)
  }, [onScroll])

  // 监听容器高度变化
  useEffect(() => {
    if (!containerRef.current) return

    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerHeight(entry.contentRect.height)
      }
    })

    observer.observe(containerRef.current)
    return () => observer.disconnect()
  }, [])

  // 渲染行
  const renderRow = (record: T, index: number) => {
    const actualIndex = startIndex + index
    return (
      <div
        key={typeof rowKey === 'function' ? rowKey(record) : String((record as Record<string, unknown>)[rowKey as string]) || actualIndex}
        style={{
          height: rowHeight,
          display: 'flex',
          alignItems: 'center',
          borderBottom: '1px solid #f0f0f0',
          boxSizing: 'border-box',
        }}
      >
        {columns?.map((col, colIndex) => {
          const value = col.dataIndex ? (record as Record<string, unknown>)[col.dataIndex] : undefined
          return (
            <div
              key={col.key || col.dataIndex || colIndex}
              style={{
                width: col.width || 100,
                minWidth: col.width || 100,
                padding: '8px 12px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {col.render ? col.render(value, record, actualIndex) : (value as ReactNode)}
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      style={{
        height: '100%',
        overflow: 'auto',
        position: 'relative',
      }}
      onScroll={handleScroll}
    >
      {/* 表头 */}
      <div
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          background: '#fafafa',
          display: 'flex',
          borderBottom: '2px solid #f0f0f0',
        }}
      >
        {columns?.map((col, index) => (
          <div
            key={col.key || col.dataIndex || index}
            style={{
              width: col.width || 100,
              minWidth: col.width || 100,
              padding: '12px',
              fontWeight: 600,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {col.title}
          </div>
        ))}
      </div>

      {/* 虚拟内容区 */}
      <div style={{ height: totalHeight, position: 'relative' }}>
        {loading ? (
          <div
            style={{
              position: 'absolute',
              top: '50%',
              left: '50%',
              transform: 'translate(-50%, -50%)',
            }}
          >
            <Spin />
          </div>
        ) : (
          <div
            style={{
              position: 'absolute',
              top: offsetY,
              left: 0,
              right: 0,
            }}
          >
            {visibleData.map((record, index) => renderRow(record, index))}
          </div>
        )}
      </div>

      {/* 空状态 */}
      {!loading && data.length === 0 && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            height: 200,
            color: '#999',
          }}
        >
          暂无数据
        </div>
      )}
    </div>
  )
}

// 使用 memo 优化
export const VirtualTable = memo(VirtualTableInner) as typeof VirtualTableInner

export default VirtualTable
