import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('../../utils/export', () => ({
  exportPositions: vi.fn(),
}))

import PositionTable from '../trade/PositionTable'

describe('PositionTable', () => {
  it('should show empty state when no positions', () => {
    render(<PositionTable positions={[]} />)
    expect(screen.getByText('暂无持仓')).toBeDefined()
  })

  it('should render positions table', () => {
    const positions = [
      { code: '123456', name: 'Test Bond', volume: 100, available_volume: 100, cost_price: 100, current_price: 101, market_value: 10100, profit_amount: 100, profit_pct: 1 },
    ]
    render(<PositionTable positions={positions} />)
    expect(screen.getByText('123456')).toBeDefined()
  })
})
