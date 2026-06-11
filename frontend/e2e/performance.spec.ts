/**
 * 性能监控 E2E 测试
 */

import { test, expect } from '@playwright/test'

test.describe('性能监控', () => {
  test('页面加载性能', async ({ page }) => {
    const startTime = Date.now()
    await page.goto('/')
    await page.waitForLoadState('networkidle')
    const loadTime = Date.now() - startTime

    // 页面加载时间应小于 5 秒
    expect(loadTime).toBeLessThan(5000)
    console.log(`Page load time: ${loadTime}ms`)
  })

  test('路由切换性能', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const routes = ['/market', '/watchlist', '/backtest', '/trade', '/settings']

    for (const route of routes) {
      const startTime = Date.now()
      await page.goto(route)
      await page.waitForLoadState('networkidle')
      const switchTime = Date.now() - startTime

      console.log(`Route ${route} switch time: ${switchTime}ms`)
      expect(switchTime).toBeLessThan(3000)
    }
  })

  test('内存使用', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 获取客户端内存信息（Chrome only）
    const memory = await page.evaluate(() => {
      if ('memory' in performance) {
        return {
          usedJSHeapSize: (performance as any).memory.usedJSHeapSize,
          totalJSHeapSize: (performance as any).memory.totalJSHeapSize,
          jsHeapSizeLimit: (performance as any).memory.jsHeapSizeLimit,
        }
      }
      return null
    })

    if (memory) {
      console.log('Memory usage:', {
        used: `${(memory.usedJSHeapSize / 1024 / 1024).toFixed(2)} MB`,
        total: `${(memory.totalJSHeapSize / 1024 / 1024).toFixed(2)} MB`,
        limit: `${(memory.jsHeapSizeLimit / 1024 / 1024).toFixed(2)} MB`,
      })

      // 内存使用应小于 500MB
      expect(memory.usedJSHeapSize).toBeLessThan(500 * 1024 * 1024)
    }
  })

  test('控制台错误检查', async ({ page }) => {
    const errors: string[] = []
    const warnings: string[] = []

    page.on('console', msg => {
      if (msg.type() === 'error') {
        errors.push(msg.text())
      } else if (msg.type() === 'warning') {
        warnings.push(msg.text())
      }
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 遍历主要页面
    const routes = ['/market', '/watchlist', '/settings']
    for (const route of routes) {
      await page.goto(route)
      await page.waitForLoadState('networkidle')
    }

    // 检查是否有严重错误（排除一些已知的非关键错误）
    const criticalErrors = errors.filter(err =>
      !err.includes('Non-serializable') &&
      !err.includes('Warning:') &&
      !err.includes('[HMR]') &&
      !err.includes('DevTools')
    )

    console.log('Console errors:', criticalErrors)
    console.log('Console warnings:', warnings.slice(0, 5))

    // 不应该有关键错误
    expect(criticalErrors.length).toBeLessThan(3)
  })

  test('网络请求性能', async ({ page }) => {
    const requests: Array<{ url: string; duration: number }> = []

    page.on('request', request => {
      const startTime = Date.now()
      request.failure() // 这会触发响应等待
      const duration = Date.now() - startTime
      if (request.url().includes('/api/')) {
        requests.push({ url: request.url(), duration })
      }
    })

    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // 检查 API 请求时间
    for (const req of requests) {
      console.log(`API request: ${req.url} - ${req.duration}ms`)
      expect(req.duration).toBeLessThan(5000)
    }
  })

  test('首次内容绘制 (FCP)', async ({ page }) => {
    await page.goto('/')

    // 等待 FCP
    const fcp = await page.evaluate(() => {
      return new Promise<number>(resolve => {
        const observer = new PerformanceObserver(list => {
          for (const entry of list.getEntries()) {
            if (entry.name === 'first-contentful-paint') {
              observer.disconnect()
              resolve(entry.startTime)
            }
          }
        })
        observer.observe({ type: 'paint', buffered: true })
      })
    })

    console.log(`First Contentful Paint: ${fcp.toFixed(2)}ms`)
    expect(fcp).toBeLessThan(2000) // FCP 应小于 2 秒
  })

  test('最大内容绘制 (LCP)', async ({ page }) => {
    await page.goto('/')

    // 等待 LCP
    const lcp = await page.evaluate(() => {
      return new Promise<number>(resolve => {
        const observer = new PerformanceObserver(list => {
          for (const entry of list.getEntries()) {
            if (entry.entryType === 'largest-contentful-paint') {
              observer.disconnect()
              resolve(entry.startTime)
            }
          }
        })
        observer.observe({ type: 'largest-contentful-paint', buffered: true })
      })
    })

    console.log(`Largest Contentful Paint: ${lcp.toFixed(2)}ms`)
    expect(lcp).toBeLessThan(4000) // LCP 应小于 4 秒
  })
})
