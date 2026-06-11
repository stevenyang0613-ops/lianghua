import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

vi.mock('../../services/api', () => ({
  placeOrder: vi.fn(() => Promise.resolve({ status: 'filled' })),
}))

vi.mock('../../utils/electron', () => ({
  isElectron: () => false,
}))

import TradePanel from '../trade/TradePanel'

describe('TradePanel', () => {
  const baseProps = {
    allBonds: [{ code: '123456', name: 'Test Bond', price: 100 }],
    account: null,
    loading: false,
    setLoading: vi.fn(),
    onOrderPlaced: vi.fn(),
  }

  it('should render without crashing', () => {
    const { container } = render(<TradePanel {...baseProps} />)
    expect(container.querySelector('.ant-form')).toBeDefined()
  })
})
