import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

import Sidebar from '../Sidebar'

describe('Sidebar', () => {
  it('should render all menu items', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sidebar collapsed={false} onCollapse={vi.fn()} />
      </MemoryRouter>
    )
    await act(async () => {})
    expect(screen.getByText('实时行情')).toBeDefined()
    expect(screen.getByText('自选列表')).toBeDefined()
    expect(screen.getByText('交易信号')).toBeDefined()
    expect(screen.getByText('回测中心')).toBeDefined()
    expect(screen.getByText('交易终端')).toBeDefined()
    expect(screen.getByText('分析工具')).toBeDefined()
    expect(screen.getByText('策略管理')).toBeDefined()
    expect(screen.getByText('系统设置')).toBeDefined()
  })

  it('should show collapse text when expanded', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sidebar collapsed={false} onCollapse={vi.fn()} />
      </MemoryRouter>
    )
    await act(async () => {})
    expect(screen.getByText('收起侧栏')).toBeDefined()
  })

  it('should hide collapse text when collapsed', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sidebar collapsed={true} onCollapse={vi.fn()} />
      </MemoryRouter>
    )
    await act(async () => {})
    expect(screen.queryByText('收起侧栏')).toBeNull()
  })

  it('should call navigate on menu click', async () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sidebar collapsed={false} onCollapse={vi.fn()} />
      </MemoryRouter>
    )
    await act(async () => {})
    const marketItem = screen.getByText('实时行情').closest('li')
    if (marketItem) fireEvent.click(marketItem)
    expect(mockNavigate).toHaveBeenCalledWith('/')
  })

  it('should call onCollapse when collapse button clicked', async () => {
    const onCollapse = vi.fn()
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Sidebar collapsed={false} onCollapse={onCollapse} />
      </MemoryRouter>
    )
    await act(async () => {})
    const btn = screen.getByText('收起侧栏').closest('button')
    if (btn) fireEvent.click(btn)
    expect(onCollapse).toHaveBeenCalledWith(true)
  })
})