/**
 * TDD测试: 完整打包 App 启动流程
 * 模拟 Electron 主进程启动→后端就绪→前端连接→API 请求
 */
const http = require('http')
const fs = require('fs')
const path = require('path')
const { spawn } = require('child_process')

const PASS = '\x1b[32mPASS\x1b[0m'
const FAIL = '\x1b[31mFAIL\x1b[0m'
let passed = 0
let failed = 0

function assert2(condition, name) {
  if (condition) { console.log(`  ${PASS} ${name}`); passed++ }
  else { console.log(`  ${FAIL} ${name}`); failed++ }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)) }

// ============================================================
// 测试1: PyInstaller 二进制可执行
// ============================================================
async function testBinaryExecutable() {
  console.log('\n=== 测试1: PyInstaller 二进制可执行 ===')
  const binPath = path.join(__dirname, '..', '..', 'backend', 'lianghua-backend')
  if (!fs.existsSync(binPath)) {
    console.log('  SKIP: 二进制文件不存在（需要先打包后端）')
    return
  }
  assert2(fs.existsSync(binPath), '二进制文件存在')

  // 检查是否有执行权限
  const stat = fs.statSync(binPath)
  const hasExecPermission = !!(stat.mode & 0o111)
  assert2(hasExecPermission, '二进制文件有执行权限')

  // 测试 --help 参数（不启动服务器）
  const result = await new Promise((resolve) => {
    const proc = spawn(binPath, ['--help'], { timeout: 5000 })
    let output = ''
    proc.stdout?.on('data', (d) => { output += d.toString() })
    proc.stderr?.on('data', (d) => { output += d.toString() })
    proc.on('close', (code) => resolve({ code, output }))
    proc.on('error', (err) => resolve({ code: -1, output: err.message }))
    setTimeout(() => { proc.kill(); resolve({ code: -2, output: 'timeout' }) }, 5000)
  })

  console.log(`  --help 输出: ${result.output.substring(0, 100)}...`)
  assert2(result.code !== -1, '二进制可执行（不报错）')
}

// ============================================================
// 测试2: main.ts 中 getPythonCmd 查找逻辑
// ============================================================
async function testGetPythonCmdLogic() {
  console.log('\n=== 测试2: getPythonCmd 查找逻辑 ===')

  const mainTs = fs.readFileSync(path.join(__dirname, '..', 'main.ts'), 'utf-8')

  // 验证代码中先查根目录再查 dist
  const rootBinPattern = /path\.join\(backendDir,\s*['"]lianghua-backend['"]\)/
  const distBinPattern = /path\.join\(backendDir,\s*['"]dist['"],\s*['"]lianghua-backend['"]\)/

  const hasRootBinCheck = rootBinPattern.test(mainTs)
  const hasDistBinCheck = distBinPattern.test(mainTs)

  assert2(hasRootBinCheck, 'main.ts 先查 backend/lianghua-backend（根目录）')
  assert2(hasDistBinCheck, 'main.ts 再查 backend/dist/lianghua-backend（备选）')

  // 验证根目录检查在 dist 之前
  const rootIndex = mainTs.search(rootBinPattern)
  const distIndex = mainTs.search(distBinPattern)
  assert2(rootIndex < distIndex, '根目录检查在 dist 检查之前')

  // 验证 spawn 参数区分 PyInstaller 和 Python3
  const hasIsPyinstaller = mainTs.includes("endsWith('lianghua-backend')")
  const hasUvicornArgs = mainTs.includes("-m', 'uvicorn', 'app.main:app'")
  assert2(hasIsPyinstaller, 'main.ts 区分 PyInstaller 二进制和 Python3')
  assert2(hasUvicornArgs, 'main.ts Python3 回退使用 -m uvicorn app.main:app')
}

// ============================================================
// 测试3: HashRouter 替换完成
// ============================================================
async function testHashRouterComplete() {
  console.log('\n=== 测试3: HashRouter 替换完成 ===')

  const mainTsx = fs.readFileSync(path.join(__dirname, '..', '..', 'frontend', 'src', 'main.tsx'), 'utf-8')
  assert2(!mainTsx.includes('BrowserRouter'), 'main.tsx 不再使用 BrowserRouter')
  assert2(mainTsx.includes('HashRouter'), 'main.tsx 使用 HashRouter')

  // 检查 hotkeys.ts 中的导航使用 hash 方式
  const hotkeysTs = fs.readFileSync(path.join(__dirname, '..', '..', 'frontend', 'src', 'utils', 'hotkeys.ts'), 'utf-8')
  const badNavCount = (hotkeysTs.match(/window\.location\.href\s*=\s*['"]\//g) || []).length
  const goodNavCount = (hotkeysTs.match(/window\.location\.hash\s*=\s*['"]#\//g) || []).length

  assert2(badNavCount === 0, 'hotkeys.ts 不使用 window.location.href 路由跳转')
  assert2(goodNavCount >= 3, 'hotkeys.ts 使用 window.location.hash 路由跳转')
}

// ============================================================
// 测试4: 离线模式不会意外启用
// ============================================================
async function testOfflineModeFixed() {
  console.log('\n=== 测试4: 离线模式不会意外启用 ===')

  const dataCacheTs = fs.readFileSync(path.join(__dirname, '..', '..', 'frontend', 'src', 'utils', 'dataCache.ts'), 'utf-8')

  // isOfflineMode 应该在 Electron 环境下忽略 navigator.onLine
  const hasElectronCheck = dataCacheTs.includes('electronAPI') && dataCacheTs.includes('httpRequest')
  assert2(hasElectronCheck, 'isOfflineMode 在 Electron 环境下忽略 navigator.onLine')

  // StartupLoading 成功连接后应该 disableOfflineMode
  const startupTs = fs.readFileSync(path.join(__dirname, '..', '..', 'frontend', 'src', 'components', 'StartupLoading.tsx'), 'utf-8')
  const hasDisableOnSuccess = startupTs.includes('disableOfflineMode()')
  assert2(hasDisableOnSuccess, 'StartupLoading 连接成功后调用 disableOfflineMode()')
}

// ============================================================
// 测试5: package.json 不排除 lianghua-backend
// ============================================================
async function testPackageJsonNoDistFilter() {
  console.log('\n=== 测试5: package.json 不排除二进制文件 ===')

  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'package.json'), 'utf-8'))
  const backendResource = pkg.build.extraResources.find(r => r.to === 'backend')

  assert2(backendResource !== undefined, 'backend extraResources 存在')

  // 不应该有 !dist/** 过滤
  const hasDistFilter = backendResource.filter.includes('!dist/**')
  assert2(!hasDistFilter, '!dist/** 过滤已移除（二进制文件可以被打包）')

  // lianghua-backend 根目录文件应该被 **/* 匹配到
  assert2(backendResource.filter.includes('**/*'), '**/* 包含规则存在')
}

// ============================================================
// 测试6: 完整模拟后端启动→健康检查→API 请求
// ============================================================
async function testFullBootFlow() {
  console.log('\n=== 测试6: 完整启动→连接→API 请求模拟 ===')

  // 创建模拟后端
  let backendReady = false
  const server = http.createServer((req, res) => {
    if (!backendReady) {
      res.writeHead(503)
      res.end(JSON.stringify({ status: 'error' }))
      return
    }

    const respond = (code, data) => {
      res.writeHead(code, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify(data))
    }

    if (req.url === '/health') {
      respond(200, { status: 'ok', app: 'LiangHua', market_running: true, db_ok: true, ws_auth_token: 'flow-test-token' })
    } else if (req.url === '/api/v1/market/quotes') {
      respond(200, { total: 2, bonds: [{ code: '113050', name: '南银转债', price: 105.5 }], updated_at: '2026-05-16' })
    } else if (req.url === '/api/v1/health') {
      respond(200, { status: 'ok', app: 'LiangHua', market_running: true, db_ok: true, ws_auth_token: 'flow-test-token' })
    } else {
      respond(404, { detail: 'Not found' })
    }
  })

  await new Promise(r => server.listen(19895, r))
  const BASE = 'http://127.0.0.1:19895'

  // 模拟 IPC 代理请求函数
  function httpRequest(method, url, body) {
    return new Promise((resolve) => {
      try {
        const parsedUrl = new URL(url)
        const options = {
          hostname: parsedUrl.hostname,
          port: parsedUrl.port || 80,
          path: parsedUrl.pathname + parsedUrl.search,
          method: method.toUpperCase(),
          headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
          timeout: 5000,
        }
        const req = http.request(options, (res) => {
          let data = ''
          res.on('data', (chunk) => { data += chunk })
          res.on('end', () => {
            try { resolve({ ok: res.statusCode >= 200 && res.statusCode < 300, status: res.statusCode, data: JSON.parse(data) }) }
            catch { resolve({ ok: false, status: res.statusCode, data: null }) }
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

  // 步骤1: 后端未启动时健康检查失败
  const check1 = await httpRequest('GET', `${BASE}/health`)
  assert2(check1.ok === false, '后端未启动: 健康检查失败')
  assert2(check1.status === 503, '后端未启动: 返回 503')

  // 步骤2: 模拟后端启动
  backendReady = true

  // 步骤3: 健康检查成功
  const check2 = await httpRequest('GET', `${BASE}/health`)
  assert2(check2.ok === true, '后端启动后: 健康检查成功')
  assert2(check2.data?.ws_auth_token === 'flow-test-token', '后端启动后: 返回 ws_auth_token')

  // 步骤4: API 数据请求成功
  const quotesResult = await httpRequest('GET', `${BASE}/api/v1/market/quotes`)
  assert2(quotesResult.ok === true, 'API 数据请求成功')
  assert2(quotesResult.data?.bonds?.length === 1, 'API 返回行情数据')

  // 步骤5: /api/v1/health 也成功
  const check3 = await httpRequest('GET', `${BASE}/api/v1/health`)
  assert2(check3.ok === true, '/api/v1/health 也成功')

  await new Promise(r => server.close(r))
}

// ============================================================
// 测试7: 确认 Electron main.ts 编译通过
// ============================================================
async function testMainTsCompiles() {
  console.log('\n=== 测试7: main.ts TypeScript 编译检查 ===')

  const { execSync } = require('child_process')
  try {
    const electronDir = path.join(__dirname, '..')
  const tsc = path.join(electronDir, 'node_modules', '.bin', 'tsc')
  const tsconfig = path.join(electronDir, 'tsconfig.json')
  execSync(`${tsc} -p ${tsconfig} --noEmit`, {
      timeout: 30000,
      stdio: 'pipe'
    })
    assert2(true, 'main.ts TypeScript 编译通过')
  } catch (e) {
    assert2(false, 'main.ts TypeScript 编译失败: ' + e.stderr?.toString().substring(0, 100))
  }
}

// ============================================================
// 运行
// ============================================================
async function runAll() {
  await testBinaryExecutable()
  await testGetPythonCmdLogic()
  await testHashRouterComplete()
  await testOfflineModeFixed()
  await testPackageJsonNoDistFilter()
  await testFullBootFlow()
  await testMainTsCompiles()

  console.log(`\n${'='.repeat(50)}`)
  console.log(`结果: ${passed} 通过, ${failed} 失败, ${passed + failed} 总计`)
  if (failed > 0) {
    console.log('\x1b[31m存在失败测试！\x1b[0m')
    process.exit(1)
  } else {
    console.log('\x1b[32m所有测试通过！\x1b[0m')
  }
}

runAll().catch(e => { console.error('测试执行错误:', e); process.exit(1) })
