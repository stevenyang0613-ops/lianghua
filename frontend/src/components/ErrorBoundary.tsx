/**
 * React 错误边界组件
 * 全局错误捕获和用户友好提示
 * 支持错误上报、重试机制、降级 UI
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

export default class ErrorBoundary extends Component<Props, State> {
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

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({ errorInfo })

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
   * 上报错误到服务器
   */
  reportError = async (error: Error, errorInfo: ErrorInfo): Promise<void> => {
    if (this.state.reportSent) return

    try {
      // 这里可以替换为实际的错误上报 API
      const errorReport = {
        message: error.message,
        stack: error.stack,
        componentStack: errorInfo.componentStack,
        url: window.location.href,
        userAgent: navigator.userAgent,
        timestamp: Date.now(),
        retryCount: this.state.retryCount,
      }

      // 尝试发送到错误收集服务
      if (navigator.onLine) {
        // 示例：发送到后端
        // await fetch('/api/errors', {
        //   method: 'POST',
        //   headers: { 'Content-Type': 'application/json' },
        //   body: JSON.stringify(errorReport),
        // })

        console.log('[ErrorBoundary] Error reported:', errorReport)
        this.setState({ reportSent: true })
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

    navigator.clipboard.writeText(errorText)
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
