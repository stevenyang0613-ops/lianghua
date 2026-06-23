export interface ConvertibleQuote {
  code: string
  name: string
  stock_code?: string
  stock_name?: string
  price: number | undefined
  change_pct: number | undefined
  stock_price: number | undefined
  stock_change_pct: number | undefined
  conversion_price: number | undefined
  conversion_value: number | undefined
  premium_ratio: number | undefined
  dual_low: number | undefined
  ytm: number | undefined
  volume: number | undefined
  remaining_years: number | undefined
  forced_call_days: number | undefined
  is_called: boolean | undefined
  call_status: string | undefined
  last_trade_date: string | undefined
  maturity_date: string | undefined
  redemption_price: number | undefined
  industry?: string
  roe?: number
  gpm?: number
  cagr?: number
  debt_ratio?: number
  current_ratio?: number
  pe?: number
  pb?: number
  iv?: number
  iv_source?: string
  hv?: number
  rating?: string
  rating_score?: number
  pure_bond_premium_ratio?: number
  bond_value?: number
  buyback_amount?: number
  mgmt_buy_price?: number
  turnover_rate?: number
  net_capital_flow?: number
  net_capital_flow_pct?: number
  net_super_flow?: number
  net_big_flow?: number
  outstanding_scale?: number
  pledge_ratio?: number
  momentum_5d?: number
  momentum_10d?: number
  momentum_20d?: number
  momentum_60d?: number
  event_score?: number
  event_detail?: string
  concepts?: string[]
  north_net?: number
  margin_balance?: number
  lhb_count?: number
  block_trade_amount?: number
  holder_num_change?: number
  eps_forecast?: number
  eps?: number
  bps?: number
  revenue_yoy?: number
  profit_yoy?: number
  restricted_release_amount?: number
  sentiment_score?: number
  macro_cpi?: number
  macro_ppi?: number
  macro_m2?: number
  macro_lpr?: number
  macro_policy_score?: number
  macro_event_score?: number
  timestamp: string
}

export interface WsMessage {
  type: 'tick' | 'subscribe' | 'unsubscribe'
  data?: ConvertibleQuote[]
  codes?: string[]
}

/** Electron IPC 与前端共用的 WS 状态常量，杜绝字符串不匹配 */
export const WsIpcState = {
  CONNECTED: 'connected',
  DISCONNECTED: 'disconnected',
  CONNECTING: 'connecting',
  ERROR: 'error',
} as const

export type WsIpcStateType = (typeof WsIpcState)[keyof typeof WsIpcState]

/** WS 错误码到用户友好描述的映射 */
export const WsErrorDescriptions: Record<number, string> = {
  4001: '认证失败，请重启应用',
  5030: '服务端引擎未就绪，请稍后重试',
  1011: '服务端内部错误',
  1013: '连接数超限，请关闭多余窗口',
  1006: '连接异常断开，正在重连',
  1000: '连接已关闭',
}
