import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { marketWs, signalsWs } from '../utils/wsInstances'

interface AppState {
  backendConnected: boolean
  setBackendConnected: (v: boolean) => void
  selectedBond: string | null
  setSelectedBond: (code: string | null) => void
  marketWsConnected: boolean
  signalWsConnected: boolean
}

// Store创建时立即注册WS状态监听，确保任何组件首次读取时状态已是最新
// 使用 queueMicrotask 避免同步 setState 导致 React #300 错误
const _unsub1 = marketWs.onStateChange((state) => {
  queueMicrotask(() => {
    try { useAppStore.setState({ marketWsConnected: state === 'connected' }) } catch { /* isolated */ }
  })
})
const _unsub2 = signalsWs.onStateChange((state) => {
  queueMicrotask(() => {
    try { useAppStore.setState({ signalWsConnected: state === 'connected' }) } catch { /* isolated */ }
  })
})

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      backendConnected: false,
      setBackendConnected: (v) => set({ backendConnected: v }),
      selectedBond: null,
      setSelectedBond: (code) => set({ selectedBond: code }),
      marketWsConnected: marketWs.isConnected(),
      signalWsConnected: signalsWs.isConnected(),
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
