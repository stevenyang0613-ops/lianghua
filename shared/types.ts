export interface ConvertibleQuote {
  code: string
  name: string
  price: number
  change_pct: number
  stock_price: number
  stock_change_pct: number
  conversion_price: number
  conversion_value: number
  premium_ratio: number
  dual_low: number
  ytm: number
  volume: number
  remaining_years: number
  forced_call_days: number
  timestamp: string
}

export interface WsMessage {
  type: 'tick' | 'subscribe' | 'unsubscribe'
  data?: ConvertibleQuote[]
  codes?: string[]
}
