/**
 * 交易页面 E2E 测试
 */

import { test, expect } from '@playwright/test'

test.describe('交易页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/trade')
  })

  test('应该显示交易面板', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 检查交易相关元素
    const tradePanel = page.locator('.trade-panel, [data-testid="trade-panel"], .ant-card')
    await expect(tradePanel.first()).toBeVisible({ timeout: 10000 })
  })

  test('下单流程 - 买入', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找买入按钮
    const buyButton = page.locator('button:has-text("买入"), [data-testid="buy-button"]').first()

    if (await buyButton.isVisible()) {
      // 填写代码
      const codeInput = page.locator('input[placeholder*="代码"], input[name="code"]').first()
      if (await codeInput.isVisible()) {
        await codeInput.fill('128001')
      }

      // 填写价格
      const priceInput = page.locator('input[placeholder*="价格"], input[name="price"]').first()
      if (await priceInput.isVisible()) {
        await priceInput.fill('100.50')
      }

      // 填写数量
      const quantityInput = page.locator('input[placeholder*="数量"], input[name="quantity"]').first()
      if (await quantityInput.isVisible()) {
        await quantityInput.fill('100')
      }

      // 点击买入
      await buyButton.click()

      // 确认订单
      const confirmButton = page.locator('.ant-modal button:has-text("确认")').first()
      if (await confirmButton.isVisible()) {
        await confirmButton.click()
      }
    }
  })

  test('下单流程 - 卖出', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找卖出按钮
    const sellButton = page.locator('button:has-text("卖出"), [data-testid="sell-button"]').first()

    if (await sellButton.isVisible()) {
      await sellButton.click()
    }
  })

  test('查看持仓', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找持仓标签
    const positionTab = page.locator('.ant-tabs-tab:has-text("持仓"), button:has-text("持仓")').first()

    if (await positionTab.isVisible()) {
      await positionTab.click()
    }
  })

  test('查看委托', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找委托标签
    const orderTab = page.locator('.ant-tabs-tab:has-text("委托"), button:has-text("委托")').first()

    if (await orderTab.isVisible()) {
      await orderTab.click()
    }
  })

  test('撤单', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找撤单按钮
    const cancelButton = page.locator('button:has-text("撤单"), [data-testid="cancel-order"]').first()

    if (await cancelButton.isVisible()) {
      await cancelButton.click()
    }
  })
})
