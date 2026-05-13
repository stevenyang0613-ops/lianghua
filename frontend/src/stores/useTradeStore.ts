import { create } from 'zustand'
import { devtools } from 'zustand/middleware'

interface Account {
  total_asset: number
  cash: number
  frozen: number
  market_value: number
  daily_profit: number
  total_profit: number
  updated_at: string
}

interface Position {
  code: string
  name: string
  volume: number
  available_volume: number
  cost_price: number
  current_price: number
  market_value: number
  profit_pct: number
  profit_amount: number
}

interface Order {
  id: string
  code: string
  name: string
  side: string
  type: string
  price: number
  volume: number
  filled_volume: number
  status: string
  created_at: string
  updated_at: string | null
  reject_reason: string
}

interface FundPoint {
  ts: string
  total_asset: number
  cash: number
  market_value: number
  total_profit: number
}

interface TradeState {
  account: Account | null
  positions: Position[]
  orders: Order[]
  fundCurve: FundPoint[]
  loading: boolean
  setAccount: (acc: Account) => void
  setPositions: (pos: Position[]) => void
  setOrders: (orders: Order[]) => void
  setFundCurve: (curve: FundPoint[]) => void
  setLoading: (v: boolean) => void
}

export const useTradeStore = create<TradeState>()(
  devtools(
    (set) => ({
      account: null,
      positions: [],
      orders: [],
      fundCurve: [],
      loading: false,
      setAccount: (account) => set({ account }),
      setPositions: (positions) => set({ positions }),
      setOrders: (orders) => set({ orders }),
      setFundCurve: (fundCurve) => set({ fundCurve }),
      setLoading: (loading) => set({ loading }),
    }),
    { name: 'trade-store' }
  )
)
