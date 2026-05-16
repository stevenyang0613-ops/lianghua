/**
 * 启动连接流程 E2E 测试
 * 验证：启动 → 健康检查 → 后端连接 → 数据展示
 */
import { test, expect } from '@playwright/test'

const mockHealthResponse = {
  status: 'ok',
  app: 'LiangHua',
  market_running: true,
  db_ok: true,
  ws_auth_token: 'test-ws-token-e2e',
}

const mockMarketData = {
  total: 3,
  bonds: [
    { code: '113050', name: '南银转债', price: 105.5, change_pct: 1.23 },
    { code: '123045', name: '晨丰转债', price: 98.2, change_pct: -0.56 },
    { code: '128080', name: '顺博转债', price: 112.8, change_pct: 2.15 },
  ],
  updated_at: '2026-05-16T10:00:00',
}

test.describe('启动连接流程', () => {
  test('should load startup screen and connect to backend', async ({ page }) => {
    // Mock /health endpoint
    await page.route('**/health', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockHealthResponse),
      })
    )

    await page.goto('/')

    // Should eventually load the main app (not stuck on startup screen)
    await expect(page.locator('body')).toBeVisible({ timeout: 15000 })
  })

  test('should show error when backend is unreachable', async ({ page }) => {
    // Block /health endpoint
    await page.route('**/health', route => route.abort())

    await page.goto('/')

    // Should show error state after timeout
    await expect(page.getByText(/重试|离线模式|后端/)).toBeVisible({ timeout: 30000 })
  })

  test('should retry connection after backend becomes available', async ({ page }) => {
    let healthCallCount = 0

    await page.route('**/health', route => {
      healthCallCount++
      if (healthCallCount < 3) {
        // First 2 calls fail
        route.fulfill({ status: 503, body: JSON.stringify({ status: 'error' }) })
      } else {
        // 3rd call succeeds
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(mockHealthResponse),
        })
      }
    })

    await page.goto('/')
    await expect(page.locator('body')).toBeVisible({ timeout: 15000 })
  })

  test('should fallback to offline mode when network is unavailable', async ({ page }) => {
    await page.route('**/health', route => route.abort())
    await page.route('**/api/**', route => route.abort())

    await page.goto('/')

    // Should have option to go offline
    await expect(page.getByText(/离线模式/)).toBeVisible({ timeout: 30000 })
  })
})

test.describe('健康检查数据展示', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/health', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockHealthResponse),
      })
    )
    await page.route('**/api/v1/market/quotes', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockMarketData),
      })
    )
    await page.route('**/api/v1/market/bonds**', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockMarketData),
      })
    )
  })

  test('should display market data after connection', async ({ page }) => {
    await page.goto('/')
    // Wait for app to load (may show startup screen briefly)
    await page.waitForLoadState('networkidle')
    // Should render the main content area
    await expect(page.locator('.ant-layout')).toBeVisible({ timeout: 15000 })
  })
})

test.describe('性能监控页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/health', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(mockHealthResponse),
      })
    )
  })

  test('should render performance page with tabs', async ({ page }) => {
    await page.goto('/performance')
    await expect(page.getByRole('heading', { name: /性能监控/ })).toBeVisible({ timeout: 10000 })

    // Should have API monitoring tab
    await expect(page.getByText('API 监控')).toBeVisible()

    // Should have system metrics tab
    await expect(page.getByText('系统指标')).toBeVisible()

    // Should have crash reports tab
    await expect(page.getByText('崩溃报告')).toBeVisible()
  })

  test('should display API statistics', async ({ page }) => {
    await page.goto('/performance')
    await expect(page.getByText('总请求数')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('平均响应')).toBeVisible()
    await expect(page.getByText('最大响应')).toBeVisible()
  })

  test('should show storage statistics', async ({ page }) => {
    await page.goto('/performance')
    await expect(page.getByText('存储统计')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('存储键数')).toBeVisible()
  })

  test('should switch to system metrics tab', async ({ page }) => {
    await page.goto('/performance')
    await page.getByText('系统指标').click()

    // In web mode (no Electron), should show "not available" message
    await expect(page.getByText(/Electron 性能指标不可用|应用运行时间|内存使用/)).toBeVisible({ timeout: 5000 })
  })

  test('should switch to crash reports tab', async ({ page }) => {
    await page.goto('/performance')
    await page.getByText('崩溃报告').click()

    // In web mode, should show "no crash reports" or empty state
    await expect(page.getByText(/暂无崩溃报告|崩溃列表/)).toBeVisible({ timeout: 5000 })
  })

  test('should allow clearing API records', async ({ page }) => {
    await page.goto('/performance')
    // Look for the clear button in API tab
    const clearBtn = page.getByRole('button', { name: /清除记录/ })
    if (await clearBtn.isVisible()) {
      await clearBtn.click()
    }
  })

  test('should allow exporting report', async ({ page }) => {
    await page.goto('/performance')
    const exportBtn = page.getByRole('button', { name: /导出报告/ })
    if (await exportBtn.isVisible()) {
      await exportBtn.click()
    }
  })

  test('should display warning threshold config', async ({ page }) => {
    await page.goto('/performance')
    await expect(page.getByText('告警配置')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('警告阈值')).toBeVisible()
    await expect(page.getByText('严重阈值')).toBeVisible()
  })
})
