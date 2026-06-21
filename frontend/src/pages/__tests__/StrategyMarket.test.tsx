import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import StrategyMarket from '../StrategyMarket'
import * as strategyShare from '../../utils/strategyShare'

// Mock fetch globally
global.fetch = vi.fn()

const mockStrategies = [
  {
    id: 'cb-dual-low-rotation',
    name: '可转债双低轮动策略',
    description: '经典可转债双低策略',
    author: '方正证券',
    avatar: '',
    category: 'quant',
    tags: ['可转债', '双低'],
    rating: 4.7,
    downloads: 100,
    likes: 50,
    returns: 18.5,
    maxDrawdown: 16.2,
    sharpe: 1.42,
    winRate: 62.3,
    tradeCount: 156,
    createdAt: Date.now(),
    updatedAt: Date.now(),
    code: '',
    params: [{ name: 'hold_count', type: 'int', default: 10, description: '持有数量' }],
  },
]

describe('StrategyMarket', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    ;(global.fetch as any).mockResolvedValue({
      ok: true,
      json: async () => ({
        strategies: mockStrategies.map((s) => ({
          ...s,
          type: 'quant',
          visibility: 'public',
          author: { id: 'system', name: s.author },
          version: '1.0.0',
          status: 'published',
          price: 0,
          stats: { views: 0, likes: s.likes, subscribers: s.downloads, forks: 0, comments: 0, downloads: s.downloads },
          ratings: { average: s.rating, count: 1, distribution: { '1': 0, '2': 0, '3': 0, '4': 0, '5': 1 } },
          backtestResult: {
            totalReturn: s.returns,
            annualizedReturn: s.returns,
            maxDrawdown: s.maxDrawdown,
            sharpeRatio: s.sharpe,
            winRate: s.winRate,
            profitFactor: 1.5,
            tradesCount: s.tradeCount,
            period: '2018-01-01 ~ 2024-12-31',
          },
          config: {},
          params: s.params,
          createdAt: new Date(s.createdAt).toISOString(),
          updatedAt: new Date(s.updatedAt).toISOString(),
        })),
        total: mockStrategies.length,
        page: 1,
        pageSize: 20,
      }),
    })
  })

  it('renders strategy market title', () => {
    render(
      <BrowserRouter>
        <StrategyMarket />
      </BrowserRouter>,
    )
    expect(screen.getByText('策略市场')).toBeInTheDocument()
  })

  it('loads and displays strategies from backend', async () => {
    render(
      <BrowserRouter>
        <StrategyMarket />
      </BrowserRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('可转债双低轮动策略')).toBeInTheDocument()
    })

    expect(screen.getByText('经典可转债双低策略')).toBeInTheDocument()
    expect(screen.getByText('方正证券')).toBeInTheDocument()
  })

  it('falls back to empty state when backend fails', async () => {
    ;(global.fetch as any).mockRejectedValue(new Error('network error'))

    render(
      <BrowserRouter>
        <StrategyMarket />
      </BrowserRouter>,
    )

    await waitFor(() => {
      expect(screen.getByText('暂无策略')).toBeInTheDocument()
    })
  })
})
