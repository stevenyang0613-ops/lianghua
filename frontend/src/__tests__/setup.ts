/**
 * Jest 测试配置
 */

import '@testing-library/jest-dom'
import { vi, afterEach } from 'vitest'

// Mock localStorage
const localStorageMock = {
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
  clear: vi.fn(),
}
Object.defineProperty(window, 'localStorage', { value: localStorageMock })

// Mock sessionStorage
Object.defineProperty(window, 'sessionStorage', { value: localStorageMock })

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock ResizeObserver
class ResizeObserverMock {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}
Object.defineProperty(window, 'ResizeObserver', { value: ResizeObserverMock })

// Mock IntersectionObserver
class IntersectionObserverMock {
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
  root = null
  rootMargin = ''
  thresholds = []
}
Object.defineProperty(window, 'IntersectionObserver', { value: IntersectionObserverMock })

// Mock performance.memory
Object.defineProperty(performance, 'memory', {
  value: {
    usedJSHeapSize: 10000000,
    totalJSHeapSize: 50000000,
    jsHeapSizeLimit: 100000000,
  },
})

// 清理每个测试后的状态
afterEach(() => {
  vi.clearAllMocks()
})

// Make localStorage actually work for crypto tests
// Override the mock to store/retrieve values
const workingStorage: Record<string, string> = {}
const originalMock = window.localStorage
Object.defineProperty(window, 'localStorage', {
  value: {
    getItem: (key: string) => workingStorage[key] ?? null,
    setItem: (key: string, value: string) => { workingStorage[key] = value; },
    removeItem: (key: string) => { delete workingStorage[key]; },
    clear: () => { Object.keys(workingStorage).forEach(k => delete workingStorage[k]); },
  },
  configurable: true,
})

// Mock WebSocket to prevent connection attempts in test environment
class WebSocketMock {
  url: string
  readyState: number = WebSocketMock.CLOSED
  onopen: ((event: any) => void) | null = null
  onclose: ((event: any) => void) | null = null
  onmessage: ((event: any) => void) | null = null
  onerror: ((event: any) => void) | null = null
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  constructor(url: string) {
    this.url = url
    // Simulate immediate close to prevent reconnection loops
    setTimeout(() => {
      this.readyState = WebSocketMock.CLOSED
      if (this.onclose) this.onclose({ code: 1000, reason: 'mock close' })
    }, 0)
  }
  send(data: any) {}
  close() { this.readyState = WebSocketMock.CLOSED }
  addEventListener() {}
  removeEventListener() {}
  dispatchEvent() { return true }
}

Object.defineProperty(window, 'WebSocket', { value: WebSocketMock, configurable: true })
