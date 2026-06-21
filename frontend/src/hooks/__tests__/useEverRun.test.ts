import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useEverRun } from '../useEverRun'

describe('useEverRun', () => {
  const STORAGE_KEY = 'test_ever_run'

  beforeEach(() => {
    localStorage.clear()
  })

  it('returns false initially when no localStorage and no conditions met', () => {
    const { result } = renderHook(() => useEverRun(STORAGE_KEY, [false, false]))
    expect(result.current).toBe(false)
  })

  it('returns true when localStorage has true value', () => {
    localStorage.setItem(STORAGE_KEY, 'true')
    const { result } = renderHook(() => useEverRun(STORAGE_KEY, [false, false]))
    expect(result.current).toBe(true)
  })

  it('transitions to true when any condition becomes true', () => {
    const { result, rerender } = renderHook(
      ({ conditions }) => useEverRun(STORAGE_KEY, conditions),
      { initialProps: { conditions: [false, false] as boolean[] } }
    )
    expect(result.current).toBe(false)

    rerender({ conditions: [true, false] })
    expect(result.current).toBe(true)
  })

  it('persists to localStorage when condition is met', () => {
    const { rerender } = renderHook(
      ({ conditions }) => useEverRun(STORAGE_KEY, conditions),
      { initialProps: { conditions: [false] as boolean[] } }
    )

    rerender({ conditions: [true] })
    expect(localStorage.getItem(STORAGE_KEY)).toBe('true')
  })

  it('does not error when key is empty', () => {
    const { rerender } = renderHook(
      ({ conditions }) => useEverRun('', conditions),
      { initialProps: { conditions: [false] as boolean[] } }
    )

    rerender({ conditions: [true] })
    // Empty key still works — localStorage.setItem('', 'true') is valid
    expect(true).toBe(true)
  })

  it('stays true once set even if conditions go back to false', () => {
    const { result, rerender } = renderHook(
      ({ conditions }) => useEverRun(STORAGE_KEY, conditions),
      { initialProps: { conditions: [true] as boolean[] } }
    )
    expect(result.current).toBe(true)

    rerender({ conditions: [false] })
    expect(result.current).toBe(true)
  })

  it('does not re-trigger effect when conditions array reference changes but values stay same', () => {
    const { result, rerender } = renderHook(
      ({ conditions }) => useEverRun(STORAGE_KEY + '_stable', conditions),
      { initialProps: { conditions: [false] as boolean[] } }
    )
    expect(result.current).toBe(false)

    // New array reference, same values — should NOT trigger transition
    rerender({ conditions: [false] })
    expect(result.current).toBe(false)
    expect(localStorage.getItem(STORAGE_KEY + '_stable')).toBeNull()
  })

  it('coerces non-boolean truthy values correctly', () => {
    const { result, rerender } = renderHook(
      ({ conditions }) => useEverRun(STORAGE_KEY + '_coerce', conditions as boolean[]),
      { initialProps: { conditions: [0 as any, '' as any] } }
    )
    expect(result.current).toBe(false)

    // [1, ''] → Boolean() → [true, false] → some → true
    rerender({ conditions: [1 as any, '' as any] })
    expect(result.current).toBe(true)
    expect(localStorage.getItem(STORAGE_KEY + '_coerce')).toBe('true')
  })
})
