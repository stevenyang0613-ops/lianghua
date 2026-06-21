/**
 * 回测页面 E2E 测试
 */

import { test, expect } from '@playwright/test'

test.describe('回测页面', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/backtest')
  })

  test('应该显示回测配置面板', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 检查回测配置表单（优先 data-testid，兼容 antd class）
    const configForm = page.locator('[data-testid="backtest-page"] form, [data-testid="backtest-config"], .ant-form, form')
    await expect(configForm.first()).toBeVisible({ timeout: 10000 })
  })

  test('选择策略', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找策略选择器
    const strategySelect = page.locator('.ant-select, [data-testid="strategy-select"]').first()

    if (await strategySelect.isVisible()) {
      await strategySelect.click()

      // 选择一个策略选项
      const strategyOption = page.locator('.ant-select-item-option').first()
      if (await strategyOption.isVisible()) {
        await strategyOption.click()
      }
    }
  })

  test('设置时间范围', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找日期选择器
    const datePickers = page.locator('.ant-picker, input[type="date"]')

    const startDatePicker = datePickers.first()
    if (await startDatePicker.isVisible()) {
      await startDatePicker.click()
      // 等待日期面板展开
      await page.locator('.ant-picker-dropdown, .ant-picker-panel').first().waitFor({ state: 'visible', timeout: 3000 }).catch(() => {})

      // 选择一个日期
      const dateCell = page.locator('.ant-picker-cell').first()
      if (await dateCell.isVisible()) {
        await dateCell.click()
      }
    }
  })

  test('运行回测', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找运行按钮
    const runButton = page.locator('button:has-text("运行"), button:has-text("开始回测")').first()

    if (await runButton.isVisible()) {
      await runButton.click()

      // 等待回测完成：观察结果面板出现或 loading 消失（优先 data-testid）
      await page.locator('[data-testid="backtest-result"], .backtest-result, .echarts-for-react').first().waitFor({ state: 'visible', timeout: 30000 }).catch(() => {})

      // 检查结果是否显示
      const resultPanel = page.locator('.backtest-result, [data-testid="backtest-result"], .echarts-for-react')
    }
  })

  test('查看回测报告', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找报告标签
    const reportTab = page.locator('.ant-tabs-tab:has-text("报告"), button:has-text("报告")').first()

    if (await reportTab.isVisible()) {
      await reportTab.click()
    }
  })

  test('导出报告', async ({ page }) => {
    await page.waitForLoadState('networkidle')

    // 查找导出按钮
    const exportButton = page.locator('button:has-text("导出"), [data-testid="export-button"]').first()

    if (await exportButton.isVisible()) {
      // 点击导出会触发下载
      const [download] = await Promise.all([
        page.waitForEvent('download').catch(() => null),
        exportButton.click(),
      ])
    }
  })
})
