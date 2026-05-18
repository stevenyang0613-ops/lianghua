const http = require('http')
const fs = require('fs')
const path = require('path')
const { spawn } = require('child_process')

const PASS = '\x1b[32mPASS\x1b[0m'
const FAIL = '\x1b[31mFAIL\x1b[0m'
let passed = 0, failed = 0

function assert(condition, msg) {
  if (condition) { console.log(`  ${PASS} ${msg}`); passed++ }
  else { console.log(`  ${FAIL} ${msg}`); failed++ }
}

const mockResourcesPath = '/Users/stevenyang/Desktop/LiangHua.app/Contents/Resources'

async function testAll() {
  console.log('\n=== TDD: 后端启动全流程测试 ===')

  // 测试1-5: 路径和二进制
  console.log('\n[测试1-5] 路径和二进制存在性')
  const backendDir = path.join(mockResourcesPath, 'backend')
  assert(fs.existsSync(backendDir), 'backend 目录存在')
  const binPath = path.join(backendDir, 'dist', 'lianghua-backend')
  assert(fs.existsSync(binPath), 'lianghua-backend 二进制存在')
  const stat = fs.statSync(binPath)
  assert(!!(stat.mode & 0o111), '二进制有执行权限')
  assert(stat.size > 100000000, `二进制大小合理: ${(stat.size / 1024 / 1024).toFixed(0)}MB`)

  // 测试6: 二进制启动并在120秒内健康检查成功
  console.log('\n[测试6] 二进制启动 (最长等待120秒)')
  const proc = spawn(binPath, ['--host', '127.0.0.1', '--port', '18769'], { timeout: 180000 })
  
  const startTime = Date.now()
  let healthOk = false
  for (let i = 0; i < 120; i++) {
    await new Promise(r => setTimeout(r, 1000))
    try {
      const result = await new Promise((resolve) => {
        http.get('http://127.0.0.1:18769/api/v1/health', (res) => {
          let d = ''; res.on('data', c => d += c); res.on('end', () => resolve(d))
        }).on('error', () => resolve(null))
      })
      if (result) {
        const data = JSON.parse(result)
        if (data.status === 'ok') {
          healthOk = true
          const elapsed = Math.round((Date.now() - startTime) / 1000)
          assert(true, `健康检查成功 (${elapsed}s, status=${data.status})`)
          break
        }
      }
    } catch {}
  }
  
  if (!healthOk) {
    assert(false, '健康检查未能在120秒内成功')
  }
  
  proc.kill()

  // 结果
  console.log(`\n${'='.repeat(50)}`)
  console.log(`结果: ${passed} 通过, ${failed} 失败, ${passed + failed} 总计`)
  if (failed > 0) process.exit(1)
}

testAll().catch(e => { console.error('ERROR:', e); process.exit(1) })