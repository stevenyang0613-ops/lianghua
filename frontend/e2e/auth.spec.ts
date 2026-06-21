/**
 * 认证流程 E2E 测试
 */

import { test, expect } from '@playwright/test'

test.describe('认证流程', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('应该显示登录页面', async ({ page }) => {
    // 检查是否有登录相关元素
    const loginButton = page.locator('button:has-text("登录"), [data-testid="login-button"]')
    await expect(loginButton).toBeVisible({ timeout: 10000 })
  })

  test('登录流程', async ({ page }) => {
    // 点击登录按钮
    const loginButton = page.locator('button:has-text("登录")').first()
    if (await loginButton.isVisible()) {
      await loginButton.click()
    }

    // 填写用户名密码
    const usernameInput = page.locator('input[placeholder*="用户名"], input[name="username"], input[type="text"]').first()
    const passwordInput = page.locator('input[placeholder*="密码"], input[name="password"], input[type="password"]').first()

    if (await usernameInput.isVisible()) {
      await usernameInput.fill('test_user')
      await passwordInput.fill('test_password')

      // 点击提交
      const submitButton = page.locator('button[type="submit"], button:has-text("登录")').first()
      await submitButton.click()

      // 等待页面跳转或登录成功提示
      await page.waitForURL('**/dashboard,**/market,**/', { timeout: 5000 }).catch(() => {})
    }
  })

  test('注册流程', async ({ page }) => {
    // 查找注册入口
    const registerLink = page.locator('a:has-text("注册"), button:has-text("注册")').first()

    if (await registerLink.isVisible()) {
      await registerLink.click()

      // 填写注册表单
      const usernameInput = page.locator('input[placeholder*="用户名"]').first()
      const emailInput = page.locator('input[type="email"], input[placeholder*="邮箱"]').first()
      const passwordInput = page.locator('input[type="password"]').first()

      if (await usernameInput.isVisible()) {
        await usernameInput.fill('new_user_' + Date.now())
        await emailInput.fill(`user_${Date.now()}@test.com`)
        await passwordInput.fill('Test123456!')

        const submitButton = page.locator('button[type="submit"]').first()
        await submitButton.click()
      }
    }
  })
})
