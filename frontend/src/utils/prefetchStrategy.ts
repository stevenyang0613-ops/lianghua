/**
 * 数据预取策略
 * 基于用户行为预测预取数据，提升感知速度
 */

interface PrefetchRule {
  pattern: RegExp | string
  prefetch: (match: string) => Promise<void>
  priority: 'high' | 'medium' | 'low'
  condition?: () => boolean
}

interface UserBehavior {
  path: string
  timestamp: number
  action: string
  data?: Record<string, unknown>
}

class PrefetchManager {
  private rules: PrefetchRule[] = []
  private behaviorHistory: UserBehavior[] = []
  private prefetchQueue: Array<{ url: string; priority: number }> = []
  private isProcessing: boolean = false
  private maxHistorySize = 100
  private prefetchCache: Set<string> = new Set()

  constructor() {
    // 监听路由变化
    this.trackNavigation()
    // 启动预取处理
    this.startProcessing()
  }

  /**
   * 注册预取规则
   */
  registerRule(rule: PrefetchRule): void {
    this.rules.push(rule)
  }

  /**
   * 追踪用户导航
   */
  private trackNavigation(): void {
    // 记录当前路径
    this.recordBehavior(window.location.pathname, 'navigate')

    // 监听 popstate
    window.addEventListener('popstate', () => {
      this.recordBehavior(window.location.pathname, 'navigate')
    })

    // 监听点击事件（捕获阶段）
    document.addEventListener('click', (e) => {
      const target = e.target as HTMLElement
      const link = target.closest('a')
      if (link && link.href) {
        const path = new URL(link.href).pathname
        this.recordBehavior(path, 'click-link')

        // 预测并预取
        this.predictAndPrefetch(path)
      }
    }, true)
  }

  /**
   * 记录用户行为
   */
  recordBehavior(path: string, action: string, data?: Record<string, unknown>): void {
    this.behaviorHistory.push({
      path,
      timestamp: Date.now(),
      action,
      data,
    })

    // 限制历史记录大小
    if (this.behaviorHistory.length > this.maxHistorySize) {
      this.behaviorHistory.shift()
    }
  }

  /**
   * 预测并预取
   */
  private predictAndPrefetch(currentPath: string): void {
    // 基于历史行为预测下一步
    const predictions = this.predictNextPages(currentPath)

    for (const prediction of predictions) {
      this.queuePrefetch(prediction.url, prediction.priority)
    }
  }

  /**
   * 预测下一页
   */
  private predictNextPages(currentPath: string): Array<{ url: string; priority: number }> {
    const predictions: Array<{ url: string; priority: number }> = []

    // 分析历史行为，找出当前路径后常访问的页面
    const transitions: Map<string, number> = new Map()

    for (let i = 0; i < this.behaviorHistory.length - 1; i++) {
      if (this.behaviorHistory[i].path === currentPath) {
        const nextPath = this.behaviorHistory[i + 1].path
        transitions.set(nextPath, (transitions.get(nextPath) || 0) + 1)
      }
    }

    // 按频率排序
    const sorted = [...transitions.entries()].sort((a, b) => b[1] - a[1])

    for (let i = 0; i < Math.min(3, sorted.length); i++) {
      predictions.push({
        url: sorted[i][0],
        priority: 10 - i * 3, // 高频页面优先级更高
      })
    }

    // 应用规则
    for (const rule of this.rules) {
      const pattern = rule.pattern instanceof RegExp ? rule.pattern : new RegExp(rule.pattern)
      if (pattern.test(currentPath)) {
        if (!rule.condition || rule.condition()) {
          predictions.push({
            url: `rule:${currentPath}`,
            priority: rule.priority === 'high' ? 15 : rule.priority === 'medium' ? 10 : 5,
          })
        }
      }
    }

    return predictions
  }

  /**
   * 加入预取队列
   */
  private queuePrefetch(url: string, priority: number): void {
    if (this.prefetchCache.has(url)) return

    this.prefetchQueue.push({ url, priority })
    this.prefetchQueue.sort((a, b) => b.priority - a.priority)
    this.prefetchCache.add(url)
  }

  /**
   * 启动预取处理
   */
  private startProcessing(): void {
    // 使用 requestIdleCallback 在空闲时预取
    const processQueue = () => {
      if (this.isProcessing || this.prefetchQueue.length === 0) return

      this.isProcessing = true
      const item = this.prefetchQueue.shift()!

      this.processPrefetch(item.url)
        .then(() => {
          this.isProcessing = false
          // 继续处理下一个
          if ('requestIdleCallback' in window) {
            requestIdleCallback(processQueue)
          } else {
            setTimeout(processQueue, 100)
          }
        })
        .catch(() => {
          this.isProcessing = false
        })
    }

    // 定期检查队列
    setInterval(() => {
      if (this.prefetchQueue.length > 0 && !this.isProcessing) {
        processQueue()
      }
    }, 5000)

    // 页面加载完成后开始预取
    window.addEventListener('load', () => {
      if ('requestIdleCallback' in window) {
        requestIdleCallback(processQueue)
      }
    })
  }

  /**
   * 执行预取
   */
  private async processPrefetch(url: string): Promise<void> {
    // 检查是否是规则预取
    if (url.startsWith('rule:')) {
      const actualPath = url.slice(5)
      for (const rule of this.rules) {
        const pattern = rule.pattern instanceof RegExp ? rule.pattern : new RegExp(rule.pattern)
        if (pattern.test(actualPath)) {
          await rule.prefetch(actualPath)
        }
      }
      return
    }

    // 预取路由组件
    await this.prefetchRoute(url)
  }

  /**
   * 预取路由
   */
  private async prefetchRoute(path: string): Promise<void> {
    // 路由到组件的映射
    const routeComponentMap: Record<string, () => Promise<unknown>> = {
      '/market': () => import('../pages/Market'),
      '/watchlist': () => import('../pages/Watchlist'),
      '/backtest': () => import('../pages/Backtest'),
      '/trade': () => import('../pages/Trade'),
      '/analysis': () => import('../pages/Analysis'),
      '/signals': () => import('../pages/Signals'),
      '/strategies': () => import('../pages/Strategies'),
      '/settings': () => import('../pages/Settings'),
      '/performance': () => import('../pages/Performance'),
      '/trade-log': () => import('../pages/TradeLog'),
      '/strategy-replay': () => import('../pages/StrategyReplay'),
      '/accounts': () => import('../pages/AccountManager'),
      '/alerts': () => import('../pages/AlertManager'),
      '/reports': () => import('../pages/ReportCenter'),
      '/risk': () => import('../pages/RiskControl'),
      '/auto-trade': () => import('../pages/AutoTrade'),
      '/data-player': () => import('../pages/DataPlayer'),
      '/strategy-market': () => import('../pages/StrategyMarket'),
      '/dashboard': () => import('../pages/Dashboard'),
      '/messages': () => import('../pages/MessageCenter'),
      '/themes': () => import('../pages/ThemeStore'),
      '/plugins': () => import('../pages/PluginManager'),
      '/score-ranking': () => import('../pages/ScoreRanking'),
      '/sync': () => import('../pages/SyncSettings'),
      '/songgang-score': () => import('../pages/SonggangScore'),
    }

    const loader = routeComponentMap[path]
    if (loader) {
      try {
        await loader()
        console.log(`[Prefetch] Preloaded: ${path}`)
      } catch (error) {
        console.warn(`[Prefetch] Failed to preload: ${path}`, error)
      }
    }
  }

  /**
   * 手动预取
   */
  async prefetch(paths: string[]): Promise<void> {
    for (const path of paths) {
      this.queuePrefetch(path, 5)
    }
  }

  /**
   * 获取预取状态
   */
  getStatus(): {
    queueSize: number
    historySize: number
    cachedCount: number
  } {
    return {
      queueSize: this.prefetchQueue.length,
      historySize: this.behaviorHistory.length,
      cachedCount: this.prefetchCache.size,
    }
  }

  /**
   * 清除缓存
   */
  clearCache(): void {
    this.prefetchCache.clear()
    this.prefetchQueue = []
  }
}

// 导出单例
export const prefetchManager = new PrefetchManager()

/**
 * 初始化预取策略
 */
export function initPrefetchStrategy(): void {
  // 注册预取规则
  prefetchManager.registerRule({
    pattern: /^\/market/,
    prefetch: async () => {
      // 预取市场数据
      console.log('[Prefetch] Preloading market data')
    },
    priority: 'high',
  })

  prefetchManager.registerRule({
    pattern: /^\/watchlist/,
    prefetch: async () => {
      // 预取自选列表
      console.log('[Prefetch] Preloading watchlist')
    },
    priority: 'high',
  })

  prefetchManager.registerRule({
    pattern: /^\/backtest/,
    prefetch: async () => {
      // 预取回测数据
      console.log('[Prefetch] Preloading backtest data')
    },
    priority: 'medium',
  })
}

export default prefetchManager
