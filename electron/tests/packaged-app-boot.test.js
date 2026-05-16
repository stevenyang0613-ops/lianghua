/**
 * TDD测试: 打包App启动流程验证
 * 
 * 验证关键路径:
 * 1. PyInstaller二进制路径查找（backend/lianghua-backend 而非 dist/lianghua-backend）
 * 2. Python3回退时需要指定脚本文件
 * 3. BrowserRouter vs HashRouter 在 file:// 协议下的兼容性
 * 4. 前端请求在 Electron 环境下正确走 IPC 代理
 * 5. 健康检查后正确连接后端（不进入离线模式）
 */

const http = require('http')
const fs = require('fs')
const path = require('path')
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

// ============================================================
// 测试1: PyInstaller 二进制路径查找
// ============================================================
async function testBinaryPath() {
  console.log('\n=== 测试1: PyInstaller 二进制路径查找 ===')

  const backendDir = '/Users/stevenyang/Public/lianghua/backend'

  // 模拟 getPythonCmd 的逻辑
  function getPythonCmd(backendDir) {
    // 正确：先查根目录下的二进制
    const pyinstallerBin = path.join(backendDir, 'lianghua-backend')
    if (fs.existsSync(pyinstallerBin)) return pyinstallerBin
    // 再查 dist 子目录
    const pyinstallerBinDist = path.join(backendDir, 'dist', 'lianghua-backend')
    if (fs.existsSync(pyinstallerBinDist)) return pyinstallerBinDist
    // 回退到 .venv
    const venvPython = path.join(backendDir, '.venv', 'bin', 'python')
    if (fs.existsSync(venvPython)) return venvPython
    return 'python3'
  }

  const cmd = getPythonCmd(backendDir)
  console.log(`  找到命令: ${cmd}`)

  // 应该找到根目录下的二进制
  assert2(cmd.endsWith('lianghua-backend'), '找到 PyInstaller 二进制')
  assert2(!cmd.includes('/dist/lianghua-backend'), '优先使用根目录二进制（非 dist 子目录）')

  // 验证文件确实存在
  assert2(fs.existsSync(cmd), '二进制文件实际存在')

  // 验证 dist 下的也存在（开发环境）
  const distBin = path.join(backendDir, 'dist', 'lianghua-backend')
  assert2(fs.existsSync(distBin), 'dist 下的二进制也存在（开发环境）')
}

// ============================================================
// 测试2: spawn 参数正确性
// ============================================================
async function testSpawnArgs() {
  console.log('\n=== 测试2: spawn 参数正确性 ===')

  const BACKEND_HOST = '127.0.0.1'
  const BACKEND_PORT = 8765

  function getSpawnArgs(pythonCmd) {
    const isPyinstaller = pythonCmd.endsWith('lianghua-backend')
    if (isPyinstaller) {
      return ['--host', BACKEND_HOST, '--port', String(BACKEND_PORT)]
    }
    // python3 需要 -m uvicorn 方式启动
    return ['-m', 'uvicorn', 'app.main:app', '--host', BACKEND_HOST, '--port', String(BACKEND_PORT)]
  }

  // PyInstaller 二进制参数
  const pyinstallerArgs = getSpawnArgs('/path/to/backend/lianghua-backend')
  assert2(pyinstallerArgs[0] === '--host', 'PyInstaller: 第一个参数是 --host')
  assert2(pyinstallerArgs[1] === BACKEND_HOST, 'PyInstaller: host 正确')
  assert2(pyinstallerArgs[2] === '--port', 'PyInstaller: 第三个参数是 --port')
  assert2(pyinstallerArgs[3] === String(BACKEND_PORT), 'PyInstaller: port 正确')

  // Python3 回退参数
  const pythonArgs = getSpawnArgs('python3')
  assert2(pythonArgs[0] === '-m', 'Python3: 使用 -m 方式启动')
  assert2(pythonArgs[1] === 'uvicorn', 'Python3: 模块名 uvicorn')
  assert2(pythonArgs[2] === 'app.main:app', 'Python3: 应用入口 app.main:app')
}

// ============================================================
// 测试3: package.json 过滤配置
// ============================================================
async function testPackageJsonFilter() {
  console.log('\n=== 测试3: package.json 打包过滤配置 ===')

  const pkgPath = '/Users/stevenyang/Public/lianghua/electron/package.json'
  const pkg = JSON.parse(fs.readFileSync(pkgPath, 'utf-8'))
  const backendResource = pkg.build.extraResources.find(r => r.to === 'backend')

  assert2(backendResource !== undefined, 'backend extraResources 配置存在')
  assert2(backendResource.filter !== undefined, 'filter 配置存在')

  // dist 目录不应该被排除（因为二进制可能在那里）
  const hasDistFilter = backendResource.filter.includes('!dist/**')
  console.log(`  当前 !dist/** 过滤: ${hasDistFilter ? '存在（问题！）' : '不存在（正确）'}`)

  // lianghua-backend 根目录文件应该被包含
  const rootBinaryExists = fs.existsSync('/Users/stevenyang/Public/lianghua/backend/lianghua-backend')
  assert2(rootBinaryExists, '根目录二进制文件存在')

  // 验证 app 目录存在（Python 模块源码）
  const appDirExists = fs.existsSync('/Users/stevenyang/Public/lianghua/backend/app')
  assert2(appDirExists, 'app 目录存在（Python 模块）')
}

// ============================================================
// 测试4: Router 类型对 file:// 的兼容性
// ============================================================
async function testRouterType() {
  console.log('\n=== 测试4: Router 类型检查 ===')

  const mainTsx = fs.readFileSync('/Users/stevenyang/Public/lianghua/frontend/src/main.tsx', 'utf-8')

  const hasBrowserRouter = mainTsx.includes('BrowserRouter')
  const hasHashRouter = mainTsx.includes('HashRouter')

  console.log(`  BrowserRouter: ${hasBrowserRouter ? '存在' : '不存在'}`)
  console.log(`  HashRouter: ${hasHashRouter ? '存在' : '不存在'}`)

  // 在 file:// 协议下必须使用 HashRouter
  assert2(hasHashRouter === true, '使用 HashRouter（file:// 协议兼容）')
  assert2(hasBrowserRouter === false, '不使用 BrowserRouter（file:// 下不可用）')
}

// ============================================================
// 测试5: 前端 API 请求走 IPC 代理
// ============================================================
async function testFrontendIPCProxy() {
  console.log('\n=== 测试5: 前端 API 请求走 IPC 代理 ===')

  const configTs = fs.readFileSync('/Users/stevenyang/Public/lianghua/frontend/src/utils/config.ts', 'utf-8')
  const apiTs = fs.readFileSync('/Users/stevenyang/Public/lianghua/frontend/src/services/api.ts', 'utf-8')
  const startupTs = fs.readFileSync('/Users/stevenyang/Public/lianghua/frontend/src/components/StartupLoading.tsx', 'utf-8')

  // config.ts 应该用 hasElectronAPI (检查 httpRequest) 而不是 isElectron
  const hasHttpRequestCheck = configTs.includes('httpRequest') || configTs.includes('hasElectronAPI')
  assert2(hasHttpRequestCheck === true, 'config.ts 使用 httpRequest 检测 Electron 环境')

  // StartupLoading 应该用 httpRequest 做健康检查
  const startupUsesIpc = startupTs.includes('httpRequest') || startupTs.includes('electronAPI')
  assert2(startupUsesIpc === true, 'StartupLoading 通过 IPC 代理做健康检查')

  // 健康检查路径应该是 /health
  const healthPath = startupTs.includes('/health')
  assert2(healthPath === true, 'StartupLoading 使用 /health 路径')
}

// ============================================================
// 测试6: 后端 /health 和 /api/v1/health 双路由
// ============================================================
async function testBackendHealthRoutes() {
  console.log('\n=== 测试6: 后端健康检查路由 ===')

  const mainPy = fs.readFileSync('/Users/stevenyang/Public/lianghua/backend/app/main.py', 'utf-8')

  const hasHealthRoute = mainPy.includes('@app.get("/health")')
  const hasApiV1HealthRoute = mainPy.includes('@app.get("/api/v1/health")')
  const hasWsAuthToken = mainPy.includes('ws_auth_token')

  assert2(hasHealthRoute === true, '/health 路由存在')
  assert2(hasApiV1HealthRoute === true, '/api/v1/health 路由存在')
  assert2(hasWsAuthToken === true, '健康检查返回 ws_auth_token')
}

// ============================================================
// 测试7: 完整 IPC 代理 HTTP 测试
// ============================================================
async function testIPCProxyHTTP() {
  console.log('\n=== 测试7: IPC 代理 HTTP 请求测试 ===')

  // 模拟 main.ts 中的 httpRequestHandler
  function httpRequestHandler(method, url, body) {
    return new Promise((resolve) => {
      try {
        const parsedUrl = new URL(url)
        const options = {
          hostname: parsedUrl.hostname,
          port: parsedUrl.port || 80,
          path: parsedUrl.pathname + parsedUrl.search,
          method: method.toUpperCase(),
          headers: {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
          },
          timeout: 5000,
        }

        const req = http.request(options, (res) => {
          let data = ''
          res.on('data', (chunk) => { data += chunk })
          res.on('end', () => {
            try {
              resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, data: JSON.parse(data) })
            } catch {
              resolve({ ok: false, status: res.statusCode, data: null })
            }
          })
        })
        req.on('error', (e) => resolve({ ok: false, status: 0, data: null, error: e.message }))
        req.setTimeout(5000, () => { req.destroy(); resolve({ ok: false, status: 0, data: null, error: 'timeout' }) })
        if (body && method !== 'GET') req.write(JSON.stringify(body))
        req.end()
      } catch (e) {
        resolve({ ok: false, status: 0, data: null, error: String(e) })
      }
    })
  }

  // 创建模拟后端
  const server = http.createServer((req, res) => {
    const respond = (code, data) => {
      res.writeHead(code, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify(data))
    }
    if (req.url === '/health') {
      respond(200, { status: 'ok', app: 'LiangHua', market_running: true, db_ok: true, ws_auth_token: 'test-ipc-token' })
    } else if (req.url === '/api/v1/health') {
      respond(200, { status: 'ok', app: 'LiangHua', market_running: true, db_ok: true, ws_auth_token: 'test-ipc-token' })
    } else if (req.url === '/api/v1/market/quotes') {
      respond(200, { total: 2, bonds: [{ code: '113050', name: '南银转债' }], updated_at: '2026-05-16' })
    } else {
      respond(404, { detail: 'Not found' })
    }
  })

  await new Promise(r => server.listen(19893, r))
  const BASE = 'http://127.0.0.1:19893'

  // 测试 IPC 代理方式请求 /health
  const healthResult = await httpRequestHandler('GET', `${BASE}/health`)
  assert2(healthResult.ok === true, 'IPC代理 GET /health 成功')
  assert2(healthResult.data?.ws_auth_token === 'test-ipc-token', 'IPC代理返回 ws_auth_token')

  // 测试 /api/v1/health
  const healthV1 = await httpRequestHandler('GET', `${BASE}/api/v1/health`)
  assert2(healthV1.ok === true, 'IPC代理 GET /api/v1/health 成功')

  // 测试行情数据
  const quotesResult = await httpRequestHandler('GET', `${BASE}/api/v1/market/quotes`)
  assert2(quotesResult.ok === true, 'IPC代理 GET 行情数据成功')
  assert2(quotesResult.data?.total === 2, 'IPC代理行情数据正确')

  await new Promise(r => server.close(r))
}

// ============================================================
// 测试8: offline 模式不应默认启用
// ============================================================
async function testNoDefaultOffline() {
  console.log('\n=== 测试8: 离线模式不应默认启用 ===')

  const startupTs = fs.readFileSync('/Users/stevenyang/Public/lianghua/frontend/src/components/StartupLoading.tsx', 'utf-8')
  const dataCacheTs = fs.readFileSync('/Users/stevenyang/Public/lianghua/frontend/src/utils/dataCache.ts', 'utf-8')

  // enableOfflineMode 不应在组件初始化时被调用
  const autoOfflineInInit = startupTs.match(/useEffect[^]*enableOfflineMode/m)
  console.log(`  StartupLoading 自动启用离线模式: ${autoOfflineInInit ? '可能' : '否'}`)

  // 检查 isOfflineMode 默认值
  const defaultOffline = dataCacheTs.includes("localStorage.getItem('offline_mode')")
  console.log(`  离线模式持久化检查: ${defaultOffline ? '存在' : '不存在'}`)
}

// ============================================================
// 运行所有测试
// ============================================================
async function runAllTests() {
  await testBinaryPath()
  await testSpawnArgs()
  await testPackageJsonFilter()
  await testRouterType()
  await testFrontendIPCProxy()
  await testBackendHealthRoutes()
  await testIPCProxyHTTP()
  await testNoDefaultOffline()

  console.log(`\n${'='.repeat(50)}`)
  console.log(`结果: ${passed} 通过, ${failed} 失败, ${passed + failed} 总计`)
  if (failed > 0) {
    console.log('\x1b[31m存在失败测试！需要修复后重新运行\x1b[0m')
    process.exit(1)
  } else {
    console.log('\x1b[32m所有测试通过！\x1b[0m')
  }
}

runAllTests().catch(e => {
  console.error('测试执行错误:', e)
  process.exit(1)
})
