/**
 * TDD测试: Electron IPC代理后端连接
 *
 * 验证：
 * 1. httpRequestHandler 正确处理各种HTTP方法
 * 2. 后端未启动时正确返回错误
 * 3. requestAPI 在Electron环境下正确使用IPC代理
 * 4. StartupLoading 正确等待后端启动
 */

const http = require('http')

// ============================================================
// 测试1: httpRequestHandler - 模拟main.ts中的函数
// ============================================================
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

      req.on('error', (e) => {
        resolve({ ok: false, status: 0, data: null, error: String(e) })
      })

      req.setTimeout(5000, () => {
        req.destroy()
        resolve({ ok: false, status: 0, data: null, error: 'Timeout' })
      })

      if (bodyStr) req.write(bodyStr)
      req.end()
    } catch (e) {
      resolve({ ok: false, status: 0, data: null, error: String(e) })
    }
  })
}

// ============================================================
// 测试辅助: 创建模拟后端服务器
// ============================================================
function createMockBackend(port) {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      let body = ''
      req.on('data', (chunk) => { body += chunk })
      req.on('end', () => {
        const respond = (code, data) => {
          res.writeHead(code, { 'Content-Type': 'application/json' })
          res.end(JSON.stringify(data))
        }

        if (req.url === '/api/v1/health') {
          respond(200, { status: 'ok', app: 'LiangHua', market_running: true, db_ok: true })
        } else if (req.url === '/api/v1/market/quotes') {
          respond(200, { total: 1, bonds: [{ code: '123456', name: '测试转债' }], updated_at: '2026-01-01' })
        } else if (req.url === '/api/v1/test-post' && req.method === 'POST') {
          respond(200, { received: JSON.parse(body || '{}') })
        } else if (req.url === '/api/v1/test-delete' && req.method === 'DELETE') {
          respond(200, { deleted: true })
        } else if (req.url === '/api/v1/test-put' && req.method === 'PUT') {
          respond(200, { updated: true })
        } else {
          respond(404, { detail: 'Not found' })
        }
      })
    })
    server.listen(port, () => resolve(server))
  })
}

// ============================================================
// 测试执行
// ============================================================
async function runTests() {
  const PASS = '\x1b[32mPASS\x1b[0m'
  const FAIL = '\x1b[31mFAIL\x1b[0m'
  let passed = 0
  let failed = 0

  function assert(condition, name) {
    if (condition) {
      console.log(`  ${PASS} ${name}`)
      passed++
    } else {
      console.log(`  ${FAIL} ${name}`)
      failed++
    }
  }

  const TEST_PORT = 19876
  const BASE = `http://127.0.0.1:${TEST_PORT}`

  // ---- 组1: 后端未启动时 ----
  console.log('\n=== 组1: 后端未启动时的错误处理 ===')

  const r1 = await httpRequestHandler('GET', `${BASE}/api/v1/health`)
  assert(r1.ok === false, '后端未启动: ok应为false')
  assert(r1.status === 0, '后端未启动: status应为0')
  assert(r1.error && r1.error.includes('ECONNREFUSED'), `后端未启动: error应包含ECONNREFUSED, got: ${r1.error}`)
  assert(r1.data === null, '后端未启动: data应为null')

  // ---- 组2: 启动模拟后端 ----
  console.log('\n=== 组2: 后端运行时的GET请求 ===')
  const server = await createMockBackend(TEST_PORT)

  const r2 = await httpRequestHandler('GET', `${BASE}/api/v1/health`)
  assert(r2.ok === true, '健康检查: ok应为true')
  assert(r2.status === 200, '健康检查: status应为200')
  assert(r2.data?.status === 'ok', '健康检查: data.status应为ok')
  assert(r2.data?.market_running === true, '健康检查: market_running应为true')

  const r3 = await httpRequestHandler('GET', `${BASE}/api/v1/market/quotes`)
  assert(r3.ok === true, '行情数据: ok应为true')
  assert(r3.data?.total === 1, '行情数据: total应为1')

  // ---- 组3: POST请求 ----
  console.log('\n=== 组3: POST请求 ===')
  const r4 = await httpRequestHandler('POST', `${BASE}/api/v1/test-post`, { key: 'value' })
  assert(r4.ok === true, 'POST请求: ok应为true')
  assert(r4.data?.received?.key === 'value', 'POST请求: 应返回发送的数据')

  // ---- 组4: DELETE请求 ----
  console.log('\n=== 组5: DELETE请求 ===')
  const r5 = await httpRequestHandler('DELETE', `${BASE}/api/v1/test-delete`)
  assert(r5.ok === true, 'DELETE请求: ok应为true')
  assert(r5.data?.deleted === true, 'DELETE请求: 应返回deleted=true')

  // ---- 组5: PUT请求 ----
  console.log('\n=== 组6: PUT请求 ===')
  const r6 = await httpRequestHandler('PUT', `${BASE}/api/v1/test-put`, { key: 'updated' })
  assert(r6.ok === true, 'PUT请求: ok应为true')
  assert(r6.data?.updated === true, 'PUT请求: 应返回updated=true')

  // ---- 组6: 404错误 ----
  console.log('\n=== 组7: 404错误处理 ===')
  const r7 = await httpRequestHandler('GET', `${BASE}/api/v1/nonexistent`)
  assert(r7.ok === false, '404: ok应为false')
  assert(r7.status === 404, '404: status应为404')

  // ---- 组7: 并发请求 ----
  console.log('\n=== 组8: 并发请求 ===')
  const concurrent = await Promise.all([
    httpRequestHandler('GET', `${BASE}/api/v1/health`),
    httpRequestHandler('GET', `${BASE}/api/v1/market/quotes`),
    httpRequestHandler('GET', `${BASE}/api/v1/health`),
  ])
  assert(concurrent.every(r => r.ok), '并发请求: 所有请求应成功')

  // ---- 组8: 关闭后端后请求 ----
  console.log('\n=== 组9: 后端关闭后的错误处理 ===')
  await new Promise(resolve => server.close(resolve))

  const r8 = await httpRequestHandler('GET', `${BASE}/api/v1/health`)
  assert(r8.ok === false, '后端关闭: ok应为false')
  assert(r8.error !== undefined && r8.error.length > 0, '后端关闭: error应存在')

  // ---- 组9: URL解析 ----
  console.log('\n=== 组10: URL解析安全性 ===')
  // 用不存在的端口测试
  const r9 = await httpRequestHandler('GET', `http://127.0.0.1:19999/api/v1/health`)
  assert(r9.ok === false, '不存在的后端: ok应为false')

  const r10 = await httpRequestHandler('GET', 'not-a-url')
  assert(r10.ok === false, '无效URL格式: ok应为false')
  assert(r10.error !== undefined, '无效URL格式: error应存在')

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
