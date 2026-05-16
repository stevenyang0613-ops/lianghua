import { useState, useEffect } from 'react'
import { Typography } from 'antd'
import {
  AppInfoCard,
  UserManagementCard,
  DisplaySettingsCard,
  NetworkSettingsCard,
  CacheManagementCard,
  PerformanceMonitorCard,
  StartupSettingsCard,
  SignalConfigCard,
  NotificationSettingsCard,
  ErrorLogCard,
  LogViewerCard,
  ShortcutSettingsCard,
} from '../components/settings'

const { Title } = Typography

export default function Settings() {
  // Shared performance metrics state — updated by NetworkSettingsCard, displayed by PerformanceMonitorCard
  const [perfMetrics, setPerfMetrics] = useState(() => {
    const saved = localStorage.getItem('perf_metrics')
    if (saved) {
      return JSON.parse(saved)
    }
    return {
      startupTime: null as number | null,
      avgApiTime: 0,
      cacheHitRate: 0,
      lastSyncTime: null as string | null,
      apiHistory: [] as { time: number; timestamp: number }[],
    }
  })

  // Load perf metrics from localStorage on mount
  useEffect(() => {
    const saved = localStorage.getItem('perf_metrics')
    if (saved) {
      setPerfMetrics(JSON.parse(saved))
    }
  }, [])

  const handleSyncComplete = (syncTime: number) => {
    const history = [...(perfMetrics.apiHistory || []), { time: syncTime, timestamp: Date.now() }].slice(-10)
    const newMetrics = {
      ...perfMetrics,
      lastSyncTime: new Date().toLocaleString('zh-CN'),
      avgApiTime: perfMetrics.avgApiTime > 0 ? (perfMetrics.avgApiTime + syncTime) / 2 : syncTime,
      apiHistory: history,
    }
    setPerfMetrics(newMetrics)
    localStorage.setItem('perf_metrics', JSON.stringify(newMetrics))
  }

  return (
    <div style={{ padding: 16, maxWidth: 800, margin: '0 auto' }}>
      <Title level={4} style={{ marginBottom: 24 }}>系统设置</Title>

      <AppInfoCard />
      <UserManagementCard />
      <DisplaySettingsCard />
      <NetworkSettingsCard onSyncComplete={handleSyncComplete} />
      <CacheManagementCard />
      <PerformanceMonitorCard
        avgApiTime={perfMetrics.avgApiTime}
        lastSyncTime={perfMetrics.lastSyncTime}
        cacheHitRate={perfMetrics.cacheHitRate}
        apiHistory={perfMetrics.apiHistory}
      />
      <StartupSettingsCard />
      <SignalConfigCard />
      <NotificationSettingsCard />
      <ErrorLogCard />
      <LogViewerCard />
      <ShortcutSettingsCard />
    </div>
  )
}
