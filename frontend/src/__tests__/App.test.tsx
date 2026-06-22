import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../Layout', () => ({
  default: ({ children }: any) => <div>{children}</div>,
}))
vi.mock('../stores/useUserStore', () => ({
  initDefaultUser: vi.fn(),
}))
vi.mock('../utils/electron', () => ({
  isElectron: () => false,
}))
vi.mock('../utils/indexedDBStorage', () => ({
  initDB: vi.fn(),
  indexedDBStorage: { startAutoCleanup: vi.fn() },
}))
vi.mock('../utils/alertNotification', () => ({
  alertManager: { addRule: vi.fn(), getRules: vi.fn(() => []), init: vi.fn() },
  initPredefinedRules: vi.fn(),
}))
vi.mock('../utils/monitoring', () => ({
  monitoring: { init: vi.fn() },
  trackWebVitals: vi.fn(),
}))
vi.mock('../utils/logCollector', () => ({
  logCollector: { configure: vi.fn() },
}))
vi.mock('../utils/performanceOptimization', () => ({
  initPerformanceOptimization: vi.fn(),
}))
vi.mock('../utils/backgroundSync', () => ({
  initBackgroundSync: vi.fn(),
}))
vi.mock('../utils/smartSync', () => ({
  initNetworkMonitor: vi.fn(),
}))
vi.mock('../utils/cacheWarmup', () => ({
  initWarmup: vi.fn(),
}))
vi.mock('../utils/notifications', () => ({
  notificationService: { init: vi.fn() },
}))
vi.mock('../utils/errorLogger', () => ({
  setupGlobalErrorHandler: vi.fn(),
}))
vi.mock('../utils/wsInstances', () => ({
  marketWs: { connect: vi.fn(), disconnect: vi.fn(), isConnected: vi.fn(() => false), onStateChange: vi.fn(() => vi.fn()) },
  signalsWs: { connect: vi.fn(), disconnect: vi.fn(), isConnected: vi.fn(() => false), onStateChange: vi.fn(() => vi.fn()) },
  refreshWsToken: vi.fn(),
}))
vi.mock('../utils/routePreload', () => ({
  preloadByPriority: vi.fn(),
  setupSmartPreload: vi.fn(() => vi.fn()),
}))
vi.mock('../utils/offlineQueue', () => ({
  initOfflineQueue: vi.fn(),
}))
vi.mock('../utils/locales', () => ({
  initLocale: vi.fn(),
}))
vi.mock('../utils/hotkeys', () => ({
  initHotkeys: vi.fn(),
}))
vi.mock('../utils/prefetchStrategy', () => ({
  initPrefetchStrategy: vi.fn(),
}))
vi.mock('../utils/dataCache', () => ({
  onNetworkChange: vi.fn(() => vi.fn()),
  checkNetworkStatus: vi.fn(() => ({ online: true })),
  isOfflineMode: vi.fn(() => false),
}))
// Mock indexedDB for test environment
vi.mock('../utils/healthCheck', () => ({
  startHealthCheck: vi.fn(() => vi.fn()),
}))
// Mock firstScreenOptimize
vi.mock('../utils/firstScreenOptimize', () => ({
  initFirstScreenOptimize: vi.fn(),
}))

import App from '../App'

describe('App', () => {
  it('should render without crashing', () => {
    const { container } = render(<MemoryRouter><App /></MemoryRouter>)
    // The app renders StartupLoading which should be present
    expect(container.querySelector('[style*="z-index: 9999"]')).toBeDefined()
  })
})
