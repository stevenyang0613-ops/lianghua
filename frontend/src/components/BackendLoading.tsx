import { useEffect, useState } from 'react'
import { healthCheck } from '../services/api'
import { useAppStore } from '../stores/useAppStore'

const LOADING_STEPS = [
  '正在连接后端服务...',
  '正在加载市场数据...',
  '正在初始化策略引擎...',
  '正在建立 WebSocket 连接...',
  '准备就绪',
]

interface BackendLoadingProps {
  children: React.ReactNode
}

export default function BackendLoading({ children }: BackendLoadingProps) {
  const backendConnected = useAppStore((s) => s.backendConnected)
  const setBackendConnected = useAppStore((s) => s.setBackendConnected)
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    if (backendConnected) return

    let cancelled = false
    let retries = 0
    const maxRetries = 30

    async function check() {
      while (!cancelled && retries < maxRetries) {
        try {
          setStep(Math.min(1, retries < 3 ? 0 : 1))
          setProgress(Math.min(80, Math.round((retries / maxRetries) * 80)))

          await healthCheck()
          if (cancelled) return

          setStep(4)
          setProgress(100)
          await new Promise((r) => setTimeout(r, 300))
          if (!cancelled) {
            setBackendConnected(true)
          }
          return
        } catch {
          retries++
          await new Promise((r) => setTimeout(r, 1000))
        }
      }

      if (!cancelled) {
        setError('后端服务连接失败，请检查服务是否已启动')
      }
    }

    check()
    return () => { cancelled = true }
  }, [backendConnected, setBackendConnected])

  if (backendConnected) {
    return <>{children}</>
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #1a1a2e 0%, #16213e 100%)',
      color: '#fff',
      zIndex: 9999,
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    }}>
      <div style={{ fontSize: 48, marginBottom: 16 }}>📊</div>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 8 }}>LiangHua</h1>
      <div style={{ color: '#888', fontSize: 12, marginBottom: 32 }}>
        可转债量化交易系统 v1.0.0
      </div>
      <div style={{
        width: 300,
        height: 6,
        background: 'rgba(255,255,255,0.1)',
        borderRadius: 3,
        overflow: 'hidden',
        marginBottom: 16,
      }}>
        <div style={{
          width: `${progress}%`,
          height: '100%',
          background: 'linear-gradient(90deg, #1890ff, #52c41a)',
          borderRadius: 3,
          transition: 'width 0.3s ease',
        }} />
      </div>
      <div style={{ color: error ? '#ff4d4f' : '#aaa', fontSize: 13, textAlign: 'center' }}>
        {error ? (
          <>
            <div>{error}</div>
            <div style={{ marginTop: 16, display: 'flex', gap: 12, justifyContent: 'center' }}>
              <button
                onClick={() => { setError(null); setProgress(0); setStep(0); setBackendConnected(false) }}
                style={{
                  padding: '8px 24px',
                  background: '#1890ff',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: 14,
                }}
              >
                重试
              </button>
              <button
                onClick={() => {
                  try { localStorage.setItem('offline_mode', 'true') } catch { /* silent fail */ }
                  setBackendConnected(true)
                }}
                style={{
                  padding: '8px 24px',
                  background: 'transparent',
                  color: '#aaa',
                  border: '1px solid #555',
                  borderRadius: 4,
                  cursor: 'pointer',
                  fontSize: 14,
                }}
              >
                离线模式
              </button>
            </div>
          </>
        ) : (
          <>
            <span style={{
              display: 'inline-block',
              width: 16,
              height: 16,
              border: '2px solid rgba(255,255,255,0.3)',
              borderRadius: '50%',
              borderTopColor: '#1890ff',
              animation: 'lh-spin 1s linear infinite',
              marginRight: 8,
              verticalAlign: 'middle',
            }} />
            <style>{`@keyframes lh-spin { to { transform: rotate(360deg); } }`}</style>
            {LOADING_STEPS[step]}
          </>
        )}
      </div>
    </div>
  )
}
