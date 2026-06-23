import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { marketWs, signalsWs } from '../utils/wsInstances'

interface DataSourceStatus {
  configured?: boolean
  enabled?: boolean
}

interface AppState {
  backendConnected: boolean
  setBackendConnected: (v: boolean) => void
  selectedBond: string | null
  setSelectedBond: (code: string | null) => void
  marketWsConnected: boolean
  signalWsConnected: boolean
  marketRunning: boolean
  setMarketRunning: (v: boolean) => void
  dataSources: Record<string, DataSourceStatus> | null
  setDataSources: (v: Record<string, DataSourceStatus> | null) => void
}

// 使用模块级标志防止 HMR 热更新时重复注册监听器
let _listenersRegistered = false
let _unsub1: (() => void) | null = null
let _unsub2: (() => void) | null = null

/** 初始化 WS 状态监听器，确保 store 状态与 WebSocket 同步
 * 在 App.tsx 的 useEffect 中调用，避免 StrictMode 下 cleanup 后无法恢复
 */
export function initWsListeners() {
  if (_listenersRegistered) return
  _listenersRegistered = true
  _unsub1 = marketWs.onStateChange((state) => {
    queueMicrotask(() => {
      try { useAppStore.setState({ marketWsConnected: state === 'connected' }) } catch { /* isolated */ }
    })
  })
  _unsub2 = signalsWs.onStateChange((state) => {
    queueMicrotask(() => {
      try { useAppStore.setState({ signalWsConnected: state === 'connected' }) } catch { /* isolated */ }
    })
  })
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      backendConnected: false,
      setBackendConnected: (v) => set({ backendConnected: v }),
      selectedBond: null,
      setSelectedBond: (code) => set({ selectedBond: code }),
      marketWsConnected: marketWs.isConnected(),
      signalWsConnected: signalsWs.isConnected(),
      marketRunning: false,
      setMarketRunning: (v) => set({ marketRunning: v }),
      dataSources: null,
      setDataSources: (v) => set({ dataSources: v }),
    }),
    {
      name: 'lianghua-app',
      version: 1,
      partialize: (state) => ({ selectedBond: state.selectedBond }),
      migrate: (persistedState: unknown, _version: number) => {
        if (persistedState && typeof persistedState === 'object') {
          const s = persistedState as { selectedBond?: unknown }
          // v0 stored a full bond object; v1+ stores just the code string
          if (typeof s.selectedBond === 'string') {
            return { selectedBond: s.selectedBond }
          }
          if (s.selectedBond && typeof s.selectedBond === 'object' && 'code' in (s.selectedBond as object)) {
            return { selectedBond: (s.selectedBond as { code: string }).code }
          }
        }
        return { selectedBond: null }
      },
    }
  )
)

// 导出清理函数供 App 组件在卸载时调用
export function cleanupWsListeners() {
  if (typeof _unsub1 === 'function') _unsub1()
  if (typeof _unsub2 === 'function') _unsub2()
  _unsub1 = null
  _unsub2 = null
  _listenersRegistered = false
}
