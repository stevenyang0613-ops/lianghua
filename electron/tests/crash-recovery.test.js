/**
 * TDD测试: Electron 应用崩溃恢复
 * 1. 后端崩溃后自动重启
 * 2. 健康检查失败后触发重启
 * 3. 重启次数限制
 * 4. 后端启动超时处理
 */

const http = require('http')
const assert = require('assert')

const PASS = '\x1b[32mPASS\x1b[0m'
const FAIL = '\x1b[31mFAIL\x1b[0m'
let passed = 0
let failed = 0

function assert2(condition, name) {
  if (condition) {
    console.log(`  ${PASS} ${name}`)
    passed++
  } else {
    console.log(`  ${FAIL} ${name}`)
    failed++
  }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }

// 模拟后端进程管理器（与 main.ts 中的逻辑一致）
class BackendProcessManager {
  constructor() {
    this.restartAttempts = 0
    this.maxRestartAttempts = 5
    this.isQuitting = false
    this.healthcheckFailCount = 0
    this.healthcheckMaxFails = 3
    this.backendRunning = false
    this.restartLog = []
  }

  // 模拟启动后端
  async startBackend() {
    if (this.restartAttempts >= this.maxRestartAttempts) {
      this.restartLog.push('max_retries_exceeded')
      return false
    }
    this.restartAttempts++
    this.restartLog.push(`start_attempt_${this.restartAttempts}`)
    this.backendRunning = true
    return true
  }

  // 模拟后端崩溃
  crashBackend() {
    this.backendRunning = false
    this.restartLog.push('backend_crashed')
  }

  // 模拟健康检查
  healthcheck() {
    return this.backendRunning
  }

  // 模拟健康检查循环
  async runHealthcheckOnce() {
    if (!this.healthcheck()) {
      this.healthcheckFailCount++
      if (this.healthcheckFailCount >= this.healthcheckMaxFails) {
        this.restartLog.push('healthcheck_triggered_restart')
        this.healthcheckFailCount = 0
        return this.restartBackend()
      }
    } else {
      this.healthcheckFailCount = 0
    }
    return true
  }

  // 模拟重启后端
  async restartBackend() {
    this.restartAttempts = 0
    this.backendRunning = false
    return this.startBackend()
  }

  // 模拟等待后端就绪
  async waitForBackend(maxWaitMs = 30000, intervalMs = 500) {
    const start = Date.now()
    while (Date.now() - start < maxWaitMs) {
      if (this.healthcheck()) return true
      await sleep(intervalMs)
    }
    return false
  }
}

async function runTests() {
  // ---- 测试1: 后端正常启动 ----
  console.log('\n=== 测试1: 后端正常启动 ===')

  const mgr = new BackendProcessManager()
  const started = await mgr.startBackend()
  assert2(started === true, '后端启动成功')
  assert2(mgr.restartAttempts === 1, '重启计数为1')
  assert2(mgr.healthcheck() === true, '健康检查通过')

  // ---- 测试2: 后端崩溃后健康检查触发重启 ----
  console.log('\n=== 测试2: 后端崩溃后自动重启 ===')

  mgr.crashBackend()
  assert2(mgr.healthcheck() === false, '崩溃后健康检查失败')

  // 连续3次健康检查失败后触发重启
  await mgr.runHealthcheckOnce() // fail 1
  await mgr.runHealthcheckOnce() // fail 2
  const result = await mgr.runHealthcheckOnce() // fail 3 -> restart
  assert2(result === true, '健康检查失败3次后自动重启成功')
  assert2(mgr.healthcheck() === true, '重启后健康检查通过')

  // ---- 测试3: 最大重启次数限制 ----
  console.log('\n=== 测试3: 最大重启次数限制 ===')

  const mgr2 = new BackendProcessManager()
  mgr2.maxRestartAttempts = 3

  // 连续启动3次
  await mgr2.startBackend()
  await mgr2.startBackend()
  await mgr2.startBackend()

  // 第4次应失败
  const overLimit = await mgr2.startBackend()
  assert2(overLimit === false, '超过最大重启次数后返回失败')
  assert2(mgr2.restartAttempts === 3, '重启次数保持在限制值')

  // ---- 测试4: 健康检查通过时重置失败计数 ----
  console.log('\n=== 测试4: 健康检查通过重置失败计数 ===')

  const mgr3 = new BackendProcessManager()
  await mgr3.startBackend()

  // 2次失败
  mgr3.crashBackend()
  await mgr3.runHealthcheckOnce()
  await mgr3.runHealthcheckOnce()
  assert2(mgr3.healthcheckFailCount === 2, '失败计数为2')

  // 恢复后端
  mgr3.backendRunning = true
  await mgr3.runHealthcheckOnce()
  assert2(mgr3.healthcheckFailCount === 0, '恢复后失败计数重置为0')

  // 再崩溃，需要重新累计3次
  mgr3.crashBackend()
  await mgr3.runHealthcheckOnce()
  await mgr3.runHealthcheckOnce()
  assert2(mgr3.healthcheckFailCount === 2, '重新计数：失败2次')

  // ---- 测试5: 重启后重置重启计数 ----
  console.log('\n=== 测试5: restartBackend 重置重启计数 ===')

  const mgr4 = new BackendProcessManager()
  await mgr4.startBackend()
  await mgr4.startBackend()
  assert2(mgr4.restartAttempts === 2, '重启前计数为2')

  await mgr4.restartBackend()
  assert2(mgr4.restartAttempts === 1, 'restartBackend 后计数重置为1')

  // ---- 测试6: waitForBackend 超时 ----
  console.log('\n=== 测试6: waitForBackend 超时处理 ===')

  const mgr5 = new BackendProcessManager()
  mgr5.backendRunning = false
  const waitResult = await mgr5.waitForBackend(1000, 200)
  assert2(waitResult === false, '后端不启动时 waitForBackend 超时返回 false')

  // ---- 测试7: waitForBackend 后端就绪 ----
  console.log('\n=== 测试7: waitForBackend 后端就绪 ===')

  const mgr6 = new BackendProcessManager()
  mgr6.backendRunning = false

  // 异步启动后端
  setTimeout(() => { mgr6.backendRunning = true }, 300)
  const waitResult2 = await mgr6.waitForBackend(5000, 200)
  assert2(waitResult2 === true, '后端启动后 waitForBackend 返回 true')

  // ---- 测试8: HTTP 健康检查实际调用 ----
  console.log('\n=== 测试8: HTTP 健康检查实际调用 ===')

  // 创建临时 HTTP 服务器
  const server = http.createServer((req, res) => {
    if (req.url === '/health') {
      res.writeHead(200, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ status: 'ok', app: 'LiangHua', market_running: true, db_ok: true, ws_auth_token: 'test-token-123' }))
    } else {
      res.writeHead(404)
      res.end()
    }
  })

  await new Promise(r => server.listen(19883, r))

  const healthResult = await new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:19883/health', (res) => {
      let data = ''
      res.on('data', chunk => data += chunk)
      res.on('end', () => {
        try {
          resolve({ ok: res.statusCode === 200, data: JSON.parse(data) })
        } catch {
          resolve({ ok: false, data: null })
        }
      })
    })
    req.on('error', () => resolve({ ok: false, data: null }))
    req.setTimeout(2000, () => { req.destroy(); resolve({ ok: false, data: null }) })
  })

  assert2(healthResult.ok === true, 'HTTP 健康检查成功')
  assert2(healthResult.data?.status === 'ok', '返回 status=ok')
  assert2(healthResult.data?.ws_auth_token !== undefined, '返回 ws_auth_token')

  // 测试后端未就绪
  await new Promise(r => server.close(r))

  const deadResult = await new Promise((resolve) => {
    const req = http.get('http://127.0.0.1:19883/health', (res) => {
      resolve({ ok: true })
    })
    req.on('error', () => resolve({ ok: false }))
    req.setTimeout(1000, () => { req.destroy(); resolve({ ok: false }) })
  })

  assert2(deadResult.ok === false, '后端关闭后健康检查返回失败')

  // 总结
  console.log(`\n${'='.repeat(50)}`)
  console.log(`结果: ${passed} 通过, ${failed} 失败, ${passed + failed} 总计`)
  if (failed > 0) {
    console.log('\x1b[31m存在失败测试！\x1b[0m')
    process.exit(1)
  } else {
    console.log('\x1b[32m所有测试通过！\x1b[0m')
  }
}

runTests().catch(e => {
  console.error('测试执行错误:', e)
  process.exit(1)
})
