import { test, expect } from '@playwright/test'

const mockHealth = (page: any) =>
  page.route('**/health', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'ok', app: 'LiangHua', market_running: true }),
    })
  )

test.describe('App initial load', () => {
  test('should render the page title', async ({ page }) => {
    await page.goto('/')
    await expect(page).toHaveTitle(/LiangHua/)
  })

  test('should show status bar with version info', async ({ page }) => {
    await mockHealth(page)
    await page.goto('/')
    await expect(page.getByText('LiangHua v0.1.0')).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('数据源: AKShare')).toBeVisible()
  })

  test('should show backend connection status', async ({ page }) => {
    await mockHealth(page)
    await page.goto('/')
    const statusEl = page.locator('.ant-tag')
    await expect(statusEl.first()).toBeVisible({ timeout: 10000 })
  })
})

test.describe('Sidebar navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockHealth(page)
  })

  test('should display all menu items', async ({ page }) => {
    await page.goto('/')
    const menu = page.getByRole('menu')
    await expect(menu.getByText('实时行情')).toBeVisible({ timeout: 10000 })
    await expect(menu.getByText('自选列表')).toBeVisible()
    await expect(menu.getByText('交易信号')).toBeVisible()
    await expect(menu.getByText('回测中心')).toBeVisible()
    await expect(menu.getByText('交易终端')).toBeVisible()
    await expect(menu.getByText('分析工具')).toBeVisible()
    await expect(menu.getByText('策略管理')).toBeVisible()
    await expect(menu.getByText('系统设置')).toBeVisible()
  })

  test('should navigate to trade page when clicking trade menu item', async ({ page }) => {
    await page.goto('/')
    await page.getByText('交易终端').click()
    await expect(page).toHaveURL(/\/trade/)
  })

  test('should navigate to backtest page when clicking backtest menu item', async ({ page }) => {
    await page.goto('/')
    await page.getByText('回测中心').click()
    await expect(page).toHaveURL(/\/backtest/)
  })

  test('should navigate to settings page when clicking settings menu item', async ({ page }) => {
    await page.goto('/')
    await page.getByText('系统设置').click()
    await expect(page).toHaveURL(/\/settings/)
  })

  test('should navigate to signals page when clicking signals menu item', async ({ page }) => {
    await page.goto('/')
    await page.getByText('交易信号').click()
    await expect(page).toHaveURL(/\/signals/)
  })

  test('should navigate to analysis page when clicking analysis menu item', async ({ page }) => {
    await page.goto('/')
    await page.getByText('分析工具').click()
    await expect(page).toHaveURL(/\/analysis/)
  })

  test('should navigate to watchlist page when clicking watchlist menu item', async ({ page }) => {
    await page.goto('/')
    await page.getByText('自选列表').click()
    await expect(page).toHaveURL(/\/watchlist/)
  })

  test('should navigate to strategies page when clicking strategies menu item', async ({ page }) => {
    await page.goto('/')
    await page.getByText('策略管理').click()
    await expect(page).toHaveURL(/\/strategies/)
  })
})

test.describe('Theme toggle', () => {
  test('should open theme options on click', async ({ page }) => {
    await mockHealth(page)
    await page.goto('/')
    await page.locator('button').filter({ has: page.locator('[class*="anticon-sun"], [class*="anticon-moon"], [class*="anticon-desktop"]') }).click()
    await expect(page.getByText('浅色')).toBeVisible({ timeout: 5000 })
    await expect(page.getByText('深色')).toBeVisible()
    await expect(page.getByText('跟随系统')).toBeVisible()
  })
})

test.describe('Settings page', () => {
  test.beforeEach(async ({ page }) => {
    await mockHealth(page)
  })

  test('should display settings page with all sections', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByRole('heading', { name: '系统设置' })).toBeVisible({ timeout: 10000 })
    await expect(page.getByText('用户管理')).toBeVisible()
    await expect(page.getByText('显示设置')).toBeVisible()
    await expect(page.getByText('网络设置')).toBeVisible()
    await expect(page.getByText('缓存管理')).toBeVisible()
    await expect(page.locator('.ant-card-head-title').filter({ hasText: '性能监控' })).toBeVisible()
    await expect(page.getByText('启动设置')).toBeVisible()
    await expect(page.getByText('信号配置')).toBeVisible()
    await expect(page.getByText('通知设置')).toBeVisible()
    await expect(page.getByText('日志查看器')).toBeVisible()
  })

  test('should switch theme to dark mode', async ({ page }) => {
    await page.goto('/settings')
    // The theme selector is an antd Select - click the selector
    await page.locator('.ant-select-selector').first().click()
    // Select dark mode from dropdown - it renders as a popup
    await page.locator('.ant-select-item-option').filter({ hasText: '深色' }).click()
    // Verify the select displays dark mode (there may still be sidebar menu text)
    await expect(page.locator('.ant-select-selection-item').filter({ hasText: '深色' }).first()).toBeVisible()
  })

  test('should toggle offline mode', async ({ page }) => {
    await page.goto('/settings')
    // Find the switch near '离线模式' by finding its containing card section
    const offlineCard = page.getByText('离线模式').locator('xpath=../..')
    const offlineSwitch = offlineCard.locator('.ant-switch')
    await offlineSwitch.click()
    await expect(page.getByText('已启用离线模式')).toBeVisible()
  })

  test('should create a new user', async ({ page }) => {
    await page.goto('/settings')
    await page.getByText('添加用户').click()
    await expect(page.getByText('创建新用户')).toBeVisible()
    await page.getByPlaceholder('请输入用户名').fill('测试用户')
    // Click the modal footer '创建' button
    await page.locator('.ant-modal-footer .ant-btn-primary').click()
    await expect(page.getByText('测试用户')).toBeVisible()
  })

  test('should show cache management stats', async ({ page }) => {
    await page.goto('/settings')
    await expect(page.getByText('缓存条目')).toBeVisible()
    await expect(page.getByText('清除过期缓存')).toBeVisible()
    await expect(page.getByText('清除全部缓存')).toBeVisible()
  })

  test('should toggle auto sync', async ({ page }) => {
    await page.goto('/settings')
    // Find the auto sync switch in its card
    const syncText = page.getByText('自动后台同步')
    await expect(syncText).toBeVisible()
    const syncCard = syncText.locator('xpath=../..')
    const syncSwitch = syncCard.locator('.ant-switch')
    await syncSwitch.click()
    await expect(page.getByText('已开启自动同步')).toBeVisible()
    // Toggle back off
    await syncSwitch.click()
    await expect(page.getByText('已关闭自动同步')).toBeVisible()
  })

  test('should show log viewer modal', async ({ page }) => {
    await page.goto('/settings')
    await page.getByText('查看日志').click()
    await expect(page.getByText('应用日志')).toBeVisible()
    // '关闭' button is in modal footer with type="primary"
    await expect(page.locator('.ant-modal-footer .ant-btn-primary')).toBeVisible()
    await page.locator('.ant-modal-footer .ant-btn-primary').click()
  })
})

test.describe('Page rendering', () => {
  test.beforeEach(async ({ page }) => {
    await mockHealth(page)
  })

  test('should render signals page', async ({ page }) => {
    await page.goto('/signals')
    await expect(page.getByRole('heading', { name: '交易信号' })).toBeVisible({ timeout: 10000 })
  })

  test('should render analysis page', async ({ page }) => {
    await page.goto('/analysis')
    await expect(page.getByRole('heading', { name: /分析工具/ })).toBeVisible({ timeout: 10000 })
  })

  test('should render watchlist page', async ({ page }) => {
    await page.goto('/watchlist')
    await expect(page.getByRole('heading', { name: '自选列表' })).toBeVisible({ timeout: 10000 })
  })

  test('should render strategies page', async ({ page }) => {
    await page.goto('/strategies')
    await expect(page.getByRole('heading', { name: /策略管理/ })).toBeVisible({ timeout: 10000 })
  })

  test('should render trade page', async ({ page }) => {
    await page.goto('/trade')
    await expect(page.getByRole('heading', { name: '交易终端' })).toBeVisible({ timeout: 10000 })
  })

  test('should render backtest page', async ({ page }) => {
    await page.goto('/backtest')
    await expect(page.getByRole('heading', { name: '回测中心' })).toBeVisible({ timeout: 10000 })
  })
})
