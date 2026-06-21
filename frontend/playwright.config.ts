import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright E2E 测试配置
 *
 * 使用方式：
 *   npx playwright test            — 运行所有 E2E 测试
 *   npx playwright test --ui       — 可视化调试
 *   npx playwright test -g "侧栏"  — 按名称过滤
 *   E2E_BASE_URL=http://host npx playwright test — 指定后端地址
 *
 * 前置条件：
 *   - 后端已启动（localhost:8765）
 *   - 前端 dev server 已启动（localhost:5173）或由 webServer 自动启动
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // 串行执行，避免后端 API 并发冲突
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: process.env.CI
    ? [['github'], ['html', { open: 'never' }]]
    : [['list'], ['html', { open: 'on-failure' }]],
  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    // 无状态 UI 测试：auth 和 settings 互不依赖，各自可并行
    {
      name: 'ui-auth',
      testDir: './e2e',
      testMatch: /auth\.spec\.ts/,
      fullyParallel: true,
      workers: process.env.CI ? 1 : 2,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'ui-settings',
      testDir: './e2e',
      testMatch: /settings\.spec\.ts/,
      fullyParallel: true,
      workers: process.env.CI ? 1 : 2,
      use: { ...devices['Desktop Chrome'] },
    },
    // 有状态集成测试：依赖后端数据，串行执行避免冲突
    {
      name: 'integration',
      testDir: './e2e',
      testIgnore: /.*(settings|auth)\.spec\.ts/,
      fullyParallel: false,
      workers: 1,
      use: { ...devices['Desktop Chrome'] },
    },
    // 移动端按需启用（CI 环境下跳过以减少运行时间）
    ...(!process.env.CI ? [
      {
        name: 'Mobile Chrome',
        testDir: './e2e',
        testMatch: /.*(settings|auth)\.spec\.ts/,
        fullyParallel: true,
        workers: 2,
        use: { ...devices['Pixel 5'] },
      },
    ] : []),
  ],

  // 自动启动前端 dev server（仅当 E2E_BASE_URL 未设置时）
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: 'npm run dev',
        url: 'http://localhost:5173',
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
})
