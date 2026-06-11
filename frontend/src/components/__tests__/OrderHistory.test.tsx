import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../../utils/export', () => ({
  exportTrades: vi.fn(),
}))

import OrderHistory from '../trade/OrderHistory'

describe('OrderHistory', () => {
  const mockCancel = vi.fn()

  it('should show empty state', () => {
    render(<OrderHistory orders={[]} onCancelOrder={mockCancel} />)
    expect(screen.getByText('暂无委托记录')).toBeDefined()
  })

  it('should render order rows', () => {
    const orders = [
      { id: 'ord1', code: '123456', name: 'Test', side: 'buy', price: 100, volume: 10, filled_volume: 10, status: 'filled', type: 'limit', created_at: '2024-01-01', updated_at: null, reject_reason: '' },
    ]
    render(<OrderHistory orders={orders} onCancelOrder={mockCancel} />)
    expect(screen.getByText('ord1')).toBeDefined()
    expect(screen.getByText('123456')).toBeDefined()
  })
})
