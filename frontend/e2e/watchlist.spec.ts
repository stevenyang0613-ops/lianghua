/**
 * 自选页面 E2E 测试
 */

import { test, expect } from '@playwright/test'

test.describe('自选页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/watchlist')
  })

  test('应该显示自选列表', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 检查自选列表容器
    const watchlistContainer = page.locator('.watchlist, [data-testid="watchlist"], .ant-list, table')
    await expect(watchlistContainer.first()).toBeVisible({ timeout: 10000 })
  })

  test('添加自选', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找添加按钮
    const addButton = page.locator('button:has-text("添加"), [data-testid="add-watchlist"]').first()

    if (await addButton.isVisible()) {
      await addButton.click()

      // 填写标的代码
      const codeInput = page.locator('input[placeholder*="代码"], input[name="code"]').first()
      if (await codeInput.isVisible()) {
        await codeInput.fill('128001')

        const confirmButton = page.locator('button:has-text("确定"), button[type="submit"]').first()
        await confirmButton.click()
      }
    }
  })

  test('删除自选', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找删除按钮
    const deleteButton = page.locator('button:has-text("删除"), [data-testid="delete-button"], .anticon-delete').first()

    if (await deleteButton.isVisible()) {
      await deleteButton.click()

      // 确认删除
      const confirmButton = page.locator('.ant-modal button:has-text("确定")').first()
      if (await confirmButton.isVisible()) {
        await confirmButton.click()
      }
    }
  })

  test('分组管理', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找分组标签
    const groupTabs = page.locator('.ant-tabs-tab, [data-testid="group-tab"]')

    if (await groupTabs.first().isVisible()) {
      await groupTabs.first().click()
    }
  })
})
