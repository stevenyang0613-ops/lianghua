import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface AppState {
  backendConnected: boolean
  setBackendConnected: (v: boolean) => void
  selectedBond: string | null
  setSelectedBond: (code: string | null) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      backendConnected: false,
      setBackendConnected: (v) => set({ backendConnected: v }),
      selectedBond: null,
      setSelectedBond: (code) => set({ selectedBond: code }),
    }),
    {
      name: 'lianghua-app',
    }
  )
)
