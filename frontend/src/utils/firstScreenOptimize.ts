/**
 * 首屏加载性能优化工具
 * 实现关键资源预加载、代码分割优化、骨架屏
 */

// 关键资源预加载
export function preloadCriticalResources() {
  const criticalResources = [
    // 预加载字体
    { rel: 'preload', as: 'font', href: 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap', crossorigin: 'anonymous' },
  ]

  criticalResources.forEach((resource) => {
    const link = document.createElement('link')
    Object.assign(link, resource)
    document.head.appendChild(link)
  })
}

// 骨架屏组件样式
export const skeletonStyles = `
  .skeleton {
    background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
    background-size: 200% 100%;
    animation: skeleton-loading 1.5s infinite;
  }

  @keyframes skeleton-loading {
    0% { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

  .skeleton-text {
    height: 16px;
    border-radius: 4px;
    margin-bottom: 8px;
  }

  .skeleton-title {
    height: 24px;
    border-radius: 4px;
    width: 60%;
    margin-bottom: 16px;
  }

  .skeleton-card {
    background: #fff;
    border-radius: 8px;
    padding: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  }

  .skeleton-row {
    display: flex;
    gap: 12px;
    margin-bottom: 12px;
  }

  .skeleton-avatar {
    width: 40px;
    height: 40px;
    border-radius: 50%;
  }

  .skeleton-button {
    height: 32px;
    border-radius: 4px;
    width: 80px;
  }
`

// 注入骨架屏样式
export function injectSkeletonStyles() {
  const style = document.createElement('style')
  style.textContent = skeletonStyles
  document.head.appendChild(style)
}

// 性能监控
export function measureFirstPaint() {
  if (typeof performance === 'undefined') return null

  const timing = performance.timing
  const navigationStart = timing.navigationStart

  return {
    // DNS 查询时间
    dns: timing.domainLookupEnd - timing.domainLookupStart,
    // TCP 连接时间
    tcp: timing.connectEnd - timing.connectStart,
    // 请求响应时间
    request: timing.responseEnd - timing.requestStart,
    // DOM 解析时间
    domParse: timing.domInteractive - timing.responseEnd,
    // 资源加载时间
    resource: timing.loadEventStart - timing.domContentLoadedEventEnd,
    // 首屏时间
    firstPaint: timing.responseStart - navigationStart,
    // DOM Ready 时间
    domReady: timing.domContentLoadedEventEnd - navigationStart,
    // 页面完全加载时间
    load: timing.loadEventEnd - navigationStart,
  }
}

// 请求空闲回调
export function requestIdleCallback(callback: IdleRequestCallback, options?: IdleRequestOptions): number {
  if ('requestIdleCallback' in window) {
    return window.requestIdleCallback(callback, options)
  }

  // 降级处理
  const start = Date.now()
  return setTimeout(() => {
    callback({
      didTimeout: false,
      timeRemaining: () => Math.max(0, 50 - (Date.now() - start)),
    })
  }, 1) as unknown as number
}

// 取消空闲回调
export function cancelIdleCallback(id: number) {
  if ('cancelIdleCallback' in window) {
    window.cancelIdleCallback(id)
  } else {
    clearTimeout(id)
  }
}

// 延迟非关键任务
export function deferNonCriticalTask(callback: () => void, timeout = 2000) {
  requestIdleCallback(
    (deadline) => {
      if (deadline.timeRemaining() > 0 || deadline.didTimeout) {
        callback()
      } else {
        deferNonCriticalTask(callback, timeout)
      }
    },
    { timeout }
  )
}

// 图片懒加载
export function setupLazyLoading() {
  if ('loading' in HTMLImageElement.prototype) {
    // 原生支持
    document.querySelectorAll('img[data-src]').forEach((img) => {
      const src = img.getAttribute('data-src')
      if (src) {
        img.setAttribute('src', src)
        img.removeAttribute('data-src')
      }
    })
  } else {
    // 降级：使用 IntersectionObserver
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          const img = entry.target as HTMLImageElement
          const src = img.getAttribute('data-src')
          if (src) {
            img.setAttribute('src', src)
            img.removeAttribute('data-src')
            observer.unobserve(img)
          }
        }
      })
    })

    document.querySelectorAll('img[data-src]').forEach((img) => {
      observer.observe(img)
    })
  }
}

// 预连接到关键域名
export function preconnectOrigins() {
  const origins = [
    'https://fonts.googleapis.com',
    'https://fonts.gstatic.com',
  ]

  origins.forEach((origin) => {
    const link = document.createElement('link')
    link.rel = 'preconnect'
    link.href = origin
    link.crossOrigin = 'anonymous'
    document.head.appendChild(link)
  })
}

// 初始化首屏优化
export function initFirstScreenOptimize() {
  // 预连接关键域名
  preconnectOrigins()

  // 预加载关键资源
  preloadCriticalResources()

  // 注入骨架屏样式
  injectSkeletonStyles()

  // 延迟执行非关键任务
  deferNonCriticalTask(() => {
    setupLazyLoading()

    // 上报性能指标
    const metrics = measureFirstPaint()
    if (metrics) {
      console.log('[Performance] First screen metrics:', metrics)
    }
  })
}

export default {
  preloadCriticalResources,
  injectSkeletonStyles,
  measureFirstPaint,
  requestIdleCallback,
  cancelIdleCallback,
  deferNonCriticalTask,
  setupLazyLoading,
  preconnectOrigins,
  initFirstScreenOptimize,
}
