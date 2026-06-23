/**
 * 路由预加载服务
 */

import type { ComponentType } from 'react'

const PRELOAD_PRIORITY = {
  high: ['/', '/market', '/watchlist', '/signals', '/dashboard'],
  medium: ['/trade', '/backtest', '/strategies', '/alerts'],
  low: ['/settings', '/performance', '/themes', '/plugins'],
} as const

const preloadedModules = new Set<string>()
const pendingPreloads = new Map<string, Promise<unknown>>()
const moduleMap: Record<string, () => Promise<{ default: ComponentType<unknown> }>> = {}

export function registerPreloadableModules(
  modules: Record<string, () => Promise<{ default: ComponentType<unknown> }>>
): void {
  Object.assign(moduleMap, modules)
}

export function preloadRoute(route: string): Promise<unknown> {
  if (preloadedModules.has(route)) return Promise.resolve()
  if (pendingPreloads.has(route)) return pendingPreloads.get(route)!

  const loader = moduleMap[route]
  if (!loader) return Promise.resolve()

  const promise = loader().then(() => {
    preloadedModules.add(route)
    pendingPreloads.delete(route)
  }).catch((error) => {
    console.warn(`[Preload] 预加载失败: ${route}`, error)
    pendingPreloads.delete(route)
  })

  pendingPreloads.set(route, promise)
  return promise
}

export function preloadRoutes(routes: string[]): Promise<unknown[]> {
  return Promise.all(routes.map(preloadRoute))
}

export function preloadByPriority(): () => void {
  void preloadRoutes([...PRELOAD_PRIORITY.high])
  const t1 = setTimeout(() => preloadRoutes([...PRELOAD_PRIORITY.medium]), 1000)
  const t2 = setTimeout(() => preloadRoutes([...PRELOAD_PRIORITY.low]), 3000)
  return () => {
    clearTimeout(t1)
    clearTimeout(t2)
  }
}

export function preloadAllRoutes(): void {
  preloadRoutes(Object.keys(moduleMap))
}

export function setupSmartPreload(): () => void {
  const handleMouseOver = (e: MouseEvent) => {
    const target = e.target as HTMLElement
    const link = target.closest('a[href], [data-preload]')
    if (link) {
      const route = link.getAttribute('href') || link.getAttribute('data-preload')
      if (route) void preloadRoute(route)
    }
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        const route = (entry.target as HTMLElement).dataset.preloadViewport
        if (route) void preloadRoute(route)
      }
    })
  }, { rootMargin: '100px' })

  const observeElements = () => {
    document.querySelectorAll('[data-preload-viewport]').forEach((el) => observer.observe(el))
  }

  document.addEventListener('mouseover', handleMouseOver)
  if (document.readyState === 'complete') observeElements()
  else {
    const _observeElements = observeElements
    window.addEventListener('load', _observeElements)
  }

  return () => {
    document.removeEventListener('mouseover', handleMouseOver)
    window.removeEventListener('load', observeElements)
    observer.disconnect()
  }
}

export function preloadAssets(assets: Array<{ type: 'image' | 'font' | 'style' | 'script'; url: string }>): void {
  assets.forEach(({ type, url }) => {
    const link = document.createElement('link')
    link.rel = type === 'font' ? 'preload' : 'prefetch'
    link.as = type === 'image' ? 'image' : type === 'style' ? 'style' : type === 'script' ? 'script' : 'font'
    link.href = url
    if (type === 'font') link.crossOrigin = 'anonymous'
    document.head.appendChild(link)
  })
}

export function getPreloadStatus(): { preloaded: string[]; pending: string[]; total: number } {
  return {
    preloaded: [...preloadedModules],
    pending: [...pendingPreloads.keys()],
    total: Object.keys(moduleMap).length,
  }
}

export function clearPreloadCache(): void {
  preloadedModules.clear()
  pendingPreloads.clear()
}

export default {
  registerPreloadableModules,
  preloadRoute,
  preloadRoutes,
  preloadByPriority,
  preloadAllRoutes,
  setupSmartPreload,
  preloadAssets,
  getPreloadStatus,
  clearPreloadCache,
}
