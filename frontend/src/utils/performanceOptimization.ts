/**
 * 性能优化工具集
 * 包含首屏加载优化、资源预加载、缓存策略等
 */

import { performanceTracker } from './performanceTracking'

interface PreloadConfig {
  critical: string[]      // 关键资源
  high: string[]          // 高优先级
  low: string[]           // 低优先级
  deferred: string[]      // 延迟加载
}

interface CacheStrategy {
  name: string
  match: (url: string) => boolean
  handler: 'networkFirst' | 'cacheFirst' | 'staleWhileRevalidate' | 'networkOnly' | 'cacheOnly'
  maxAge: number
  maxEntries?: number
}

/**
 * 首屏加载优化
 */
export class FirstScreenOptimizer {
  private loaded = new Set<string>()
  private criticalResources: string[] = []
  private loadingPromises = new Map<string, Promise<unknown>>()

  /**
   * 设置关键资源
   */
  setCriticalResources(resources: string[]): void {
    this.criticalResources = resources
  }

  /**
   * 预加载关键资源
   */
  async preloadCritical(): Promise<void> {
    const start = performance.now()

    const promises = this.criticalResources.map(resource => this.loadResource(resource, 'high'))

    await Promise.all(promises)

    const duration = performance.now() - start
    performanceTracker.end('firstScreen:criticalLoad', { duration, count: this.criticalResources.length })
  }

  /**
   * 加载单个资源
   */
  private async loadResource(url: string, priority: 'high' | 'low' = 'low'): Promise<unknown> {
    if (this.loaded.has(url)) {
      return Promise.resolve()
    }

    if (this.loadingPromises.has(url)) {
      return this.loadingPromises.get(url)!
    }

    const promise = this.doLoad(url, priority)
    this.loadingPromises.set(url, promise)

    try {
      await promise
      this.loaded.add(url)
    } finally {
      this.loadingPromises.delete(url)
    }

    return promise
  }

  /**
   * 实际加载逻辑
   */
  private async doLoad(url: string, priority: 'high' | 'low'): Promise<unknown> {
    const ext = url.split('.').pop()?.toLowerCase()

    switch (ext) {
      case 'js':
        return this.loadScript(url, priority)
      case 'css':
        return this.loadStyle(url)
      case 'png':
      case 'jpg':
      case 'jpeg':
      case 'webp':
      case 'svg':
        return this.loadImage(url)
      case 'woff':
      case 'woff2':
        return this.loadFont(url)
      default:
        return this.preloadLink(url, priority)
    }
  }

  /**
   * 加载脚本
   */
  private loadScript(url: string, priority: 'high' | 'low'): Promise<HTMLScriptElement> {
    return new Promise((resolve, reject) => {
      const script = document.createElement('script')
      script.src = url
      script.async = priority === 'low'
      script.onload = () => resolve(script)
      script.onerror = reject
      document.head.appendChild(script)
    })
  }

  /**
   * 加载样式
   */
  private loadStyle(url: string): Promise<HTMLLinkElement> {
    return new Promise((resolve, reject) => {
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = url
      link.onload = () => resolve(link)
      link.onerror = reject
      document.head.appendChild(link)
    })
  }

  /**
   * 预加载图片
   */
  private loadImage(url: string): Promise<HTMLImageElement> {
    return new Promise((resolve, reject) => {
      const img = new Image()
      img.onload = () => resolve(img)
      img.onerror = reject
      img.src = url
    })
  }

  /**
   * 预加载字体
   */
  private loadFont(url: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const link = document.createElement('link')
      link.rel = 'preload'
      link.as = 'font'
      link.href = url
      link.crossOrigin = 'anonymous'
      link.onload = () => resolve()
      link.onerror = reject
      document.head.appendChild(link)
    })
  }

  /**
   * 使用 link preload
   */
  private preloadLink(url: string, priority: 'high' | 'low'): Promise<void> {
    return new Promise((resolve, reject) => {
      const link = document.createElement('link')
      link.rel = priority === 'high' ? 'preload' : 'prefetch'
      link.href = url
      link.onload = () => resolve()
      link.onerror = reject
      document.head.appendChild(link)
    })
  }

  /**
   * 延迟加载非关键资源
   */
  deferLoad(resources: string[]): void {
    if ('requestIdleCallback' in window) {
      requestIdleCallback(() => {
        resources.forEach(url => this.loadResource(url, 'low'))
      })
    } else {
      setTimeout(() => {
        resources.forEach(url => this.loadResource(url, 'low'))
      }, 1000)
    }
  }

  /**
   * 获取加载状态
   */
  getLoadStatus(): { loaded: number; total: number; pending: number } {
    return {
      loaded: this.loaded.size,
      total: this.criticalResources.length,
      pending: this.loadingPromises.size,
    }
  }
}

/**
 * 资源预加载器
 */
export class ResourcePreloader {
  private preloaded = new Set<string>()
  private prefetchQueue: string[] = []
  private isProcessing = false

  /**
   * 预加载资源
   */
  preload(url: string, options?: { as?: string; priority?: 'high' | 'low' }): void {
    if (this.preloaded.has(url)) return

    const link = document.createElement('link')
    link.rel = options?.priority === 'high' ? 'preload' : 'prefetch'
    link.href = url

    if (options?.as) {
      link.as = options.as
    }

    document.head.appendChild(link)
    this.preloaded.add(url)
  }

  /**
   * 批量预加载
   */
  preloadBatch(urls: string[], options?: { as?: string; priority?: 'high' | 'low' }): void {
    urls.forEach(url => this.preload(url, options))
  }

  /**
   * 添加到预取队列
   */
  addToPrefetchQueue(url: string): void {
    if (!this.preloaded.has(url) && !this.prefetchQueue.includes(url)) {
      this.prefetchQueue.push(url)
      this.processQueue()
    }
  }

  /**
   * 处理预取队列
   */
  private processQueue(): void {
    if (this.isProcessing || this.prefetchQueue.length === 0) return

    this.isProcessing = true

    const processNext = () => {
      if (this.prefetchQueue.length === 0) {
        this.isProcessing = false
        return
      }

      const url = this.prefetchQueue.shift()!
      this.preload(url, { priority: 'low' })

      // 使用 requestIdleCallback 处理下一个
      if ('requestIdleCallback' in window) {
        requestIdleCallback(processNext, { timeout: 100 })
      } else {
        setTimeout(processNext, 50)
      }
    }

    processNext()
  }

  /**
   * 预连接域名
   */
  preconnect(domains: string[]): void {
    domains.forEach(domain => {
      const link = document.createElement('link')
      link.rel = 'preconnect'
      link.href = domain
      document.head.appendChild(link)

      // DNS 预解析
      const dnsLink = document.createElement('link')
      dnsLink.rel = 'dns-prefetch'
      dnsLink.href = domain
      document.head.appendChild(dnsLink)
    })
  }

  /**
   * 清除预加载记录
   */
  clear(): void {
    this.preloaded.clear()
    this.prefetchQueue = []
    this.isProcessing = false
  }
}

/**
 * 缓存策略管理器
 */
export class CacheStrategyManager {
  private strategies: CacheStrategy[] = [
    // API 请求 - 网络优先
    {
      name: 'api',
      match: (url) => url.includes('/api/'),
      handler: 'networkFirst',
      maxAge: 60000, // 1分钟
    },
    // 静态资源 - 缓存优先
    {
      name: 'static',
      match: (url) => /\.(js|css|woff2?|ttf|eot)$/.test(url),
      handler: 'cacheFirst',
      maxAge: 86400000 * 30, // 30天
      maxEntries: 100,
    },
    // 图片 - 边缓存边返回
    {
      name: 'images',
      match: (url) => /\.(png|jpe?g|webp|svg|gif|ico)$/.test(url),
      handler: 'staleWhileRevalidate',
      maxAge: 86400000 * 7, // 7天
      maxEntries: 200,
    },
    // 实时数据 - 仅网络
    {
      name: 'realtime',
      match: (url) => url.includes('/realtime/') || url.includes('/ws'),
      handler: 'networkOnly',
      maxAge: 0,
    },
    // K线数据 - 边缓存边更新
    {
      name: 'kline',
      match: (url) => url.includes('/kline') || url.includes('/history'),
      handler: 'staleWhileRevalidate',
      maxAge: 300000, // 5分钟
      maxEntries: 500,
    },
  ]

  /**
   * 添加自定义策略
   */
  addStrategy(strategy: CacheStrategy): void {
    this.strategies.unshift(strategy)
  }

  /**
   * 获取资源的缓存策略
   */
  getStrategy(url: string): CacheStrategy | null {
    for (const strategy of this.strategies) {
      if (strategy.match(url)) {
        return strategy
      }
    }
    return null
  }

  /**
   * 执行缓存策略
   */
  async fetch(url: string, options?: RequestInit): Promise<Response> {
    const strategy = this.getStrategy(url)

    if (!strategy) {
      return fetch(url, options)
    }

    switch (strategy.handler) {
      case 'networkFirst':
        return this.networkFirst(url, options, strategy.maxAge)
      case 'cacheFirst':
        return this.cacheFirst(url, options, strategy.maxAge)
      case 'staleWhileRevalidate':
        return this.staleWhileRevalidate(url, options, strategy.maxAge)
      case 'networkOnly':
        return fetch(url, options)
      case 'cacheOnly':
        return this.cacheOnly(url)
      default:
        return fetch(url, options)
    }
  }

  /**
   * 网络优先策略
   */
  private async networkFirst(url: string, options?: RequestInit, maxAge?: number): Promise<Response> {
    try {
      const response = await fetch(url, options)
      if (response.ok && 'caches' in window) {
        const cache = await caches.open('network-first')
        await cache.put(url, response.clone())
      }
      return response
    } catch {
      // 网络失败，尝试缓存
      const cached = await this.getValidCache(url, maxAge)
      if (cached) return cached
      throw new Error('Network failed and no valid cache')
    }
  }

  /**
   * 缓存优先策略
   */
  private async cacheFirst(url: string, options?: RequestInit, maxAge?: number): Promise<Response> {
    const cached = await this.getValidCache(url, maxAge)
    if (cached) return cached

    const response = await fetch(url, options)
    if (response.ok && 'caches' in window) {
      const cache = await caches.open('cache-first')
      await cache.put(url, response.clone())
    }
    return response
  }

  /**
   * 边缓存边更新策略
   */
  private async staleWhileRevalidate(url: string, options?: RequestInit, maxAge?: number): Promise<Response> {
    const cached = await this.getValidCache(url, maxAge)

    // 后台更新缓存
    const updatePromise = fetch(url, options).then(response => {
      if (response.ok && 'caches' in window) {
        caches.open('stale-while-revalidate').then(cache => {
          cache.put(url, response.clone())
        })
      }
      return response
    }).catch(() => null)

    // 返回缓存或等待网络
    if (cached) {
      return cached
    }

    const response = await updatePromise
    if (response) return response

    throw new Error('No cache and network failed')
  }

  /**
   * 仅缓存策略
   */
  private async cacheOnly(url: string): Promise<Response> {
    const cached = await caches.match(url)
    if (cached) return cached
    throw new Error('No cache available')
  }

  /**
   * 获取有效缓存
   */
  private async getValidCache(url: string, maxAge?: number): Promise<Response | undefined> {
    if (!('caches' in window)) return undefined

    const cached = await caches.match(url)
    if (!cached) return undefined

    // 检查过期时间
    if (maxAge) {
      const dateHeader = cached.headers.get('date')
      if (dateHeader) {
        const cachedTime = new Date(dateHeader).getTime()
        if (Date.now() - cachedTime > maxAge) {
          return undefined
        }
      }
    }

    return cached
  }

  /**
   * 清理过期缓存
   */
  async cleanExpiredCache(): Promise<number> {
    if (!('caches' in window)) return 0

    let cleaned = 0
    const cacheNames = await caches.keys()

    for (const name of cacheNames) {
      const cache = await caches.open(name)
      const requests = await cache.keys()

      for (const request of requests) {
        const response = await cache.match(request)
        if (response) {
          const strategy = this.getStrategy(request.url)
          if (strategy?.maxAge) {
            const dateHeader = response.headers.get('date')
            if (dateHeader) {
              const cachedTime = new Date(dateHeader).getTime()
              if (Date.now() - cachedTime > strategy.maxAge) {
                await cache.delete(request)
                cleaned++
              }
            }
          }
        }
      }
    }

    return cleaned
  }
}

/**
 * 渲染优化器
 */
export class RenderOptimizer {
  private rafId: number | null = null
  private pendingUpdates = new Set<() => void>()
  private isScheduled = false

  /**
   * 批量更新
   */
  batchUpdate(updateFn: () => void): void {
    this.pendingUpdates.add(updateFn)
    this.scheduleFlush()
  }

  /**
   * 调度刷新
   */
  private scheduleFlush(): void {
    if (this.isScheduled) return
    this.isScheduled = true

    this.rafId = requestAnimationFrame(() => {
      this.flush()
      this.isScheduled = false
    })
  }

  /**
   * 执行所有更新
   */
  private flush(): void {
    const updates = [...this.pendingUpdates]
    this.pendingUpdates.clear()

    updates.forEach(update => update())
  }

  /**
   * 取消所有更新
   */
  cancel(): void {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    this.pendingUpdates.clear()
    this.isScheduled = false
  }

  /**
   * 使用 IntersectionObserver 延迟加载
   */
  lazyLoad(element: HTMLElement, callback: () => void, options?: IntersectionObserverInit): () => void {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          callback()
          observer.disconnect()
        }
      })
    }, options)

    observer.observe(element)

    return () => observer.disconnect()
  }

  /**
   * 虚拟列表辅助
   */
  createVirtualList<T>(
    container: HTMLElement,
    items: T[],
    renderItem: (item: T, index: number) => HTMLElement,
    options?: {
      itemHeight?: number
      overscan?: number
      bufferSize?: number
    }
  ): {
    scrollTo: (index: number) => void
    update: (newItems: T[]) => void
    destroy: () => void
  } {
    const itemHeight = options?.itemHeight || 40
    const overscan = options?.overscan || 3
    const bufferSize = options?.bufferSize || 20

    let visibleItems: T[] = []
    let startIndex = 0
    let endIndex = 0

    const wrapper = document.createElement('div')
    wrapper.style.position = 'relative'
    wrapper.style.height = `${items.length * itemHeight}px`

    const viewport = document.createElement('div')
    viewport.style.position = 'absolute'
    viewport.style.top = '0'
    viewport.style.width = '100%'

    wrapper.appendChild(viewport)
    container.appendChild(wrapper)

    const render = () => {
      const scrollTop = container.scrollTop
      const viewportHeight = container.clientHeight

      startIndex = Math.max(0, Math.floor(scrollTop / itemHeight) - overscan)
      endIndex = Math.min(items.length, Math.ceil((scrollTop + viewportHeight) / itemHeight) + overscan)

      visibleItems = items.slice(startIndex, endIndex)

      viewport.innerHTML = ''
      viewport.style.transform = `translateY(${startIndex * itemHeight}px)`

      visibleItems.forEach((item, i) => {
        const element = renderItem(item, startIndex + i)
        element.style.height = `${itemHeight}px`
        viewport.appendChild(element)
      })
    }

    const scrollHandler = () => {
      requestAnimationFrame(render)
    }

    container.addEventListener('scroll', scrollHandler)
    render()

    return {
      scrollTo: (index: number) => {
        container.scrollTop = index * itemHeight
      },
      update: (newItems: T[]) => {
        items = newItems
        wrapper.style.height = `${items.length * itemHeight}px`
        render()
      },
      destroy: () => {
        container.removeEventListener('scroll', scrollHandler)
        container.removeChild(wrapper)
      },
    }
  }
}

/**
 * 数据预取策略
 */
export class DataPrefetchStrategy {
  private prefetched = new Map<string, { data: unknown; timestamp: number }>()
  private prefetchQueue: Array<{ key: string; fetcher: () => Promise<unknown> }> = []
  private maxCache = 100
  private maxAge = 300000 // 5分钟

  /**
   * 预取数据
   */
  async prefetch(key: string, fetcher: () => Promise<unknown>): Promise<void> {
    if (this.prefetched.has(key)) return

    try {
      const data = await fetcher()
      this.prefetched.set(key, { data, timestamp: Date.now() })
      this.cleanup()
    } catch (error) {
      console.warn(`[Prefetch] Failed: ${key}`, error)
    }
  }

  /**
   * 添加到预取队列
   */
  queuePrefetch(key: string, fetcher: () => Promise<unknown>): void {
    if (this.prefetched.has(key) || this.prefetchQueue.some(q => q.key === key)) return

    this.prefetchQueue.push({ key, fetcher })
    this.processQueue()
  }

  /**
   * 处理预取队列
   */
  private async processQueue(): Promise<void> {
    while (this.prefetchQueue.length > 0) {
      const item = this.prefetchQueue.shift()!
      await this.prefetch(item.key, item.fetcher)

      // 等待一小段时间避免过度请求
      await new Promise(resolve => setTimeout(resolve, 100))
    }
  }

  /**
   * 获取预取的数据
   */
  get<T>(key: string): T | null {
    const cached = this.prefetched.get(key)
    if (!cached) return null

    // 检查过期
    if (Date.now() - cached.timestamp > this.maxAge) {
      this.prefetched.delete(key)
      return null
    }

    return cached.data as T
  }

  /**
   * 清理过期数据
   */
  private cleanup(): void {
    // 清理过期数据
    const now = Date.now()
    for (const [key, value] of this.prefetched) {
      if (now - value.timestamp > this.maxAge) {
        this.prefetched.delete(key)
      }
    }

    // 清理超出数量限制
    if (this.prefetched.size > this.maxCache) {
      const keys = [...this.prefetched.keys()].slice(0, this.prefetched.size - this.maxCache)
      keys.forEach(key => this.prefetched.delete(key))
    }
  }

  /**
   * 清除所有
   */
  clear(): void {
    this.prefetched.clear()
    this.prefetchQueue = []
  }
}

// 导出单例
export const firstScreenOptimizer = new FirstScreenOptimizer()
export const resourcePreloader = new ResourcePreloader()
export const cacheStrategyManager = new CacheStrategyManager()
export const renderOptimizer = new RenderOptimizer()
export const dataPrefetchStrategy = new DataPrefetchStrategy()

/**
 * 初始化性能优化
 */
export function initPerformanceOptimization(): void {
  // 预连接关键域名
  resourcePreloader.preconnect([
    'https://api.example.com',
    'https://cdn.example.com',
    'https://fonts.googleapis.com',
  ])

  // 定期清理缓存
  setInterval(() => {
    cacheStrategyManager.cleanExpiredCache()
  }, 3600000) // 1小时

  console.log('[Performance] Optimization initialized')
}

export default {
  firstScreenOptimizer,
  resourcePreloader,
  cacheStrategyManager,
  renderOptimizer,
  dataPrefetchStrategy,
  initPerformanceOptimization,
}
