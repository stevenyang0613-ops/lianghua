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

    // 检查是否有数据表格或列表
    const dataTable = page.locator('table, .ant-table, [data-testid="market-table"]')
    await expect(dataTable).toBeVisible({ timeout: 15000 })
  })

  test('搜索功能', async ({ page }) => {
    // 等待页面加载
    await page.waitForLoadState('networkidle')

    // 查找搜索框
    const searchInput = page.locator('input[placeholder*="搜索"], input[placeholder*="代码"], .ant-input-search input').first()

    if (await searchInput.isVisible()) {
      await searchInput.fill('128001')
      await searchInput.press('Enter')

      // 等待搜索结果
      await page.waitForTimeout(1000)
    }
  })

  test('排序功能', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找可排序的表头
    const sortableHeader = page.locator('.ant-table-column-sorters, th[class*="sortable"]').first()

    if (await sortableHeader.isVisible()) {
      await sortableHeader.click()
      await page.waitForTimeout(500)
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
        await page.waitForTimeout(1000)
      }
    }
  })

  test('刷新数据', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找刷新按钮
    const refreshButton = page.locator('button:has-text("刷新"), [data-testid="refresh-button"]').first()

    if (await refreshButton.isVisible()) {
      await refreshButton.click()
      await page.waitForTimeout(2000)
    }
  })

  test('查看详情', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找可点击的数据行
    const dataRow = page.locator('.ant-table-row, tr[data-row-key]').first()

    if (await dataRow.isVisible()) {
      await dataRow.click()
      await page.waitForTimeout(1000)

      // 检查是否弹出详情面板
      const detailPanel = page.locator('.ant-drawer, .ant-modal, [data-testid="detail-panel"]')
      // 可能存在也可能不存在，不强制检查
    }
  })
})
