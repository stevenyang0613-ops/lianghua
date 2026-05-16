/**
 * Electron API 全局类型声明
 * 统一定义 window.electronAPI 的类型
 */

import type { ElectronAPI as SharedElectronAPI, UpdateStatus as SharedUpdateStatus } from '@shared/types/electron'

export type UpdateStatus = SharedUpdateStatus
export type ElectronAPI = SharedElectronAPI

declare global {
  interface Window {
    electronAPI?: ElectronAPI
  }
}

export {}
