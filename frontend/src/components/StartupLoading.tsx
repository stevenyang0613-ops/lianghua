/**
 * 启动加载动画组件
 * 支持进度动画、离线模式检测、版本更新检查
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { healthCheck } from '../services/api'
import { refreshWsToken } from '../utils/wsInstances'
import { getApiBase, setWsAuthToken, setBackendPort, setBrowserBackendUrl, probeDirectBackend } from '../utils/config'
import { useAppStore } from '../stores/useAppStore'
import {
  enableOfflineMode,
  disableOfflineMode,
  isOfflineMode,
  checkNetworkStatus,
  onNetworkChange,
} from '../utils/dataCache'

const LOADING_STEPS = [
  { text: '正在初始化应用...', icon: '🚀' },
  { text: '正在连接后端服务...', icon: '🔌' },
  { text: '正在加载市场数据...', icon: '📊' },
  { text: '正在初始化策略引擎...', icon: '⚙️' },
  { text: '正在建立 WebSocket 连接...', icon: '🔗' },
  { text: '准备就绪', icon: '✅' },
]

interface StartupLoadingProps {
  children: React.ReactNode
}

// 版本更新检查
async function checkForUpdates(): Promise<{ hasUpdate: boolean; version?: string }> {
  try {
    // Electron 环境
    if (window.electronAPI?.checkForUpdates) {
      const result = await window.electronAPI.checkForUpdates()
      return { hasUpdate: result.available, version: result.version }
    }

    // Web 环境 - 检查 service worker 更新
    if ('serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.getRegistration()
      if (registration) {
        await registration.update()
      }
    }

    return { hasUpdate: false }
  } catch {
    return { hasUpdate: false }
  }
}

export default function StartupLoading({ children }: StartupLoadingProps) {
  const backendConnected = useAppStore((s) => s.backendConnected)
  const setBackendConnected = useAppStore((s) => s.setBackendConnected)
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [progress, setProgress] = useState(0)
  const [showOfflineHint, setShowOfflineHint] = useState(false)
  const [updateInfo, setUpdateInfo] = useState<{ hasUpdate: boolean; version?: string } | null>(null)
  // isMounted ref：防止组件卸载后异步回调 setState 触发 React warning
  const isMountedRef = useRef(true)

  // Electron 环境下启动时清除离线模式残留
  useEffect(() => {
    isMountedRef.current = true
    if (window.electronAPI) {
      localStorage.removeItem('offline_mode')
    }
    return () => { isMountedRef.current = false }
  }, [])

  // 检查离线模式
  useEffect(() => {
    const offline = isOfflineMode()
    const network = checkNetworkStatus()

    if (!network.online && !offline) {
      setShowOfflineHint(true)
    }

    // 监听网络变化
    const cleanup = onNetworkChange((online) => {
      if (online) {
        setShowOfflineHint(false)
        disableOfflineMode()
      } else {
        setShowOfflineHint(true)
      }
    })

    return cleanup
  }, [])

  // 监听主进程的后端就绪事件
  useEffect(() => {
    if (backendConnected) return

    const cleanup = window.electronAPI?.onBackendReady?.((data: any) => {
      if (!isMountedRef.current) return // 组件已卸载，忽略异步回调
      const port = typeof data === 'object' ? data.port : data
      const token = typeof data === 'object' ? data.ws_auth_token : undefined
      console.log('[StartupLoading] Received backend-ready event, port:', port, 'hasToken:', !!token)
      setBackendPort(port)
      if (token) {
        setWsAuthToken(token)
        refreshWsToken()
      }
      setBackendConnected(true)
    })

    return () => { cleanup?.() }
  }, [backendConnected, setBackendConnected])

  // 版本更新检查
  useEffect(() => {
    if (backendConnected) {
      checkForUpdates().then(info => {
        if (isMountedRef.current) setUpdateInfo(info)
      })
    }
  }, [backendConnected])

  const handleRetry = useCallback(() => {
    setError(null)
    setProgress(0)
    setStep(0)
    // Don't flip backendConnected — it will re-trigger the useEffect and retry naturally
  }, [])

  const handleOfflineMode = useCallback(() => {
    enableOfflineMode()
    setBackendConnected(true)
  }, [setBackendConnected])

  useEffect(() => {
    if (backendConnected) return

    let cancelled = false
    let retries = 0
    const maxRetries = 120
    // stepInterval 引用：在清理时统一停止
    let stepInterval: ReturnType<typeof setInterval> | null = null
    // AbortController 用于取消 probeDirectBackend 请求
    const probeAbortController = new AbortController()
    // 指数退避：Electron 环境后端启动需 6-10 分钟，逐步拉长重试间隔
    // 浏览器：5s → 10s → 20s → 20s...  Electron IPC：1s → 2s → 4s → 4s...
    // MAX_BACKOFF_EXPONENT: 退避指数上限，retries 超过此值后不再翻倍
    const MAX_BACKOFF_EXPONENT = 3
    // probe 刚超时标志：后端 5s 内未响应但可能正在启动，缩短下次重试间隔
    // 注意：此标志仅影响浏览器环境（probeDirectBackend 在 Electron 中返回 false，
    // 不会设置此标志）。Electron 环境走 IPC 通道，不受 probe 超时影响。
    let probeJustTimedOut = false
    function getRetryDelay(): number {
      const isElectron = !!window.electronAPI?.httpRequest
      const base = isElectron ? 1000 : 5000
      const max = isElectron ? 4000 : 20000
      // 如果 probe 刚超时，缩短间隔为 base 的 60%（后端可能即将就绪）
      if (probeJustTimedOut) {
        probeJustTimedOut = false
        return Math.round(base * 0.6)
      }
      const delay = base * Math.pow(2, Math.min(retries, MAX_BACKOFF_EXPONENT))
      return Math.min(delay, max)
    }

    async function check() {
      // 仅在 Electron 环境中等待 window.electronAPI 注入
      // 非 Electron 环境（浏览器开发模式）跳过，避免浪费 5 秒
      if (typeof window !== 'undefined' && !window.electronAPI) {
        for (let i = 0; i < 50; i++) {
          if (window.electronAPI) break
          await new Promise((r) => setTimeout(r, 100))
          if (cancelled) return
        }
      }
      if (cancelled) return

      // 步骤动画
      stepInterval = setInterval(() => {
        if (!cancelled && step < LOADING_STEPS.length - 1) {
          setStep((s) => Math.min(s + 0.5, LOADING_STEPS.length - 1))
        }
      }, 800)

      while (!cancelled && retries < maxRetries) {
        try {
          if (cancelled) return
          setProgress(Math.min(80, Math.round((retries / maxRetries) * 80)))

          // 在 Electron 环境中直接使用 IPC 检测后端，跳过 withRetry 延迟
          if (window.electronAPI?.httpRequest) {
            const result = await window.electronAPI.httpRequest('GET', getApiBase() + '/health')
            if (cancelled) return
            if (result.ok) {
              disableOfflineMode()
              const token = result.data?.ws_auth_token
                || (window.electronAPI?.getWsToken ? await window.electronAPI.getWsToken() : undefined)
              if (token) {
                setWsAuthToken(token)
                // token 更新后，刷新 WebSocket URL 确保使用最新 token
                refreshWsToken()
              }
              clearInterval(stepInterval)
              setStep(LOADING_STEPS.length - 1)
              setProgress(100)
              await new Promise((r) => setTimeout(r, 500))
              if (!cancelled) {
                setBackendConnected(true)
              }
              return
            }
            // 后端未就绪，使用退避间隔重试
            retries++
            await new Promise((r) => setTimeout(r, getRetryDelay()))
            continue
          }

          const healthResult = await healthCheck()
          if (cancelled) return

          disableOfflineMode()

          if (healthResult.ws_auth_token) {
            setWsAuthToken(healthResult.ws_auth_token)
            // token 更新后，刷新 WebSocket URL 确保使用最新 token
            refreshWsToken()
          }

          clearInterval(stepInterval)
          setStep(LOADING_STEPS.length - 1)
          setProgress(100)

          await new Promise((r) => setTimeout(r, 500))
          if (!cancelled) {
            setBackendConnected(true)
          }
          return
        } catch {
          retries++
          // 浏览器环境降级：Vite 代理失败时，尝试探测后端直连地址
          if (!window.electronAPI?.httpRequest && retries === 3) {
            console.log('[StartupLoading] Vite proxy failed, probing direct backend...')
            try {
              const probed = await probeDirectBackend(probeAbortController.signal)
              if (probed) {
                // 探测成功，重新走 healthCheck（此时 getApiBase 已更新）
                const healthResult = await healthCheck()
                if (cancelled) return
                disableOfflineMode()
                if (healthResult.ws_auth_token) {
                  setWsAuthToken(healthResult.ws_auth_token)
                  refreshWsToken()
                }
                clearInterval(stepInterval)
                setStep(LOADING_STEPS.length - 1)
                setProgress(100)
                await new Promise((r) => setTimeout(r, 500))
                if (!cancelled) {
                  setBackendConnected(true)
                }
                return
	              }
	              // probe 返回 false（超时或后端不可达），缩短下次重试间隔
	              probeJustTimedOut = true
	            } catch {
	              // 探测也失败，缩短下次重试间隔
	              probeJustTimedOut = true
            }
          }
          await new Promise((r) => setTimeout(r, getRetryDelay()))
        }
      }

      clearInterval(stepInterval)
      if (!cancelled) {
        setError('后端服务连接失败，请检查服务是否已启动')
      }
    }

    check()
    return () => {
      cancelled = true
      if (stepInterval) clearInterval(stepInterval)
      try {
        probeAbortController?.abort()
      } catch {
        // abort may throw if already consumed; ignore
      }
    }
    // 注意：step 不应在依赖数组中，否则会导致无限循环
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [backendConnected, setBackendConnected])

  if (backendConnected) {
    return (
      <>
        {children}
        {/* 版本更新提示 */}
        {updateInfo?.hasUpdate && (
          <div
            style={{
              position: 'fixed',
              bottom: 20,
              right: 20,
              background: 'linear-gradient(135deg, #1890ff 0%, #52c41a 100%)',
              color: '#fff',
              padding: '12px 20px',
              borderRadius: 8,
              boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
              zIndex: 10000,
              display: 'flex',
              alignItems: 'center',
              gap: 12,
            }}
          >
            <span>🎉 发现新版本 {updateInfo.version}</span>
            <button
              onClick={() => window.electronAPI?.restartBackend?.()}
              style={{
                background: '#fff',
                color: '#1890ff',
                border: 'none',
                padding: '6px 16px',
                borderRadius: 4,
                cursor: 'pointer',
                fontWeight: 600,
              }}
            >
              立即更新
            </button>
          </div>
        )}
      </>
    )
  }

  const currentStepIndex = Math.floor(step)
  const stepProgress = (step % 1) * 100

  return (
    <div style={styles.container}>
      {/* 动态背景 */}
      <div style={styles.backgroundAnimation}>
        <div style={styles.orb1} />
        <div style={styles.orb2} />
        <div style={styles.orb3} />
      </div>

      {/* Logo 区域 */}
      <div style={styles.logoContainer}>
        <div style={styles.logoIcon}>
          <span style={styles.logoEmoji}>📊</span>
          <div style={styles.logoRing} />
        </div>
        <h1 style={styles.title}>LiangHua</h1>
        <div style={styles.version}>可转债量化交易系统 v1.0.0</div>
      </div>

      {/* 进度条 */}
      <div style={styles.progressContainer}>
        <div style={styles.progressBar}>
          <div
            style={{
              ...styles.progressFill,
              width: `${progress}%`,
            }}
          />
        </div>
        <div style={styles.progressText}>{Math.round(progress)}%</div>
      </div>

      {/* 步骤指示器 */}
      <div style={styles.stepsContainer}>
        {LOADING_STEPS.map((s, i) => (
          <div
            key={i}
            style={{
              ...styles.stepItem,
              opacity: i <= currentStepIndex ? 1 : 0.3,
            }}
          >
            <span style={styles.stepIcon}>{s.icon}</span>
            <span style={styles.stepText}>{s.text}</span>
            {i === currentStepIndex && i < LOADING_STEPS.length - 1 && (
              <span style={styles.spinner} />
            )}
          </div>
        ))}
      </div>

      {/* 离线提示 */}
      {showOfflineHint && !error && (
        <div style={styles.offlineHint}>
          <span style={styles.offlineIcon}>📡</span>
          <span>网络不可用，将在离线模式下运行</span>
          <button onClick={handleOfflineMode} style={styles.offlineButton}>
            进入离线模式
          </button>
        </div>
      )}

      {/* 错误状态 */}
      {error && (
        <div style={styles.errorContainer}>
          <div style={styles.errorIcon}>❌</div>
          <div style={styles.errorText}>{error}</div>
          <div style={styles.errorActions}>
            <button onClick={handleRetry} style={styles.retryButton}>
              重试
            </button>
            <button onClick={handleOfflineMode} style={styles.offlineModeButton}>
              离线模式
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    position: 'fixed',
    inset: 0,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 50%, #f093fb 100%)',
    color: '#fff',
    zIndex: 9999,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    overflow: 'hidden',
  },
  backgroundAnimation: {
    position: 'absolute',
    inset: 0,
    overflow: 'hidden',
    pointerEvents: 'none',
  },
  orb1: {
    position: 'absolute',
    width: 400,
    height: 400,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(255,255,255,0.25) 0%, transparent 70%)',
    top: -100,
    right: -100,
    animation: 'float1 8s ease-in-out infinite',
  },
  orb2: {
    position: 'absolute',
    width: 300,
    height: 300,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(255,215,0,0.2) 0%, transparent 70%)',
    bottom: -50,
    left: -50,
    animation: 'float2 10s ease-in-out infinite',
  },
  orb3: {
    position: 'absolute',
    width: 200,
    height: 200,
    borderRadius: '50%',
    background: 'radial-gradient(circle, rgba(255,255,255,0.15) 0%, transparent 70%)',
    top: '50%',
    left: '50%',
    transform: 'translate(-50%, -50%)',
    animation: 'float3 6s ease-in-out infinite',
  },
  logoContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    marginBottom: 40,
    zIndex: 1,
  },
  logoIcon: {
    position: 'relative',
    width: 80,
    height: 80,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 16,
  },
  logoEmoji: {
    fontSize: 48,
    filter: 'drop-shadow(0 4px 12px rgba(24,144,255,0.4))',
  },
  logoRing: {
    position: 'absolute',
    inset: 0,
    border: '2px solid rgba(255,255,255,0.4)',
    borderRadius: '50%',
    animation: 'pulse 2s ease-in-out infinite',
  },
  title: {
    fontSize: 32,
    fontWeight: 700,
    margin: 0,
    color: '#fff',
    letterSpacing: 2,
    textShadow: '0 2px 8px rgba(0,0,0,0.2)',
  },
  version: {
    color: 'rgba(255,255,255,0.8)',
    fontSize: 14,
    marginTop: 8,
  },
  progressContainer: {
    width: 320,
    marginBottom: 32,
    zIndex: 1,
  },
  progressBar: {
    width: '100%',
    height: 4,
    background: 'rgba(255,255,255,0.3)',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    background: 'linear-gradient(90deg, #fff, #ffd700)',
    borderRadius: 2,
    transition: 'width 0.3s ease',
    boxShadow: '0 0 12px rgba(255,255,255,0.6)',
  },
  progressText: {
    textAlign: 'center',
    marginTop: 8,
    fontSize: 12,
    color: 'rgba(255,255,255,0.9)',
  },
  stepsContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    zIndex: 1,
  },
  stepItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 13,
    color: 'rgba(255,255,255,0.7)',
    transition: 'opacity 0.3s, color 0.3s',
  },
  stepIcon: {
    fontSize: 14,
  },
  stepText: {
    minWidth: 180,
  },
  spinner: {
    width: 12,
    height: 12,
    border: '2px solid rgba(255,255,255,0.2)',
    borderTopColor: '#1890ff',
    borderRadius: '50%',
    animation: 'spin 1s linear infinite',
  },
  offlineHint: {
    position: 'absolute',
    bottom: 40,
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '12px 20px',
    background: 'rgba(255,255,255,0.15)',
    border: '1px solid rgba(255,255,255,0.3)',
    borderRadius: 8,
    color: '#fff',
    fontSize: 13,
    zIndex: 1,
  },
  offlineIcon: {
    fontSize: 16,
  },
  offlineButton: {
    background: '#fff',
    color: '#667eea',
    border: 'none',
    padding: '4px 12px',
    borderRadius: 4,
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 600,
    marginLeft: 8,
  },
  errorContainer: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 16,
    zIndex: 1,
  },
  errorIcon: {
    fontSize: 48,
  },
  errorText: {
    color: '#ff4d4f',
    fontSize: 14,
    textAlign: 'center',
  },
  errorActions: {
    display: 'flex',
    gap: 12,
    marginTop: 8,
  },
  retryButton: {
    padding: '10px 28px',
    background: '#1890ff',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 14,
    fontWeight: 500,
    transition: 'all 0.2s',
  },
  offlineModeButton: {
    padding: '10px 28px',
    background: 'transparent',
    color: '#fffc',
    border: '1px solid rgba(255,255,255,0.4)',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 14,
    transition: 'all 0.2s',
  },
}
