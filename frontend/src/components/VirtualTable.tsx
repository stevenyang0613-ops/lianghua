/**
 * 高性能虚拟滚动表格
 * 支持 10万+ 行数据 + 列头点击排序
 */

import { useEffect, useRef, useState, useCallback, useMemo, memo, type ReactNode } from 'react'
import { Spin } from 'antd'

export type SortOrder = 'asc' | 'desc' | null

export interface VirtualColumn<T> {
  key?: string | number
  title?: ReactNode
  dataIndex?: string
  width?: number | string
  render?: (value: unknown, record: T, index: number) => ReactNode
  /** 启用列头点击排序。设置为 true 时,点击列头会通过 onSort 回调通知父组件 */
  sortable?: boolean
  /** 当前列的排序方向(由父组件控制),与 sorter 配合使用 */
  sortOrder?: SortOrder
  /** 自定义排序比较函数;省略时按 dataIndex 取值做数值/字符串比较 */
  sorter?: (a: T, b: T) => number
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
  onRowClick?: (record: T, index: number) => void
  /** 列头排序事件(仅对 sortable=true 的列触发),dataIndex 可能为 undefined */
  onSort?: (dataIndex: string | number | undefined, column: VirtualColumn<T>) => void
}

function VirtualTableInner<T>({
  data,
  rowHeight = 48,
  overscan = 5,
  columns,
  loading,
  onScroll,
  rowKey,
  onRowClick,
  onSort,
}: VirtualTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [scrollTop, setScrollTop] = useState(0)
  const [containerHeight, setContainerHeight] = useState(600)

  // 计算所有列总宽度，用于水平滚动
  const totalWidth = useMemo(() =>
    columns?.reduce((sum, col) => sum + (typeof col.width === 'number' ? col.width : 100), 0) || 800,
    [columns]
  )

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
          cursor: onRowClick ? 'pointer' : undefined,
        }}
        onClick={() => onRowClick?.(record, actualIndex)}
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

  const handleHeaderClick = (col: VirtualColumn<T>) => {
    if (!col.sortable) return
    onSort?.(col.dataIndex, col)
  }

  const renderSortIndicator = (col: VirtualColumn<T>) => {
    if (!col.sortable) return null
    const order = col.sortOrder
    const isActive = order === 'asc' || order === 'desc'
    const arrow = order === 'asc' ? '▲' : order === 'desc' ? '▼' : '⇅'
    return (
      <span
        aria-hidden
        style={{
          marginLeft: 4,
          fontSize: 10,
          color: isActive ? '#1677ff' : '#bbb',
          userSelect: 'none',
          transition: 'color 0.15s',
        }}
      >
        {arrow}
      </span>
    )
  }

  return (
    <div
      ref={containerRef}
      className="virtual-table"
      style={{
        height: '100%',
        overflow: 'auto',
        position: 'relative',
        fontSize: 'var(--table-cell-font-size, 13px)',
      }}
      onScroll={handleScroll}
    >
      {/* 表头 - 与内容区同宽实现水平滚动同步 */}
      <div
        className="vt-header"
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 10,
          background: '#fafafa',
          display: 'flex',
          borderBottom: '2px solid #f0f0f0',
          minWidth: totalWidth,
          fontSize: 'var(--table-header-font-size, 13px)',
        }}
      >
        {columns?.map((col, index) => (
          <div
            key={col.key || col.dataIndex || index}
            onClick={() => handleHeaderClick(col)}
            className={col.sortable ? 'vt-header-cell sortable' : 'vt-header-cell'}
            style={{
              width: col.width || 100,
              minWidth: col.width || 100,
              padding: '12px',
              fontWeight: 600,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              cursor: col.sortable ? 'pointer' : 'default',
              userSelect: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: 2,
            }}
            data-testid={col.sortable ? `vt-sort-${col.dataIndex}` : undefined}
            role={col.sortable ? 'button' : undefined}
            aria-sort={
              col.sortOrder === 'asc' ? 'ascending' :
              col.sortOrder === 'desc' ? 'descending' :
              'none'
            }
            title={typeof col.title === 'string' ? col.title : undefined}
          >
            <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{col.title}</span>
            {renderSortIndicator(col)}
          </div>
        ))}
      </div>

      {/* 虚拟内容区 - minWidth 保证水平滚动时列不收缩 */}
      <div style={{ height: totalHeight, position: 'relative', minWidth: totalWidth }}>
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
