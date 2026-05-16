/**
 * 拖拽排序 Hook
 * 列表拖拽排序，支持虚拟列表
 */

import { useState, useCallback, useRef, useEffect } from 'react'

export interface DragSortItem {
  id: string
  [key: string]: unknown
}

export interface UseDragSortOptions<T extends DragSortItem> {
  items: T[]
  onReorder: (items: T[]) => void
  keyField?: string
  dragHandle?: boolean
}

interface DragState {
  draggingId: string | null
  dragOverId: string | null
  dragStartY: number
  dragOffsetY: number
}

export function useDragSort<T extends DragSortItem>(
  options: UseDragSortOptions<T>
) {
  const { items, onReorder, keyField = 'id', dragHandle = false } = options

  const [state, setState] = useState<DragState>({
    draggingId: null,
    dragOverId: null,
    dragStartY: 0,
    dragOffsetY: 0,
  })

  const containerRef = useRef<HTMLDivElement>(null)
  const itemRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  const dragIdRef = useRef<string | null>(null)

  /**
   * 获取项目位置
   */
  const getItemPosition = useCallback((id: string): number => {
    return items.findIndex(item => item[keyField] === id)
  }, [items, keyField])

  /**
   * 开始拖拽
   */
  const handleDragStart = useCallback((id: string, e: React.DragEvent | React.MouseEvent) => {
    e.preventDefault()

    const startY = 'clientY' in e ? e.clientY : (e as React.MouseEvent).clientY
    const rect = itemRefs.current.get(id)?.getBoundingClientRect()

    setState(prev => ({
      ...prev,
      draggingId: id,
      dragStartY: startY,
      dragOffsetY: rect ? startY - rect.top : 0,
    }))

    dragIdRef.current = id
  }, [])

  /**
   * 拖拽悬停
   */
  const handleDragOver = useCallback((id: string, e: React.DragEvent | React.MouseEvent) => {
    if (!state.draggingId || state.draggingId === id) return

    e.preventDefault()

    setState(prev => ({ ...prev, dragOverId: id }))

    // 计算插入位置
    const dragIndex = getItemPosition(state.draggingId)
    const overIndex = getItemPosition(id)

    if (dragIndex !== overIndex) {
      const newItems = [...items]
      const [removed] = newItems.splice(dragIndex, 1)
      newItems.splice(overIndex, 0, removed)
      onReorder(newItems)
    }
  }, [state.draggingId, items, getItemPosition, onReorder])

  /**
   * 拖拽结束
   */
  const handleDragEnd = useCallback(() => {
    setState({
      draggingId: null,
      dragOverId: null,
      dragStartY: 0,
      dragOffsetY: 0,
    })
    dragIdRef.current = null
  }, [])

  /**
   * 鼠标移动
   */
  const handleMouseMove = useCallback((e: MouseEvent) => {
    if (!state.draggingId) return

    const container = containerRef.current
    if (!container) return

    // 查找悬停的元素
    const elements = container.querySelectorAll('[data-drag-id]')
    elements.forEach(el => {
      const rect = el.getBoundingClientRect()
      const id = el.getAttribute('data-drag-id')
      if (id && id !== state.draggingId) {
        if (e.clientY >= rect.top && e.clientY <= rect.bottom) {
          if (state.dragOverId !== id) {
            handleDragOver(id, e as unknown as React.MouseEvent)
          }
        }
      }
    })
  }, [state.draggingId, state.dragOverId, handleDragOver])

  /**
   * 鼠标释放
   */
  const handleMouseUp = useCallback(() => {
    handleDragEnd()
  }, [handleDragEnd])

  // 绑定全局事件
  useEffect(() => {
    if (state.draggingId) {
      document.addEventListener('mousemove', handleMouseMove)
      document.addEventListener('mouseup', handleMouseUp)
      return () => {
        document.removeEventListener('mousemove', handleMouseMove)
        document.removeEventListener('mouseup', handleMouseUp)
      }
    }
  }, [state.draggingId, handleMouseMove, handleMouseUp])

  /**
   * 获取项目属性
   */
  const getItemProps = useCallback((item: T) => {
    const id = item[keyField] as string
    const isDragging = state.draggingId === id
    const isOver = state.dragOverId === id

    return {
      'data-drag-id': id,
      ref: (el: HTMLDivElement | null) => {
        if (el) {
          itemRefs.current.set(id, el)
        } else {
          itemRefs.current.delete(id)
        }
      },
      style: {
        opacity: isDragging ? 0.5 : 1,
        cursor: dragHandle ? 'default' : 'grab',
        transition: 'transform 0.2s',
        transform: isOver ? 'scale(1.02)' : undefined,
        boxShadow: isDragging ? '0 4px 12px rgba(0,0,0,0.15)' : undefined,
      } as React.CSSProperties,
      draggable: !dragHandle,
      onDragStart: (e: React.DragEvent) => handleDragStart(id, e),
      onDragOver: (e: React.DragEvent) => handleDragOver(id, e),
      onDragEnd: handleDragEnd,
      onMouseDown: dragHandle ? undefined : (e: React.MouseEvent) => handleDragStart(id, e),
    }
  }, [keyField, state.draggingId, state.dragOverId, dragHandle, handleDragStart, handleDragOver, handleDragEnd])

  /**
   * 获取拖拽手柄属性
   */
  const getHandleProps = useCallback((item: T) => {
    const id = item[keyField] as string

    return {
      style: { cursor: 'grab' } as React.CSSProperties,
      onMouseDown: (e: React.MouseEvent) => {
        e.stopPropagation()
        handleDragStart(id, e)
      },
    }
  }, [keyField, handleDragStart])

  /**
   * 获取容器属性
   */
  const getContainerProps = useCallback(() => ({
    ref: containerRef,
    style: { userSelect: 'none' } as React.CSSProperties,
  }), [])

  /**
   * 移动项目
   */
  const moveItem = useCallback((fromIndex: number, toIndex: number) => {
    if (fromIndex === toIndex) return

    const newItems = [...items]
    const [removed] = newItems.splice(fromIndex, 1)
    newItems.splice(toIndex, 0, removed)
    onReorder(newItems)
  }, [items, onReorder])

  /**
   * 移动到顶部
   */
  const moveToTop = useCallback((id: string) => {
    const index = getItemPosition(id)
    if (index > 0) {
      moveItem(index, 0)
    }
  }, [getItemPosition, moveItem])

  /**
   * 移动到底部
   */
  const moveToBottom = useCallback((id: string) => {
    const index = getItemPosition(id)
    if (index < items.length - 1) {
      moveItem(index, items.length - 1)
    }
  }, [getItemPosition, items.length, moveItem])

  return {
    getItemProps,
    getHandleProps,
    getContainerProps,
    moveItem,
    moveToTop,
    moveToBottom,
    isDragging: state.draggingId !== null,
    draggingId: state.draggingId,
  }
}

export default useDragSort
