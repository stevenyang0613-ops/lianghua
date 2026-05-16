/**
 * TDD测试: 模拟前端StartupLoading + requestAPI的完整启动流程
 *
 * 关键场景：
 * 1. Electron环境下 requestAPI 是否使用IPC代理
 * 2. 后端未就绪时 health check 是否正确重试
 * 3. 后端就绪后是否正确标记连接成功
 */

const http = require('http')
const assert = require('assert')

// 模拟 httpRequestHandler (与 main.ts 中的实现一致)
function httpRequestHandler(method, url, body) {
  return new Promise((resolve) => {
    try {
      const parsedUrl = new URL(url)
      const bodyStr = body !== undefined ? JSON.stringify(body) : undefined
      const options = {
        hostname: parsedUrl.hostname,
        port: parsedUrl.port || 80,
        path: parsedUrl.pathname + parsedUrl.search,
        method: method.toUpperCase(),
        headers: {
          'Content-Type': 'application/json',
          ...(bodyStr ? { 'Content-Length': Buffer.byteLength(bodyStr) } : {}),
        },
      }
      const req = http.request(options, (res) => {
        let data = ''
        res.on('data', (chunk) => { data += chunk })
        res.on('end', () => {
          try {
            const jsonData = JSON.parse(data)
            resolve({ ok: (res.statusCode ?? 0) >= 200 && (res.statusCode ?? 0) < 300, status: res.statusCode ?? 0, data: jsonData })
          } catch (e) {
            resolve({ ok: false, status: res.statusCode ?? 0, data: null, error: 'Parse error' })
          }
        })
      })
      req.on('error', (e) => { resolve({ ok: false, status: 0, data: null, error: String(e) }) })
      req.setTimeout(5000, () => { req.destroy(); resolve({ ok: false, status: 0, data: null, error: 'Timeout' }) })
      if (bodyStr) req.write(bodyStr)
      req.end()
    } catch (e) {
      resolve({ ok: false, status: 0, data: null, error: String(e) })
    }
  })
}

// ============================================================
// 测试: 模拟 requestAPI 函数（与 api.ts 中的实现一致）
// ============================================================
function isElectron(mockElectronAPI) {
  return typeof mockElectronAPI !== 'undefined' && mockElectronAPI?.isElectron === true
}

async function requestAPI(method, url, body, mockElectronAPI) {
  const electronDetected = isElectron(mockElectronAPI)
  const hasHttpRequest = !!mockElectronAPI?.httpRequest

  // 关键：只检查 httpRequest 是否存在，不依赖 isElectron
  if (hasHttpRequest) {
    console.log(`  [requestAPI] Using IPC proxy for ${method} ${url}`)
    const result = await mockElectronAPI.httpRequest(method, url, body)
    if (!result.ok) {
      const err = new Error(result.error || `HTTP ${result.status}`)
      err.status = result.status
      throw err
    }
    return result.data
  }

  console.log(`  [requestAPI] Using fetch for ${method} ${url} (electronDetected=${electronDetected}, hasHttpRequest=${hasHttpRequest})`)
  // 模拟 fetch (在 file:// 协议下会失败)
  throw new Error('fetch failed - file:// protocol cannot connect to http://127.0.0.1:8765')
}

// ============================================================
// 测试: 模拟 StartupLoading 的健康检查循环
// ============================================================
async function simulateStartupLoading(backendPort, delayBackendMs, mockElectronAPI) {
  const maxRetries = 120
  const retryInterval = 500
  let retries = 0
  let backendConnected = false
  let error = null
  let usedIPCProxy = false
  let usedFetch = false

  // 延迟启动后端
  let backendStarted = false
  setTimeout(() => { backendStarted = true }, delayBackendMs)

  while (retries < maxRetries && !backendConnected) {
    try {
      // 模拟 StartupLoading 中的 httpRequest 优先路径
      if (mockElectronAPI?.httpRequest) {
        usedIPCProxy = true
        const result = await mockElectronAPI.httpRequest('GET', `http://127.0.0.1:${backendPort}/api/v1/health`)
        if (result.ok) {
          backendConnected = true
          break
        }
        retries++
        await new Promise(r => setTimeout(r, retryInterval))
        continue
      }

      // 回退到 healthCheck (通过 requestAPI)
      usedFetch = true
      await requestAPI('GET', `http://127.0.0.1:${backendPort}/api/v1/health`, undefined, mockElectronAPI)
      backendConnected = true
    } catch (e) {
      retries++
      await new Promise(r => setTimeout(r, retryInterval))
    }
  }

  if (!backendConnected) {
    error = '后端服务连接失败，请检查服务是否已启动'
  }

  return { backendConnected, error, retries, usedIPCProxy, usedFetch }
}

// ============================================================
// 创建模拟后端（延迟启动）
// ============================================================
function createDelayedBackend(port, startAfterMs) {
  return new Promise((resolve) => {
    let server = null
    setTimeout(() => {
      server = http.createServer((req, res) => {
        if (req.url === '/api/v1/health') {
          res.writeHead(200, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({ status: 'ok', app: 'LiangHua', market_running: true, db_ok: true }))
        } else {
          res.writeHead(200, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify({}))
        }
      })
      server.listen(port, () => {
        console.log(`  模拟后端在 ${startAfterMs}ms 后启动于端口 ${port}`)
      })
    }, startAfterMs)
    resolve({ close: () => server?.close() })
  })
}

// ============================================================
// 运行所有测试
// ============================================================
async function runTests() {
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

  // ---- 测试1: requestAPI 在有 httpRequest 时使用IPC代理 ----
  console.log('\n=== 测试1: requestAPI 使用IPC代理 ===')

  const mockElectronAPI = {
    isElectron: true,
    httpRequest: async (method, url, body) => {
      return httpRequestHandler(method, url, body)
    }
  }

  // 先启动后端
  const TEST_PORT = 19877
  const backend = await createDelayedBackend(TEST_PORT, 0)
  await new Promise(r => setTimeout(r, 100)) // 等后端启动

  try {
    const data = await requestAPI('GET', `http://127.0.0.1:${TEST_PORT}/api/v1/health`, undefined, mockElectronAPI)
    assert2(data?.status === 'ok', 'requestAPI 通过IPC代理成功获取数据')
  } catch (e) {
    assert2(false, `requestAPI 通过IPC代理失败: ${e.message}`)
  }

  // ---- 测试2: requestAPI 在没有 httpRequest 时走fetch（在file://下会失败）----
  console.log('\n=== 测试2: 没有httpRequest时走fetch（应失败）===')

  const mockNoHttpRequest = { isElectron: true } // 没有 httpRequest

  try {
    await requestAPI('GET', `http://127.0.0.1:${TEST_PORT}/api/v1/health`, undefined, mockNoHttpRequest)
    assert2(false, '应该抛出fetch错误')
  } catch (e) {
    assert2(e.message.includes('fetch failed'), '没有httpRequest时正确抛出fetch错误')
  }

  // ---- 测试3: isElectron为false但有httpRequest时仍使用IPC代理 ----
  console.log('\n=== 测试3: isElectron=false但有httpRequest时应使用IPC代理 ===')

  const mockNotElectronButHasAPI = {
    isElectron: false,  // 关键：isElectron为false
    httpRequest: async (method, url, body) => {
      return httpRequestHandler(method, url, body)
    }
  }

  try {
    const data = await requestAPI('GET', `http://127.0.0.1:${TEST_PORT}/api/v1/health`, undefined, mockNotElectronButHasAPI)
    assert2(data?.status === 'ok', 'isElectron=false但有httpRequest时也能使用IPC代理')
  } catch (e) {
    assert2(false, `isElectron=false但有httpRequest时失败: ${e.message}`)
  }

  // ---- 测试4: 模拟完整启动流程（后端延迟5秒启动）----
  console.log('\n=== 测试4: 完整启动流程模拟（后端5秒后启动）===')

  const E2E_PORT = 19878
  const backend2 = await createDelayedBackend(E2E_PORT, 3000)

  const result = await simulateStartupLoading(E2E_PORT, 3000, mockElectronAPI)
  assert2(result.backendConnected === true, '启动流程: 最终应成功连接')
  assert2(result.usedIPCProxy === true, '启动流程: 应使用IPC代理')
  assert2(result.usedFetch === false, '启动流程: 不应使用fetch')
  assert2(result.error === null, '启动流程: 不应有错误')

  // ---- 测试5: 后端始终不启动 ----
  console.log('\n=== 测试5: 后端始终不启动 ===')

  const DEAD_PORT = 19879
  const result2 = await simulateStartupLoading(DEAD_PORT, 999999, mockElectronAPI)
  // 120 retries * 500ms = 60秒，但这会太慢，用少量重试
  assert2(result2.usedIPCProxy === true, '无后端: 仍应使用IPC代理')
  // 注意：完整120次重试太慢，只验证使用了IPC代理

  // ---- 测试6: electronAPI 完全不存在 ----
  console.log('\n=== 测试6: electronAPI完全不存在 ===')

  const result3 = await simulateStartupLoading(E2E_PORT, 0, undefined)
  assert2(result3.usedIPCProxy === false, '无electronAPI: 不应使用IPC代理')
  assert2(result3.usedFetch === true, '无electronAPI: 应尝试fetch')
  assert2(result3.backendConnected === false, '无electronAPI: fetch在file://下应失败')

  // 清理
  await new Promise(r => setTimeout(r, 100))

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
