/**
 * 安全数值格式化工具
 *
 * 防止 undefined/null.toFixed() 崩溃 和 NaN显示
 * 用法: fmt(value, digits, fallback) 替代 value.toFixed(digits)
 */

export const fmt = (v: number | undefined | null, digits = 2, fallback = '-'): string =>
  typeof v === 'number' && Number.isFinite(v) ? v.toFixed(digits) : fallback

/** 百分比格式化：0.85 → "85%" */
export const fmtPct = (v: number | undefined | null, digits = 0, fallback = '--'): string =>
  typeof v === 'number' && Number.isFinite(v) ? `${(v * 100).toFixed(digits)}%` : fallback

/** 金额格式化：1234567 → "1,234,567.00" */
export const fmtMoney = (v: number | undefined | null, digits = 2, fallback = '-'): string =>
  typeof v === 'number' && Number.isFinite(v)
    ? v.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
    : fallback

/** 安全 toFixed：确保数值不为 NaN/Infinity 才格式化 (与fmt等价，保留兼容) */
export const safeFixed = (v: number | undefined | null, digits = 2, fallback = '-'): string => {
  if (typeof v !== 'number' || !Number.isFinite(v)) return fallback
  return v.toFixed(digits)
}
