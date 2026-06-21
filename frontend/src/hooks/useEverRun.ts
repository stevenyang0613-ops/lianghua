import { useState, useEffect, useRef } from 'react'

/**
 * useEverRun — 首次触发后永久标记的 hook
 *
 * 适用场景：新手引导、首次配置向导、首次数据导入等，
 * 只要在当前 session 或跨 session 中满足过条件，就不再展示引导。
 *
 * 优先级：
 * 1. 后端驱动条件（如 account.created_at / is_running）— 跨设备同步
 * 2. localStorage 缓存 — 后端还没返回数据时的辅助标记
 *
 * @param storageKey localStorage 持久化 key（建议包含业务标识，如策略 ID）
 * @param conditions 触发条件数组，任一为 true 即标记为"已运行"
 *   ⚠️ 传入值会被 Boolean() 强制转换，避免 [1] vs [true] 序列化不一致
 *
 * @example
 * ```tsx
 * const hasEverRun = useEverRun(
 *   `lianghua_paper_trade_ever_run_${strategyId}`,
 *   [!!account?.created_at, account.is_running]
 * )
 * ```
 */
export function useEverRun(storageKey: string, conditions: boolean[]): boolean {
  const [hasEverRun, setHasEverRun] = useState(() => {
    // 辅助缓存：后端还没返回数据时，先从 localStorage 读取
    try {
      return localStorage.getItem(storageKey) === 'true'
    } catch {
      return false
    }
  })

  // 用 useRef 缓存序列化值，避免 useMemo 依赖项中执行副作用（.map + .join）
  // 仅在序列化值变化时更新 ref，不依赖数组引用
  // ⚠️ StrictMode safety：分离 ref 更新和值计算，避免 double-invoke 导致 ref 写入顺序不确定
  const prevSerializedRef = useRef('')
  const boolConditions = conditions.map(Boolean)
  const serialized = boolConditions.join()
  if (serialized !== prevSerializedRef.current) {
    prevSerializedRef.current = serialized
  }
  const conditionsMet = boolConditions.some(Boolean)

  // 任意条件为 true 且当前未标记 → 标记并持久化
  useEffect(() => {
    if (conditionsMet && !hasEverRun) {
      setHasEverRun(true)
      try {
        localStorage.setItem(storageKey, 'true')
      } catch { /* ignore quota / privacy mode errors */ }
    }
  }, [conditionsMet, hasEverRun, storageKey])

  return hasEverRun
}
