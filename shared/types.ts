export interface ConvertibleQuote {
  code: string
  name: string
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
