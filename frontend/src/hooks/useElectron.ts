import { useEffect, useCallback } from 'react'
import { message } from 'antd'
import { useNavigate } from 'react-router-dom'
import type { ElectronAPI } from '../types/electron'

export function useElectron() {
  const navigate = useNavigate()
  const api: ElectronAPI | undefined = window.electronAPI

  const isElectron = api?.isElectron === true

  const showNotification = useCallback(async (title: string, body: string) => {
    if (api?.showNotification) {
      await api.showNotification(title, body)
    } else if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, { body })
    }
  }, [api])

  const getAppInfo = useCallback(async () => {
    if (api?.getAppInfo) {
      return await api.getAppInfo()
    }
    return null
  }, [api])

  const restartBackend = useCallback(async () => {
    if (api?.restartBackend) {
      await api.restartBackend()
      message.success('后端服务重启中...')
    } else {
      message.error('此功能仅在桌面端可用')
    }
  }, [api])

  const openExternal = useCallback((url: string) => {
    if (api?.openExternal) {
      api.openExternal(url)
    } else {
      window.open(url, '_blank')
    }
  }, [api])

  // 监听 Electron 菜单事件
  useEffect(() => {
    if (!api) return

    const unsubNav = api.onNavigate?.((route: string) => navigate(route))
    const unsubRefresh = api.onRefreshData?.(() => {
      message.success('正在刷新数据...')
      window.dispatchEvent(new CustomEvent('refresh-market-data'))
    })
    const unsubExport = api.onExportReport?.(() => {
      message.info('导出报告功能开发中...')
    })

    return () => {
      unsubNav?.()
      unsubRefresh?.()
      unsubExport?.()
    }
  }, [api, navigate])

  return {
    isElectron,
    platform: api?.platform,
    versions: api?.versions,
    showNotification,
    getAppInfo,
    restartBackend,
    openExternal,
  }
}

export default useElectron
