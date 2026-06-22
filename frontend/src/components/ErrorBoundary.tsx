/**
 * React 错误边界组件
 * 全局错误捕获和用户友好提示
 * 支持错误上报、重试机制、降级 UI
 * 页面级隔离：一个页面崩溃不会影响其他页面
 */

import { Component, type ReactNode, type ErrorInfo } from 'react'
import { Result, Button, Typography, Collapse, Space, Statistic, Alert } from 'antd'
import { BugOutlined, ReloadOutlined, HomeOutlined, CopyOutlined, SendOutlined, WarningOutlined } from '@ant-design/icons'
import { logError } from '../utils/errorLogger'

const { Paragraph, Text } = Typography

interface Props {
  children: ReactNode
  fallback?: ReactNode
  onError?: (error: Error, errorInfo: ErrorInfo) => void
  onRetry?: () => void
  maxRetries?: number
  showReport?: boolean
}

interface State {
  hasError: boolean
  error: Error | null
  errorInfo: ErrorInfo | null
  retryCount: number
  reportSent: boolean
}

// 全局未捕获 Promise 错误处理：标记但不触发全页面崩溃
let globalRejectionHandler: ((event: PromiseRejectionEvent) => void) | null = null

// Error deduplication: track recent errors to avoid flooding the server
const _recentErrors = new Map<string, { count: number; firstTs: number; lastTs: number }>()
const ERROR_DEDUP_WINDOW = 60000 // 60s dedup window
const ERROR_DEDUP_MAX = 10 // max same error per window before suppressing

function getErrorFingerprint(error: Error, errorInfo?: ErrorInfo): string {
  // Use message + first line of component stack as fingerprint
  const componentKey = errorInfo?.componentStack?.split('\n')[1]?.trim() || ''
  return `${error.message}::${componentKey}`
}

function shouldReportError(fingerprint: string): boolean {
  const now = Date.now()
  const entry = _recentErrors.get(fingerprint)
  if (!entry || now - entry.lastTs > ERROR_DEDUP_WINDOW) {
    _recentErrors.set(fingerprint, { count: 1, firstTs: now, lastTs: now })
    return true
  }
  entry.count++
  entry.lastTs = now
  // Suppress after max occurrences within window
  if (entry.count > ERROR_DEDUP_MAX) {
    return false
  }
  return true
}

let _errorDedupInterval: ReturnType<typeof setInterval> | null = null

function startErrorDedupCleanup() {
  if (_errorDedupInterval) return
  _errorDedupInterval = setInterval(() => {
    const now = Date.now()
    for (const [key, entry] of _recentErrors) {
      if (now - entry.lastTs > ERROR_DEDUP_WINDOW) {
        _recentErrors.delete(key)
      }
    }
  }, 120000)
}

function stopErrorDedupCleanup() {
  if (_errorDedupInterval) {
    clearInterval(_errorDedupInterval)
    _errorDedupInterval = null
  }
}
// DEPRECATED: This global singleton guard is no longer used.
// Each ErrorBoundary instance now installs its own per-instance handler in
// componentDidMount / componentWillUnmount. Kept for backward-compatibility
// in case external code references it, but not called internally.
function setupRejectionGuard() {
  if (globalRejectionHandler) return
  globalRejectionHandler = (event: PromiseRejectionEvent) => {
    // 阻止默认的全局错误传播，仅记录日志
    console.warn('[ErrorBoundary] Unhandled promise rejection (isolated):', event.reason)
    event.preventDefault()
  }
  window.addEventListener('unhandledrejection', globalRejectionHandler)
}

/** @deprecated Use per-instance ErrorBoundary handlers instead. */
export { setupRejectionGuard }

export default class ErrorBoundary extends Component<Props, State> {
  private rejectionHandler: ((event: PromiseRejectionEvent) => void) | null = null

  constructor(props: Props) {
    super(props)
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      retryCount: 0,
      reportSent: false,
    }
  }

  componentDidMount(): void {
    startErrorDedupCleanup()
    // 实例级 rejection handler：每个 ErrorBoundary 维护自己的 listener，避免全局单例问题
    this.rejectionHandler = (event: PromiseRejectionEvent) => {
      console.warn('[ErrorBoundary] Unhandled promise rejection (isolated):', event.reason)
      event.preventDefault()
    }
    window.addEventListener('unhandledrejection', this.rejectionHandler)
  }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo })

    // Send error to main process for logging
    if (window.electronAPI) {
      window.electronAPI.httpRequest?.('POST', '/api/errors', {
        message: error.message,
        stack: error.stack,
        componentStack: errorInfo.componentStack,
        url: window.location.href,
        timestamp: Date.now(),
      }).catch(() => {
        // HTTP failed; log is best-effort
      })
    }

    console.error('[ErrorBoundary] Caught error:', error.message)
    console.error('[ErrorBoundary] Component stack:', errorInfo.componentStack)

    logError({
      type: 'react',
      message: error.message,
      stack: error.stack || '',
      componentStack: errorInfo.componentStack || '',
      timestamp: Date.now(),
      url: window.location.href,
      userAgent: navigator.userAgent,
    })

    this.props.onError?.(error, errorInfo)

    // 自动上报错误
    this.reportError(error, errorInfo)
  }

  /**
   * 上报错误到服务器（带去重）
   */
  reportError = async (error: Error, errorInfo: ErrorInfo): Promise<void> => {
    if (this.state.reportSent) return

    // Deduplicate: skip if same error reported too many times
    const fingerprint = getErrorFingerprint(error, errorInfo)
    if (!shouldReportError(fingerprint)) return

    try {
      const errorReport = {
        logs: [{
          id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
          level: 'error' as const,
          category: 'react',
          message: error.message,
          timestamp: new Date().toISOString(),
          sessionId: sessionStorage.getItem('session_id') || 'unknown',
          context: {
            stack: error.stack || '',
            componentStack: errorInfo.componentStack || '',
            url: window.location.href,
            userAgent: navigator.userAgent,
            retryCount: this.state.retryCount,
          },
        }],
      }

      if (navigator.onLine) {
        // 发送到后端 /api/v1/logs/report
        try {
          if (window.electronAPI?.httpRequest) {
            await window.electronAPI.httpRequest('POST', `http://localhost:${window.location.port || 8765}/api/v1/logs/report`, errorReport)
          } else {
            fetch('/api/v1/logs/report', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(errorReport),
            }).catch(() => {})
          }
          this.setState({ reportSent: true })
        } catch {
          // IPC 调用可能失败（URL 无效等），不影响主流程
        }
      }
    } catch (e) {
      console.error('[ErrorBoundary] Failed to report error:', e)
    }
  }

  handleReload = (): void => {
    window.location.reload()
  }

  handleGoHome = (): void => {
    window.location.href = '/'
  }

  handleRetry = (): void => {
    const { maxRetries = 3, onRetry } = this.props
    const { retryCount } = this.state

    if (retryCount < maxRetries) {
      this.setState({
        hasError: false,
        error: null,
        errorInfo: null,
        retryCount: retryCount + 1,
      })
      onRetry?.()
    }
  }

  handleCopyError = (): void => {
    const { error, errorInfo } = this.state
    const errorText = [
      `Error: ${error?.message}`,
      `Stack: ${error?.stack}`,
      `Component Stack: ${errorInfo?.componentStack}`,
      `URL: ${window.location.href}`,
      `Time: ${new Date().toLocaleString()}`,
      `Retry Count: ${this.state.retryCount}`,
    ].join('\n\n')

    navigator.clipboard.writeText(errorText).catch(() => {})
  }

  componentWillUnmount(): void {
    // 清理局部的 rejection handler
    if (this.rejectionHandler) {
      window.removeEventListener('unhandledrejection', this.rejectionHandler)
      this.rejectionHandler = null
    }
    stopErrorDedupCleanup()
  }

  render(): ReactNode {
    const { hasError, error, errorInfo, retryCount, reportSent } = this.state
    const { maxRetries = 3, showReport = true } = this.props

    if (hasError) {
      if (this.props.fallback) {
        return this.props.fallback
      }

      const canRetry = retryCount < maxRetries

      return (
        <div style={{ padding: 48, maxWidth: 800, margin: '0 auto' }}>
          <Result
            status="error"
            icon={<BugOutlined />}
            title="页面出错了"
            subTitle="抱歉，页面遇到了一些问题。请尝试刷新页面或返回首页。"
            extra={[
              canRetry && (
                <Button key="retry" type="primary" icon={<ReloadOutlined />} onClick={this.handleRetry}>
                  重试 ({retryCount}/{maxRetries})
                </Button>
              ),
              <Button key="reload" icon={<ReloadOutlined />} onClick={this.handleReload}>
                刷新页面
              </Button>,
              <Button key="home" icon={<HomeOutlined />} onClick={this.handleGoHome}>
                返回首页
              </Button>,
              <Button key="copy" icon={<CopyOutlined />} onClick={this.handleCopyError}>
                复制错误信息
              </Button>,
            ].filter(Boolean)}
          >
            {retryCount > 0 && (
              <Alert
                type="warning"
                icon={<WarningOutlined />}
                message={`已尝试 ${retryCount} 次重试`}
                style={{ marginBottom: 16 }}
                showIcon
              />
            )}

            {showReport && (
              <Space style={{ marginBottom: 16 }}>
                <Statistic
                  title="错误上报状态"
                  value={reportSent ? '已上报' : '待上报'}
                  valueStyle={{ color: reportSent ? '#52c41a' : '#faad14', fontSize: 14 }}
                />
                {!reportSent && (
                  <Button size="small" icon={<SendOutlined />} onClick={() => this.reportError(error!, errorInfo!)}>
                    手动上报
                  </Button>
                )}
              </Space>
            )}

            <Collapse ghost>
              <Collapse.Panel header="查看错误详情" key="1">
                <Paragraph>
                  <Text strong>错误信息: </Text>
                  <Text type="danger">{error?.message}</Text>
                </Paragraph>
                <Paragraph>
                  <Text strong>错误堆栈: </Text>
                  <Text code style={{ fontSize: 12, display: 'block', whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
                    {error?.stack}
                  </Text>
                </Paragraph>
                {errorInfo?.componentStack && (
                  <Paragraph>
                    <Text strong>组件堆栈: </Text>
                    <Text code style={{ fontSize: 12, display: 'block', whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
                      {errorInfo.componentStack}
                    </Text>
                  </Paragraph>
                )}
              </Collapse.Panel>
            </Collapse>
          </Result>
        </div>
      )
    }

    return this.props.children
  }
}

// 全局错误边界包装器
export function GlobalErrorBoundary({ children }: { children: ReactNode }): ReactNode {
  return (
    <ErrorBoundary>
      {children}
    </ErrorBoundary>
  )
}
