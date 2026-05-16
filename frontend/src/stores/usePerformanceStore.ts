/**
 * 性能监控设置 Store
 */

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface PerformanceSettings {
  enabled: boolean
  showFps: boolean
  showMemory: boolean
  showNetwork: boolean
  showCache: boolean
  fpsWarningThreshold: number
  memoryWarningThreshold: number
}

interface PerformanceStore extends PerformanceSettings {
  setEnabled: (enabled: boolean) => void
  setShowFps: (show: boolean) => void
  setShowMemory: (show: boolean) => void
  setShowNetwork: (show: boolean) => void
  setShowCache: (show: boolean) => void
  setFpsWarningThreshold: (threshold: number) => void
  setMemoryWarningThreshold: (threshold: number) => void
  reset: () => void
}

const defaultSettings: PerformanceSettings = {
  enabled: true,
  showFps: true,
  showMemory: true,
  showNetwork: true,
  showCache: false,
  fpsWarningThreshold: 30,
  memoryWarningThreshold: 70,
}

export const usePerformanceStore = create<PerformanceStore>()(
  persist(
    (set) => ({
      ...defaultSettings,
      setEnabled: (enabled) => set({ enabled }),
      setShowFps: (showFps) => set({ showFps }),
      setShowMemory: (showMemory) => set({ showMemory }),
      setShowNetwork: (showNetwork) => set({ showNetwork }),
      setShowCache: (showCache) => set({ showCache }),
      setFpsWarningThreshold: (fpsWarningThreshold) => set({ fpsWarningThreshold }),
      setMemoryWarningThreshold: (memoryWarningThreshold) => set({ memoryWarningThreshold }),
      reset: () => set(defaultSettings),
    }),
    {
      name: 'lianghua-performance-settings',
    }
  )
)
