import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import ErrorBoundary from '../ErrorBoundary'

vi.mock('../utils/errorLogger', () => ({ logError: vi.fn() }))

const Bomb = ({ shouldThrow }: { shouldThrow?: boolean }) => {
  if (shouldThrow) throw new Error('test error')
  return <div>正常渲染</div>
}

describe('ErrorBoundary', () => {
  it('should render children when no error', () => {
    render(<ErrorBoundary><div>正常渲染</div></ErrorBoundary>)
    expect(screen.getByText('正常渲染')).toBeDefined()
  })

  it('should show error UI on uncaught error', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ErrorBoundary><Bomb shouldThrow /></ErrorBoundary>)
    expect(screen.getByText('页面出错了')).toBeDefined()
    expect(screen.getByText('查看错误详情')).toBeDefined()
    expect(screen.getByRole('button', { name: /刷新/ })).toBeDefined()
    vi.restoreAllMocks()
  })

  it('should render custom fallback', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    render(<ErrorBoundary fallback={<div>自定义错误页</div>}><Bomb shouldThrow /></ErrorBoundary>)
    expect(screen.getByText('自定义错误页')).toBeDefined()
    vi.restoreAllMocks()
  })
})
