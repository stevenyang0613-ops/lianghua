import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import BackendLoading from '../BackendLoading'

vi.mock('../../services/api', () => ({
  healthCheck: vi.fn(() => Promise.reject(new Error('no backend'))),
}))

const mockSetBackendConnected = vi.fn()
vi.mock('../../stores/useAppStore', () => ({
  useAppStore: vi.fn((selector: any) => {
    const state = { backendConnected: false, setBackendConnected: vi.fn() }
    return selector ? selector(state) : state
  }),
}))

describe('BackendLoading', () => {
  it('should show loading state when backend not connected', () => {
    render(<BackendLoading><div>app content</div></BackendLoading>)
    expect(screen.getByText('LiangHua')).toBeDefined()
    expect(screen.getByText(/可转债量化交易系统/)).toBeDefined()
  })

  it('should render children when backend is connected', async () => {
    const { useAppStore } = await import('../../stores/useAppStore')
    const spy = vi.mocked(useAppStore)
    spy.mockImplementation((selector: any) => {
      const state = { backendConnected: true, setBackendConnected: mockSetBackendConnected }
      return selector ? selector(state) : state
    })
    render(<BackendLoading><div>app content</div></BackendLoading>)
    expect(screen.getByText('app content')).toBeDefined()
    spy.mockRestore()
  })
})
