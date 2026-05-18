const http = require('http');

const BACKEND_PORT = 8765;
const FRONTEND_PORT = 8766;
const TIMEOUT = 5000;

function fetch(port, path) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), TIMEOUT);
    http.get(`http://127.0.0.1:${port}${path}`, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        clearTimeout(timer);
        resolve({ status: res.statusCode, headers: res.headers, body: data });
      });
    }).on('error', (e) => {
      clearTimeout(timer);
      reject(e);
    });
  });
}

async function runTests() {
  let pass = 0;
  let fail = 0;

  // Test 1: Backend health
  try {
    const r = await fetch(BACKEND_PORT, '/api/v1/health');
    const j = JSON.parse(r.body);
    if (r.status === 200 && j.status === 'ok') {
      console.log('✅ Test 1: Backend health OK');
      pass++;
    } else {
      console.log(`❌ Test 1: Backend health FAIL - status=${r.status} body=${r.body}`);
      fail++;
    }
  } catch (e) {
    console.log(`❌ Test 1: Backend health ERROR - ${e.message}`);
    fail++;
  }

  // Test 2: Frontend serves index.html
  try {
    const r = await fetch(FRONTEND_PORT, '/');
    if (r.status === 200 && r.body.includes('LiangHua') && !r.body.includes('crossorigin')) {
      console.log('✅ Test 2: Frontend index.html OK (no crossorigin)');
      pass++;
    } else {
      const hasCrossorigin = r.body.includes('crossorigin');
      console.log(`❌ Test 2: Frontend index.html FAIL - status=${r.status} crossorigin=${hasCrossorigin}`);
      fail++;
    }
  } catch (e) {
    console.log(`❌ Test 2: Frontend index.html ERROR - ${e.message}`);
    fail++;
  }

  // Test 3: Frontend PROXIES /api/* to backend
  try {
    const r = await fetch(FRONTEND_PORT, '/api/v1/health');
    const j = JSON.parse(r.body);
    if (r.status === 200 && j.status === 'ok') {
      console.log('✅ Test 3: Frontend API proxy OK');
      pass++;
    } else {
      console.log(`❌ Test 3: Frontend API proxy FAIL - status=${r.status} body=${r.body.substring(0, 100)}`);
      fail++;
    }
  } catch (e) {
    console.log(`❌ Test 3: Frontend API proxy ERROR - ${e.message}`);
    fail++;
  }

  // Test 4: Frontend serves JS assets
  try {
    const indexR = await fetch(FRONTEND_PORT, '/');
    const jsMatch = indexR.body.match(/src="\.\/assets\/([^"]+\.js)"/);
    if (jsMatch) {
      const jsR = await fetch(FRONTEND_PORT, `/assets/${jsMatch[1]}`);
      if (jsR.status === 200 && jsR.headers['content-type']?.includes('javascript')) {
        console.log(`✅ Test 4: Frontend JS assets OK (${jsMatch[1]})`);
        pass++;
      } else {
        console.log(`❌ Test 4: Frontend JS assets FAIL - status=${jsR.status}`);
        fail++;
      }
    } else {
      console.log('❌ Test 4: Frontend JS assets FAIL - no script tag found');
      fail++;
    }
  } catch (e) {
    console.log(`❌ Test 4: Frontend JS assets ERROR - ${e.message}`);
    fail++;
  }

  // Test 5: React mounted (check root has children)
  try {
    const ws = require('ws');
    const pages = JSON.parse(await new Promise((resolve, reject) => {
      http.get('http://127.0.0.1:9222/json', (res) => {
        let d = '';
        res.on('data', (c) => { d += c; });
        res.on('end', () => resolve(d));
      }).on('error', reject);
    }));
    if (pages.length === 0) { throw new Error('No pages'); }
    const pageWs = new ws(pages[0]['webSocketDebuggerUrl'], { headers: { Origin: '*' } });
    await new Promise((r) => { pageWs.on('open', r); });
    pageWs.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression: 'document.getElementById("root").children.length', returnByValue: true } }));
    const resp = await new Promise((r) => { pageWs.on('message', (d) => r(JSON.parse(d))); });
    const children = resp?.result?.result?.value;
    pageWs.close();
    if (children > 0) {
      console.log(`✅ Test 5: React mounted OK (${children} children)`);
      pass++;
    } else {
      console.log(`❌ Test 5: React mounted FAIL - ${children} children`);
      fail++;
    }
  } catch (e) {
    console.log(`❌ Test 5: React mounted ERROR - ${e.message}`);
    fail++;
  }

  console.log(`\n===== Results: ${pass} passed, ${fail} failed =====`);
  process.exit(fail > 0 ? 1 : 0);
}

runTests().catch((e) => { console.error('Fatal:', e); process.exit(1); });
