/**
 * Hooks 单元测试
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useLeakTracker } from '../utils/memoryLeakDetector'
import { useDragSort } from '../hooks/useDragSort'

describe('useLeakTracker', () => {
  it('应该追踪定时器', () => {
    vi.useFakeTimers()

    const { result } = renderHook(() => useLeakTracker('TestComponent'))

    act(() => {
      const timerId = result.current.setTimeout(() => {}, 1000)
      expect(timerId).toBeDefined()
    })

    vi.useRealTimers()
  })

  it('应该追踪订阅', () => {
    const { result } = renderHook(() => useLeakTracker('TestComponent'))

    act(() => {
      result.current.trackSubscription('sub-1')
    })

    // 组件卸载时会检查未清理的订阅
  })
})

describe('useDragSort', () => {
  const mockItems = [
    { id: '1', name: 'Item 1' },
    { id: '2', name: 'Item 2' },
    { id: '3', name: 'Item 3' },
  ]

  it('应该初始化正确的状态', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragSort({ items: mockItems, onReorder })
    )

    expect(result.current.isDragging).toBe(false)
    expect(result.current.draggingId).toBeNull()
  })

  it('应该提供 getItemProps', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragSort({ items: mockItems, onReorder })
    )

    const props = result.current.getItemProps(mockItems[0])
    expect(props['data-drag-id']).toBe('1')
    expect(props.style).toBeDefined()
  })

  it('应该移动项目', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragSort({ items: mockItems, onReorder })
    )

    act(() => {
      result.current.moveItem(0, 2)
    })

    expect(onReorder).toHaveBeenCalledWith([
      { id: '2', name: 'Item 2' },
      { id: '3', name: 'Item 3' },
      { id: '1', name: 'Item 1' },
    ])
  })

  it('应该移动到顶部', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragSort({ items: mockItems, onReorder })
    )

    act(() => {
      result.current.moveToTop('3')
    })

    expect(onReorder).toHaveBeenCalledWith([
      { id: '3', name: 'Item 3' },
      { id: '1', name: 'Item 1' },
      { id: '2', name: 'Item 2' },
    ])
  })

  it('应该移动到底部', () => {
    const onReorder = vi.fn()
    const { result } = renderHook(() =>
      useDragSort({ items: mockItems, onReorder })
    )

    act(() => {
      result.current.moveToBottom('1')
    })

    expect(onReorder).toHaveBeenCalledWith([
      { id: '2', name: 'Item 2' },
      { id: '3', name: 'Item 3' },
      { id: '1', name: 'Item 1' },
    ])
  })
})
