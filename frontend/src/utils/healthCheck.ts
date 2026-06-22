import { useAppStore } from '../stores/useAppStore'
import { marketWs, signalsWs } from '../utils/wsInstances'

let _intervalId: ReturnType<typeof setInterval> | null = null
let _lastBackendOnline = false

function checkBackend() {
  const backendConnected = useAppStore.getState().backendConnected
  if (backendConnected && !_lastBackendOnline) {
    _lastBackendOnline = true
    try { marketWs.connect() } catch {}
    try { signalsWs.connect() } catch {}
  } else if (!backendConnected && _lastBackendOnline) {
    _lastBackendOnline = false
    try { marketWs.disconnect() } catch {}
    try { signalsWs.disconnect() } catch {}
  }
  _lastBackendOnline = backendConnected
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