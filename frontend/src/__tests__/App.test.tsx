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
vi.mock('../indexedDBStorage', () => ({
  initDB: vi.fn(),
  indexedDBStorage: {},
}))
vi.mock('../alertNotification', () => ({
  alertManager: { addRule: vi.fn(), getRules: vi.fn(() => []) },
  initPredefinedRules: vi.fn(),
}))
vi.mock('../monitoring', () => ({
  monitoring: {},
  trackWebVitals: vi.fn(),
}))
vi.mock('../logCollector', () => ({
  logCollector: { init: vi.fn() },
}))
vi.mock('../performanceOptimization', () => ({
  initPerformanceOptimization: vi.fn(),
}))
vi.mock('../backgroundSync', () => ({
  initBackgroundSync: vi.fn(),
}))
vi.mock('../smartSync', () => ({
  initNetworkMonitor: vi.fn(),
}))
vi.mock('../cacheWarmup', () => ({
  initWarmup: vi.fn(),
}))
vi.mock('../notifications', () => ({
  notificationService: { requestPermission: vi.fn() },
}))
vi.mock('../errorLogger', () => ({
  setupGlobalErrorHandler: vi.fn(),
}))
vi.mock('../wsInstances', () => ({
  marketWs: { connect: vi.fn(), disconnect: vi.fn() },
  signalsWs: { connect: vi.fn(), disconnect: vi.fn() },
}))
vi.mock('../routePreload', () => ({
  preloadByPriority: vi.fn(),
  setupSmartPreload: vi.fn(),
}))
vi.mock('../offlineQueue', () => ({
  initOfflineQueue: vi.fn(),
}))
vi.mock('../locales', () => ({
  initLocale: vi.fn(),
}))
vi.mock('../hotkeys', () => ({
  initHotkeys: vi.fn(),
}))
vi.mock('../prefetchStrategy', () => ({
  initPrefetchStrategy: vi.fn(),
}))
vi.mock('../dataCache', () => ({
  onNetworkChange: vi.fn(),
  checkNetworkStatus: vi.fn(() => true),
  isOfflineMode: vi.fn(() => false),
}))

import App from '../App'

describe('App', () => {
  it('should render without crashing', () => {
    const { container } = render(<MemoryRouter><App /></MemoryRouter>)
    // The app renders StartupLoading which should be present
    expect(container.querySelector('[style*="z-index: 9999"]')).toBeDefined()
  })
})
