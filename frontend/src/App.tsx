import { useEffect, lazy, Suspense } from 'react'
import { Routes, Route, Navigate } from 'react-router-dom'
import { Spin } from 'antd'
import Layout from './Layout'
import StartupLoading from './components/StartupLoading'
import ErrorBoundary from './components/ErrorBoundary'
import { initDefaultUser } from './stores/useUserStore'
import { useAccountStore } from './stores/useAccountStore'
import { useAppStore } from './stores/useAppStore'
import { initBackgroundSync, cleanupBackgroundSync } from './utils/backgroundSync'
import { initNetworkMonitor, cleanupNetworkMonitor } from './utils/smartSync'
import { initWarmup } from './utils/cacheWarmup'
import { notificationService } from './utils/notifications'
import { setupGlobalErrorHandler } from './utils/errorLogger'
import { marketWs, signalsWs, cancelRefreshWsToken, destroyWsInstances } from './utils/wsInstances'
import { preloadByPriority, setupSmartPreload } from './utils/routePreload'
import { initDB, indexedDBStorage } from './utils/indexedDBStorage'
import { initOfflineQueue } from './utils/offlineQueue'
import { offlineQueue } from './utils/offlineQueue'
import { initLocale } from './locales'
import { initHotkeys } from './utils/hotkeys'
import { initPrefetchStrategy } from './utils/prefetchStrategy'
import { onNetworkChange, checkNetworkStatus, isOfflineMode } from './utils/dataCache'
import { monitoring, trackWebVitals } from './utils/monitoring'
import { initPerformanceOptimization, stopPerformanceOptimization } from './utils/performanceOptimization'
import { logCollector } from './utils/logCollector'
import { alertManager, initPredefinedRules } from './utils/alertNotification'
import { startHealthCheck } from './utils/healthCheck'
import { initWsListeners, cleanupWsListeners } from './stores/useAppStore'
import { initThemeSystem, destroyThemeSystem } from './stores/useThemeStore'
import { prefetchManager } from './utils/prefetchStrategy'
import { useMarketStore } from './stores/useMarketStore'
import { destroyTradeLogger } from './utils/tradeLogger'
import { dataPlayer } from './utils/dataPlayer'
import { destroyPriceAlert } from './utils/priceAlert'
import { destroyScoreStore } from './stores/useScoreStore'
import { destroyXuanjiStore } from './stores/useXuanjiStore'
import { replayEngine } from './utils/strategyReplay'
import { destroyMemoryManager } from './utils/memoryManager'
import { destroyRequestCache } from './utils/requestCache'

const Market = lazy(() => import('./pages/Market'))
const Watchlist = lazy(() => import('./pages/Watchlist'))
const Backtest = lazy(() => import('./pages/Backtest'))
const Trade = lazy(() => import('./pages/Trade'))
const Analysis = lazy(() => import('./pages/Analysis'))
const Signals = lazy(() => import('./pages/Signals'))
const Strategies = lazy(() => import('./pages/Strategies'))
const Settings = lazy(() => import('./pages/Settings'))
const Performance = lazy(() => import('./pages/Performance'))
const TradeLog = lazy(() => import('./pages/TradeLog'))
const StrategyReplay = lazy(() => import('./pages/StrategyReplay'))
const AccountManager = lazy(() => import('./pages/AccountManager'))
const AlertManager = lazy(() => import('./pages/AlertManager'))
const ReportCenter = lazy(() => import('./pages/ReportCenter'))
const RiskControl = lazy(() => import('./pages/RiskControl'))
const AutoTrade = lazy(() => import('./pages/AutoTrade'))
const DataPlayer = lazy(() => import('./pages/DataPlayer'))
const StrategyMarket = lazy(() => import('./pages/StrategyMarket'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const MessageCenter = lazy(() => import('./pages/MessageCenter'))
const ThemeStore = lazy(() => import('./pages/ThemeStore'))
const PluginManager = lazy(() => import('./pages/PluginManager'))
const ScoreRanking = lazy(() => import('./pages/ScoreRanking'))
const SyncSettings = lazy(() => import('./pages/SyncSettings'))
const XibuScore = lazy(() => import('./pages/XibuScore'))
const TimingSignal = lazy(() => import('./pages/TimingSignal'))
const XuanjiIndex = lazy(() => import('./pages/XuanjiIndex'))
const AnalyticsDashboard = lazy(() => import('./pages/AnalyticsDashboard'))
const ThemeConfig = lazy(() => import('./pages/ThemeConfig'))
const DataImportExport = lazy(() => import('./pages/DataImportExport'))
const OpsDashboard = lazy(() => import('./components/OpsDashboard'))
const ExchangeableBonds = lazy(() => import('./pages/ExchangeableBonds'))
const MXData = lazy(() => import('./pages/MXData'))
const SectorRotation = lazy(() => import('./pages/SectorRotation'))
const SectorRotationStock = lazy(() => import('./pages/SectorRotationStock'))
const PaperTrade = lazy(() => import('./pages/PaperTrade'))
const DataSourceMonitor = lazy(() => import('./pages/DataSourceMonitor'))
const EnrichmentDashboard = lazy(() => import('./pages/EnrichmentDashboard'))
const BacktestResults = lazy(() => import('./pages/BacktestResults'))

// 注册 Service Worker (仅在浏览器/PWA 环境下, Electron 不支持 Service Worker)
function registerServiceWorker() {
  if ('serviceWorker' in navigator && !window.navigator.userAgent.includes('Electron')) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js')
        .then((registration) => {
          console.log('[PWA] Service Worker registered:', registration.scope)
        })
        .catch((error) => {
          console.log('[PWA] Service Worker registration failed:', error)
        })
    }, { once: true })
  }
}

import { clearStatusCacheOnStartup } from './utils/dataCache'

export default function App() {
  useEffect(() => {
    // 启动时清除状态类/配置类接口的旧缓存，避免错误状态残留
    clearStatusCacheOnStartup().catch(() => {})

    // 全局 unhandledrejection 守卫：仅在生产环境阻止默认行为，开发环境保留原生错误
    const rejectionGuard = (event: PromiseRejectionEvent) => {
      const stack = event.reason instanceof Error ? event.reason.stack : undefined
      console.warn('[App] Unhandled rejection (isolated):', event.reason, stack || '')
      if (!import.meta.env.DEV) {
        event.preventDefault()
      }
    }
    window.addEventListener('unhandledrejection', rejectionGuard)

    initDefaultUser()
    // 初始化后台数据同步
    initBackgroundSync()
    // 初始化智能网络监控
    initNetworkMonitor()
    // 初始化缓存预热
    const warmupCleanup = initWarmup()
    // 注册 Service Worker
    registerServiceWorker()
    // 初始化通知服务
    notificationService.init()
    // 设置全局错误处理
    const errorHandlerCleanup = setupGlobalErrorHandler()

    // 网络状态监听
    const networkCleanup = onNetworkChange((online) => {
      if (online && useAppStore.getState().backendConnected) {
        console.log('[Network] Online - reconnecting...')
        try { marketWs.connect() } catch { /* isolated */ }
        try { signalsWs.connect() } catch { /* isolated */ }
      } else if (!online) {
        console.log('[Network] Offline - switching to offline mode')
      }
    })

    // 全局 WS 连接管理：等 token 就绪后再连接
    // 先注册 WS 状态监听器，确保 store 状态与 WebSocket 同步
    initWsListeners()

    try {
      const wsToken = localStorage.getItem('ws_auth_token')
      if (wsToken) {
        try { marketWs.connect() } catch { /* isolated */ }
        try { signalsWs.connect() } catch { /* isolated */ }
      }
    } catch { /* localStorage may be unavailable */ }

    // 加载加密的 API Key 到内存（静默失败，不阻塞启动）
    useAccountStore.getState().loadSecureFields().catch(() => { /* secure fields optional */ })
    // 初始化 IndexedDB
    void initDB()
    // 启动 IndexedDB 自动清理
    indexedDBStorage.startAutoCleanup()
    // 初始化离线队列
    void initOfflineQueue()
    // 初始化国际化
    initLocale()
    initThemeSystem()
    // 初始化快捷键
    const hotkeysCleanup = initHotkeys()
    // 初始化预取策略
    initPrefetchStrategy()
    // 初始化监控服务
    monitoring.init({ enabled: !import.meta.env.DEV })
    const webVitalsCleanup = trackWebVitals()
    // 初始化性能优化
    initPerformanceOptimization()
    // 初始化日志收集
    logCollector.configure({
      minLevel: import.meta.env.DEV ? 'debug' : 'info',
      enableRemote: !import.meta.env.DEV,
      remoteEndpoint: '/api/logs',
    })
    // 初始化告警管理
    alertManager.init()
    initPredefinedRules()
    // 启动路由预加载
    const routePreloadCleanup = preloadByPriority()
    // 设置智能预加载（鼠标悬停预加载）
    const preloadCleanup = setupSmartPreload()
    // 启动后端健康检查（后端断开时自动断WS，恢复时自动重连）
    const healthCleanup = startHealthCheck()

      return () => {
        errorHandlerCleanup?.()
        hotkeysCleanup?.()
        networkCleanup?.()
        preloadCleanup?.()
        healthCleanup?.()
        warmupCleanup?.()
        webVitalsCleanup?.()
        routePreloadCleanup?.()
        window.removeEventListener('unhandledrejection', rejectionGuard)
        try { marketWs.disconnect() } catch { /* isolated */ }
        try { signalsWs.disconnect() } catch { /* isolated */ }
        cleanupWsListeners()
        indexedDBStorage.stopAutoCleanup()
        cleanupBackgroundSync()
        cleanupNetworkMonitor()
        cancelRefreshWsToken()
        destroyWsInstances()
        destroyRequestCache()
        monitoring.destroy()
        stopPerformanceOptimization()
        alertManager.destroy()
        notificationService.destroy()
        destroyThemeSystem()
        prefetchManager.destroy()
        offlineQueue.destroy()
        logCollector.destroy()
        destroyPriceAlert?.()
        destroyTradeLogger()
        dataPlayer.destroy()
        destroyScoreStore()
        destroyXuanjiStore()
        replayEngine.destroy()
        destroyMemoryManager()
        useMarketStore.getState().destroy?.()
      }
  }, [])

  return (
    <StartupLoading>
      <ErrorBoundary>
        <Layout>
          <Suspense fallback={<div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}><Spin size="large" /></div>}>
            <Routes>
            <Route path="/" element={<ErrorBoundary><Market /></ErrorBoundary>} />
            <Route path="/market" element={<ErrorBoundary><Market /></ErrorBoundary>} />
            <Route path="/exchangeable" element={<ErrorBoundary><ExchangeableBonds /></ErrorBoundary>} />
            <Route path="/mx-data" element={<ErrorBoundary><MXData /></ErrorBoundary>} />
            <Route path="/sector-rotation" element={<ErrorBoundary><SectorRotation /></ErrorBoundary>} />
            <Route path="/sector-rotation-stock" element={<ErrorBoundary><SectorRotationStock /></ErrorBoundary>} />
            <Route path="/watchlist" element={<ErrorBoundary><Watchlist /></ErrorBoundary>} />
            <Route path="/backtest" element={<ErrorBoundary><Backtest /></ErrorBoundary>} />
            <Route path="/trade" element={<ErrorBoundary><Trade /></ErrorBoundary>} />
            <Route path="/analysis" element={<ErrorBoundary><Analysis /></ErrorBoundary>} />
            <Route path="/signals" element={<ErrorBoundary><Signals /></ErrorBoundary>} />
            <Route path="/strategies" element={<ErrorBoundary><Strategies /></ErrorBoundary>} />
            <Route path="/settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
            <Route path="/performance" element={<ErrorBoundary><Performance /></ErrorBoundary>} />
            <Route path="/trade-log" element={<ErrorBoundary><TradeLog /></ErrorBoundary>} />
            <Route path="/strategy-replay" element={<ErrorBoundary><StrategyReplay /></ErrorBoundary>} />
            <Route path="/accounts" element={<ErrorBoundary><AccountManager /></ErrorBoundary>} />
            <Route path="/alerts" element={<ErrorBoundary><AlertManager /></ErrorBoundary>} />
            <Route path="/reports" element={<ErrorBoundary><ReportCenter /></ErrorBoundary>} />
            <Route path="/risk" element={<ErrorBoundary><RiskControl /></ErrorBoundary>} />
            <Route path="/auto-trade" element={<ErrorBoundary><AutoTrade /></ErrorBoundary>} />
            <Route path="/paper-trade" element={<ErrorBoundary><PaperTrade /></ErrorBoundary>} />
            <Route path="/backtest-results" element={<ErrorBoundary><BacktestResults /></ErrorBoundary>} />
            <Route path="/data-player" element={<ErrorBoundary><DataPlayer /></ErrorBoundary>} />
            <Route path="/strategy-market" element={<ErrorBoundary><StrategyMarket /></ErrorBoundary>} />
            <Route path="/dashboard" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
            <Route path="/messages" element={<ErrorBoundary><MessageCenter /></ErrorBoundary>} />
            <Route path="/themes" element={<ErrorBoundary><ThemeStore /></ErrorBoundary>} />
            <Route path="/plugins" element={<ErrorBoundary><PluginManager /></ErrorBoundary>} />
            <Route path="/score-ranking" element={<ErrorBoundary><ScoreRanking /></ErrorBoundary>} />
            <Route path="/xibu-score" element={<ErrorBoundary><XibuScore /></ErrorBoundary>} />
            <Route path="/timing-signal" element={<ErrorBoundary><TimingSignal /></ErrorBoundary>} />
            <Route path="/xuanji-index" element={<ErrorBoundary><XuanjiIndex /></ErrorBoundary>} />
            <Route path="/sync" element={<ErrorBoundary><SyncSettings /></ErrorBoundary>} />
            <Route path="/analytics" element={<ErrorBoundary><AnalyticsDashboard /></ErrorBoundary>} />
            <Route path="/theme-config" element={<ErrorBoundary><ThemeConfig /></ErrorBoundary>} />
            <Route path="/data-import-export" element={<ErrorBoundary><DataImportExport /></ErrorBoundary>} />
            <Route path="/ops" element={<ErrorBoundary><OpsDashboard /></ErrorBoundary>} />
            <Route path="/data-source-monitor" element={<ErrorBoundary><DataSourceMonitor /></ErrorBoundary>} />
            <Route path="/enrichment-dashboard" element={<ErrorBoundary><EnrichmentDashboard /></ErrorBoundary>} />
            <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </Layout>
      </ErrorBoundary>
    </StartupLoading>
  )
}
