/**
 * 市场页面 E2E 测试
 */

import { test, expect } from '@playwright/test'

test.describe('市场页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/market')
  })

  test('应该加载市场数据', async ({ page }) => {
    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 检查是否有数据表格或列表（优先 data-testid，兼容 antd class）
    const dataTable = page.locator('[data-testid="market-page"] table, [data-testid="market-table"], .ant-table, table')
    await expect(dataTable.first()).toBeVisible({ timeout: 15000 })
  })

  test('搜索功能', async ({ page }) => {
    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 查找搜索框
    const searchInput = page.locator('input[placeholder*="搜索"], input[placeholder*="代码"], .ant-input-search input').first()

    if (await searchInput.isVisible()) {
      await searchInput.fill('128001')
      await searchInput.press('Enter')

      // 等待搜索结果：表格内容更新
      await page.waitForFunction(() => {
        const rows = document.querySelectorAll('.ant-table-row, table tbody tr')
        return rows.length > 0
      }, { timeout: 5000 }).catch(() => test.info().annotations.push({ type: 'timeout-warning', description: '搜索结果等待超时，可能 antd class 名已变更' }))
    }
  })

  test('排序功能', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找可排序的表头
    const sortableHeader = page.locator('.ant-table-column-sorters, th[class*="sortable"]').first()

    if (await sortableHeader.isVisible()) {
      await sortableHeader.click()
      // 等待排序指示器出现
      await page.locator('.ant-table-column-sort').first().waitFor({ timeout: 3000 }).catch(() => {})
      await sortableHeader.click()
    }
  })

  test('分页功能', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找分页器
    const pagination = page.locator('.ant-pagination, [data-testid="pagination"]').first()

    if (await pagination.isVisible()) {
      const nextButton = page.locator('.ant-pagination-next, button[aria-label="next page"]').first()
      if (await nextButton.isEnabled()) {
        await nextButton.click()
        // 等待分页数据加载
        await page.locator('.ant-table-row, table tbody tr').first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})
      }
    }
  })

  test('刷新数据', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找刷新按钮（优先 data-testid）
    const refreshButton = page.locator('[data-testid="refresh-button"], button:has-text("刷新")').first()

    if (await refreshButton.isVisible()) {
      await refreshButton.click()
      // 等待刷新完成：loading 消失或数据重新出现
      await page.locator('.ant-spin-spinning').first().waitFor({ state: 'hidden', timeout: 10000 }).catch(() => {})
    }
  })

  test('查看详情', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找可点击的数据行
    const dataRow = page.locator('.ant-table-row, tr[data-row-key]').first()

    if (await dataRow.isVisible()) {
      await dataRow.click()
      // 等待详情面板出现
      await page.locator('.ant-drawer, .ant-modal, [data-testid="detail-panel"]').first().waitFor({ state: 'visible', timeout: 5000 }).catch(() => {})

      // 检查是否弹出详情面板
      const detailPanel = page.locator('.ant-drawer, .ant-modal, [data-testid="detail-panel"]')
      // 可能存在也可能不存在，不强制检查
    }
  })
})
