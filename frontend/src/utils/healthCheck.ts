import { useAppStore } from '../stores/useAppStore'
import { marketWs, signalsWs } from '../utils/wsInstances'

let _intervalId: ReturnType<typeof setInterval> | null = null
let _lastBackendOnline = false

function checkBackend() {
  const backendConnected = useAppStore.getState().backendConnected
  if (backendConnected && !_lastBackendOnline) {
    _lastBackendOnline = true
    if (marketWs.getState() !== 'connecting') try { marketWs.connect() } catch {}
    if (signalsWs.getState() !== 'connecting') try { signalsWs.connect() } catch {}
  } else if (!backendConnected && _lastBackendOnline) {
    _lastBackendOnline = false
    try { marketWs.disconnect() } catch {}
    try { signalsWs.disconnect() } catch {}
  } else if (backendConnected && _lastBackendOnline) {
    // 后端持续在线：若 WebSocket 未连接，主动补连
    if (!marketWs.isConnected() && marketWs.getState() !== 'connecting') try { marketWs.connect() } catch {}
    if (!signalsWs.isConnected() && signalsWs.getState() !== 'connecting') try { signalsWs.connect() } catch {}
  }
}

export function stopHealthCheck() {
  if (_intervalId) {
    clearInterval(_intervalId)
    _intervalId = null
  }
  _lastBackendOnline = false
}

export function startHealthCheck() {
  if (_intervalId) return () => clearInterval(_intervalId!)
  _lastBackendOnline = useAppStore.getState().backendConnected
  _intervalId = setInterval(checkBackend, 3000)
  return () => {
    if (_intervalId) {
      clearInterval(_intervalId)
      _intervalId = null
    }
  }
}