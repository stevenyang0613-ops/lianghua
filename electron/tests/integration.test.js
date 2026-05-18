/**
 * TDD Integration Test: Full system verification
 */
const http = require('http')
const fs = require('fs')
const path = require('path')

const BACKEND_PORT = 8765
const FRONTEND_PORT = 8766
const FRONTEND_DIR = path.join(__dirname, '..', '..', 'frontend', 'dist')

const PASS = '\x1b[32mPASS\x1b[0m'
const FAIL = '\x1b[31mFAIL\x1b[0m'
let passed = 0, failed = 0

function assert(condition, name) {
  if (condition) { console.log('  ' + PASS + ' ' + name); passed++ }
  else { console.log('  ' + FAIL + ' ' + name); failed++ }
}

function httpGet(url) {
  return new Promise((resolve, reject) => {
    http.get(url, (res) => {
      let data = ''
      res.on('data', (chunk) => { data += chunk.toString() })
      res.on('end', () => resolve({ status: res.statusCode, data, headers: res.headers }))
    }).on('error', reject).setTimeout(5000, () => reject(new Error('timeout')))
  })
}

async function runTests() {
  console.log('\n=== Integration Test: Full System Verification ===\n')

  // ---- Part 1: Backend ----
  console.log('=== Part 1: Backend API ===')
  try {
    const r = await httpGet('http://127.0.0.1:' + BACKEND_PORT + '/api/v1/health')
    assert(r.status === 200, 'Health API returns 200 (got ' + r.status + ')')
    const d = JSON.parse(r.data)
    assert(d.status === 'ok', 'Health status is ok')
    assert(!!d.ws_auth_token, 'Health response includes ws_auth_token')

    const q = await httpGet('http://127.0.0.1:' + BACKEND_PORT + '/api/v1/market/quotes')
    assert(q.status === 200, '/quotes without symbols returns 200 (got ' + q.status + ')')

    const q2 = await httpGet('http://127.0.0.1:' + BACKEND_PORT + '/api/v1/market/quotes?symbols=123456')
    assert(q2.status === 200, '/quotes with symbols also returns 200')
  } catch (e) {
    assert(false, 'Backend reachable: ' + e.message)
  }

  // ---- Part 2: Frontend static files ----
  console.log('\n=== Part 2: Frontend Static Files ===')
  assert(fs.existsSync(FRONTEND_DIR), 'Frontend dist exists')
  assert(fs.existsSync(path.join(FRONTEND_DIR, 'index.html')), 'index.html exists')
  assert(fs.existsSync(path.join(FRONTEND_DIR, 'assets')), 'assets dir exists')

  const html = fs.readFileSync(path.join(FRONTEND_DIR, 'index.html'), 'utf-8')
  assert(!html.includes('crossorigin'), 'index.html has crossorigin removed')
  assert(html.includes('type="module"'), 'Script uses type=module')

  const assets = fs.readdirSync(path.join(FRONTEND_DIR, 'assets'))
  assert(assets.length > 50, 'Has sufficient assets: ' + assets.length)
  assert(assets.some(f => f.endsWith('.css')), 'CSS file exists')

  const m = html.match(/src="\.\/assets\/([^"]+\.js)"/)
  if (m) {
    const mainJs = m[1]
    assert(fs.existsSync(path.join(FRONTEND_DIR, 'assets', mainJs)), 'Main JS exists: ' + mainJs)
    const c = fs.readFileSync(path.join(FRONTEND_DIR, 'assets', mainJs), 'utf-8')
    assert(c.includes('createElement'), 'React compiled')
    assert(c.includes('lazy('), 'React.lazy used')
    assert(c.includes('getDerivedStateFromError'), 'ErrorBoundary present')
    assert(c.includes('HashRouter'), 'HashRouter used')
  }

  // ---- Part 3: Frontend HTTP Server ----
  console.log('\n=== Part 3: Frontend HTTP Server ===')
  try {
    const r = await httpGet('http://127.0.0.1:' + FRONTEND_PORT + '/')
    assert(r.status === 200, 'Frontend server returns 200')
    assert(!r.data.includes('crossorigin'), 'Server strips crossorigin')
    
    if (m) {
      const js = await httpGet('http://127.0.0.1:' + FRONTEND_PORT + '/assets/' + m[1])
      assert(js.status === 200, 'Main JS loads (status ' + js.status + ')')
      const ct = js.headers['content-type'] || ''
      assert(ct.includes('javascript'), 'Content-Type is javascript (got: ' + ct + ')')
    }

    const proxy = await httpGet('http://127.0.0.1:' + FRONTEND_PORT + '/api/v1/health')
    assert(proxy.status === 200, 'API proxy works (status ' + proxy.status + ')')
    const pd = JSON.parse(proxy.data)
    assert(!!pd.ws_auth_token, 'API proxy injects ws_auth_token')

    const nf = await httpGet('http://127.0.0.1:' + FRONTEND_PORT + '/missing.js')
    assert(nf.status === 404, 'Missing files return 404')
  } catch (e) {
    assert(false, 'Frontend server: ' + e.message)
  }

  // ---- Summary ----
  console.log('\n========================================')
  console.log('Results: ' + passed + ' passed, ' + failed + ' failed')
  if (failed > 0) {
    console.log('\n' + FAIL + ' ' + failed + ' failures! Fix required.')
    process.exit(1)
  }
  console.log('\n' + PASS + ' All tests passed!')
}

runTests().catch(e => { console.error('Fatal:', e); process.exit(1) })
