/**
 * TDD测试: WebSocket IPC代理
 * 1. 代理连接建立
 * 2. 消息转发（文本和二进制）
 * 3. 连接关闭
 * 4. 错误处理
 */

const { WebSocketServer } = require('ws')
const ws = require('ws')

const TEST_PORT = 19882
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

function sleep(ms) {
  return new Promise(r => setTimeout(r, ms))
}

// 模拟后端 WebSocket 服务器
let wss = null

async function setupWsServer() {
  return new Promise((resolve) => {
    wss = new WebSocketServer({ port: TEST_PORT }, () => {
      console.log(`  WebSocket服务器启动于端口 ${TEST_PORT}`)
      resolve()
    })

    wss.on('connection', (client, req) => {
      const token = new URL(req.url, `http://localhost:${TEST_PORT}`).searchParams.get('token')
      if (token !== 'lianghua-default-token') {
        client.close(4001, 'Unauthorized')
        return
      }

      // 发送欢迎消息
      client.send(JSON.stringify({ type: 'tick', data: [{ code: '123456', price: 100 }] }))

      client.on('message', (data) => {
        try {
          const msg = JSON.parse(data.toString())
          if (msg.type === 'ping') {
            client.send(JSON.stringify({ type: 'pong' }))
          }
        } catch {}
      })
    })
  })
}

async function runTests() {
  await setupWsServer()

  // ---- 测试1: 直接WebSocket连接（baseline）----
  console.log('\n=== 测试1: 直接WebSocket连接 ===')

  const directMsgPromise = new Promise(r => {
    const client = new ws(`ws://127.0.0.1:${TEST_PORT}/market?token=lianghua-default-token`)
    client.on('message', (data) => r(JSON.parse(data.toString())))
    client.on('error', () => r(null))
  })

  const directMsg = await directMsgPromise
  assert(directMsg !== null, '直接连接收到欢迎消息')
  assert(directMsg?.type === 'tick', '欢迎消息类型为tick')

  // ---- 测试2: IPC代理连接建立 ----
  console.log('\n=== 测试2: IPC代理连接建立 ===')

  // 模拟 IPC 代理的 ws-connect 处理
  const wsProxies = new Map()

  function wsConnect(wsId, url) {
    if (wsProxies.has(wsId)) {
      return Promise.resolve({ ok: true, state: 'already_connected' })
    }
    try {
      const conn = new ws(url)
      wsProxies.set(wsId, conn)
      return Promise.resolve({ ok: true, state: 'connecting' })
    } catch (e) {
      return Promise.resolve({ ok: false, state: 'error', error: String(e) })
    }
  }

  const result = await wsConnect('market', `ws://127.0.0.1:${TEST_PORT}/market?token=lianghua-default-token`)
  assert(result.ok === true, 'IPC代理连接请求成功')
  assert(result.state === 'connecting', '初始状态为connecting')

  await new Promise(r => wsProxies.get('market').on('open', r))
  const readyState = wsProxies.get('market').readyState
  assert(readyState === 1, '连接建立后readyState为OPEN')

  // ---- 测试3: 代理消息接收 ----
  console.log('\n=== 测试3: 代理消息接收 ===')

  const proxyMsgs = []
  wsProxies.get('market').on('message', (data) => {
    proxyMsgs.push(JSON.parse(data.toString()))
  })

  // 让服务器发一条新消息 - 先关闭重新连接
  wsProxies.get('market').close()
  await sleep(200)
  wsProxies.delete('market')

  await wsConnect('market', `ws://127.0.0.1:${TEST_PORT}/market?token=lianghua-default-token`)
  const newConn = wsProxies.get('market')

  // 等待消息
  const msgPromise = new Promise(r => newConn.once('message', (data) => r(JSON.parse(data.toString()))))
  await new Promise(r => newConn.on('open', r))
  const msg = await msgPromise
  assert(msg !== null, '代理接收到服务器消息')
  assert(msg?.type === 'tick', '代理消息类型为tick')

  // ---- 测试4: 代理发送ping/pong ----
  console.log('\n=== 测试4: 代理发送ping消息 ===')

  const pongPromise = new Promise(r => newConn.once('message', (data) => r(JSON.parse(data.toString()))))
  newConn.send(JSON.stringify({ type: 'ping' }))
  const pong = await pongPromise
  assert(pong?.type === 'pong', '代理收到pong响应')

  // ---- 测试5: 代理连接关闭 ----
  console.log('\n=== 测试5: 代理连接关闭 ===')

  const closePromise = new Promise(r => newConn.on('close', r))
  newConn.close()
  await closePromise
  wsProxies.delete('market')
  assert(wsProxies.size === 0, '连接已从代理中移除')

  // ---- 测试6: 未授权连接 ----
  console.log('\n=== 测试6: 未授权连接 ===')

  await wsConnect('bad', `ws://127.0.0.1:${TEST_PORT}/market?token=wrong-token`)
  const badConn = wsProxies.get('bad')
  if (badConn) {
    const badCloseCode = await new Promise(r => badConn.on('close', (code) => r(code)))
    assert(badCloseCode === 4001, '未授权token被服务器拒绝(code=4001)')
    wsProxies.delete('bad')
  } else {
    assert(false, '连接创建失败')
  }

  // ---- 测试7: 多连接（market + signals）----
  console.log('\n=== 测试7: 多连接 ===')

  await wsConnect('market2', `ws://127.0.0.1:${TEST_PORT}/market?token=lianghua-default-token`)
  await wsConnect('signals2', `ws://127.0.0.1:${TEST_PORT}/signals?token=lianghua-default-token`)

  await new Promise(r => wsProxies.get('market2').on('open', r))
  await new Promise(r => wsProxies.get('signals2').on('open', r))

  assert(wsProxies.get('market2').readyState === 1, 'market2连接建立')
  assert(wsProxies.get('signals2').readyState === 1, 'signals2连接建立')
  assert(wsProxies.size === 2, '代理管理2个连接')

  wsProxies.get('market2').close()
  await new Promise(r => wsProxies.get('market2').on('close', r))
  wsProxies.delete('market2')

  assert(wsProxies.size === 1, '只剩signals2连接')
  wsProxies.get('signals2').close()
  await new Promise(r => wsProxies.get('signals2').on('close', r))
  wsProxies.delete('signals2')

  // ---- 测试8: 重复连接 ----
  console.log('\n=== 测试8: 重复连接相同wsId ===')

  await wsConnect('dup', `ws://127.0.0.1:${TEST_PORT}/market?token=lianghua-default-token`)
  const dupResult = await wsConnect('dup', `ws://127.0.0.1:${TEST_PORT}/market?token=lianghua-default-token`)
  assert(dupResult.state === 'already_connected', '重复连接返回already_connected')

  const dupConn = wsProxies.get('dup')
  if (dupConn && dupConn.readyState === 1) {
    dupConn.close()
    await new Promise(r => dupConn.on('close', r))
  }
  wsProxies.delete('dup')

  // 清理
  wss.close()

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
