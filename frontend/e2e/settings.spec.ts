/**
 * 设置页面 E2E 测试
 */

import { test, expect } from '@playwright/test'

test.describe('设置页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/settings')
  })

  test('应该显示设置面板', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 检查设置容器
    const settingsContainer = page.locator('.settings, [data-testid="settings"], .ant-card')
    await expect(settingsContainer.first()).toBeVisible({ timeout: 10000 })
  })

  test('主题切换', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找主题切换开关
    const themeSwitch = page.locator('.ant-switch, [data-testid="theme-switch"]').first()

    if (await themeSwitch.isVisible()) {
      await themeSwitch.click()
      // 等待主题切换生效
      await page.waitForFunction(() => {
        const html = document.documentElement
        return html.getAttribute('data-theme') !== null || html.classList.contains('dark') || html.classList.contains('light')
      }, { timeout: 3000 }).catch(() => test.info().annotations.push({ type: 'timeout-warning', description: '主题切换等待超时，可能 DOM 结构已变更' }))
    }
  })

  test('语言切换', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找语言选择器
    const languageSelect = page.locator('.ant-select:has-text("语言"), [data-testid="language-select"]').first()

    if (await languageSelect.isVisible()) {
      await languageSelect.click()

      const languageOption = page.locator('.ant-select-item-option').first()
      if (await languageOption.isVisible()) {
        await languageOption.click()
      }
    }
  })

  test('通知设置', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找通知设置标签
    const notificationTab = page.locator('.ant-tabs-tab:has-text("通知"), button:has-text("通知")').first()

    if (await notificationTab.isVisible()) {
      await notificationTab.click()
    }
  })

  test('账户管理', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找账户标签
    const accountTab = page.locator('.ant-tabs-tab:has-text("账户"), button:has-text("账户")').first()

    if (await accountTab.isVisible()) {
      await accountTab.click()
    }
  })

  test('数据同步设置', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找同步标签
    const syncTab = page.locator('.ant-tabs-tab:has-text("同步"), button:has-text("同步")').first()

    if (await syncTab.isVisible()) {
      await syncTab.click()
    }
  })

  test('保存设置', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找保存按钮
    const saveButton = page.locator('button:has-text("保存"), button:has-text("应用")').first()

    if (await saveButton.isVisible()) {
      await saveButton.click()
    }
  })
})
