import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// Must mock before any imports that use it
const mockNavigate = vi.fn()
vi.mock('react-router-dom', () => ({
  useNavigate: () => mockNavigate,
}))

import { useElectron } from '../useElectron'

const mockElectronAPI = {
  isElectron: true,
  platform: 'darwin',
  versions: { electron: '42.0.0', node: '22.0.0', chrome: '130.0.0' },
  showNotification: vi.fn(),
  getAppInfo: vi.fn(),
  restartBackend: vi.fn(),
  openExternal: vi.fn(),
  minimizeWindow: vi.fn(),
  maximizeWindow: vi.fn(),
  closeWindow: vi.fn(),
  isMaximized: vi.fn(),
  onNavigate: vi.fn(() => vi.fn()),
  onRefreshData: vi.fn(() => vi.fn()),
  onExportReport: vi.fn(() => vi.fn()),
  onWindowFocus: vi.fn(() => vi.fn()),
}

describe('useElectron', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should detect non-electron environment', () => {
    ;(window as any).electronAPI = undefined
    const { result } = renderHook(() => useElectron())
    expect(result.current.isElectron).toBe(false)
  })

  it('should detect electron environment', () => {
    window.electronAPI = mockElectronAPI as any
    const { result } = renderHook(() => useElectron())
    expect(result.current.isElectron).toBe(true)
    expect(result.current.platform).toBe('darwin')
    expect(result.current.versions).toBeDefined()
  })

  it('should call showNotification', async () => {
    window.electronAPI = mockElectronAPI as any
    const { result } = renderHook(() => useElectron())

    await act(async () => {
      await result.current.showNotification('title', 'body')
    })

    expect(mockElectronAPI.showNotification).toHaveBeenCalledWith('title', 'body')
  })

  it('should call restartBackend', async () => {
    window.electronAPI = mockElectronAPI as any
    const { result } = renderHook(() => useElectron())

    await act(async () => {
      await result.current.restartBackend()
    })

    expect(mockElectronAPI.restartBackend).toHaveBeenCalled()
  })

  it('should call openExternal', () => {
    window.electronAPI = mockElectronAPI as any
    const { result } = renderHook(() => useElectron())

    act(() => {
      result.current.openExternal('https://example.com')
    })

    expect(mockElectronAPI.openExternal).toHaveBeenCalledWith('https://example.com')
  })

  it('should register IPC listeners on mount', () => {
    window.electronAPI = mockElectronAPI as any
    renderHook(() => useElectron())

    expect(mockElectronAPI.onNavigate).toHaveBeenCalledTimes(1)
    expect(mockElectronAPI.onRefreshData).toHaveBeenCalledTimes(1)
    expect(mockElectronAPI.onExportReport).toHaveBeenCalledTimes(1)
  })

  it('should clean up IPC listeners on unmount', () => {
    window.electronAPI = mockElectronAPI as any
    const unsubscribeNav = vi.fn()
    const unsubscribeRefresh = vi.fn()
    const unsubscribeExport = vi.fn()

    mockElectronAPI.onNavigate.mockReturnValue(unsubscribeNav)
    mockElectronAPI.onRefreshData.mockReturnValue(unsubscribeRefresh)
    mockElectronAPI.onExportReport.mockReturnValue(unsubscribeExport)

    const { unmount } = renderHook(() => useElectron())
    unmount()

    expect(unsubscribeNav).toHaveBeenCalled()
    expect(unsubscribeRefresh).toHaveBeenCalled()
    expect(unsubscribeExport).toHaveBeenCalled()
  })

  it('should not register IPC listeners when not in electron', () => {
    window.electronAPI = undefined
    renderHook(() => useElectron())

    expect(mockElectronAPI.onNavigate).not.toHaveBeenCalled()
  })
})
