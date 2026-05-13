import { create } from 'zustand'

interface AppState {
  backendConnected: boolean
  setBackendConnected: (v: boolean) => void
  selectedBond: string | null
  setSelectedBond: (code: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  backendConnected: false,
  setBackendConnected: (v) => set({ backendConnected: v }),
  selectedBond: null,
  setSelectedBond: (code) => set({ selectedBond: code }),
}))
