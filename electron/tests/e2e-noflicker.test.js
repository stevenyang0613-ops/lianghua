const http = require('http');
const ws = require('ws');

const BACKEND = 8765;
const FRONTEND = 8766;
const CDP = 9222;

function fetch(port, path) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), 5000);
    http.get(`http://127.0.0.1:${port}${path}`, (res) => {
      let data = '';
      res.on('data', (c) => { data += c; });
      res.on('end', () => { clearTimeout(timer); resolve({ status: res.statusCode, body: data }); });
    }).on('error', (e) => { clearTimeout(timer); reject(e); });
  });
}

function cdpEval(expr) {
  return new Promise(async (resolve, reject) => {
    try {
      const pages = JSON.parse(await new Promise((r, j) => {
        http.get(`http://127.0.0.1:${CDP}/json`, (res) => {
          let d = ''; res.on('data', c => d += c); res.on('end', () => r(d));
        }).on('error', j);
      }));
      if (!pages.length) { reject('No pages'); return; }
      const socket = new ws(pages[0].webSocketDebuggerUrl, { headers: { Origin: '*' } });
      socket.on('open', () => {
        socket.send(JSON.stringify({ id: 1, method: 'Runtime.evaluate', params: { expression: expr, returnByValue: true } }));
      });
      socket.on('message', (d) => {
        const resp = JSON.parse(d);
        if (resp.id === 1) {
          socket.close();
          resolve(resp.result?.result?.value);
        }
      });
      setTimeout(() => { socket.close(); reject('cdp timeout'); }, 5000);
    } catch (e) { reject(e); }
  });
}

async function run() {
  let pass = 0, fail = 0;
  const t = (name, ok) => { if (ok) { console.log(`✅ ${name}`); pass++; } else { console.log(`❌ ${name}`); fail++; } };

  // 1. Backend health
  try { const r = await fetch(BACKEND, '/api/v1/health'); t('Backend health', r.status === 200); } catch { t('Backend health', false); }

  // 2. Frontend API proxy
  try { const r = await fetch(FRONTEND, '/api/v1/health'); t('Frontend API proxy', r.status === 200); } catch { t('Frontend API proxy', false); }

  // 3. Frontend HTML no crossorigin
  try { const r = await fetch(FRONTEND, '/'); t('HTML no crossorigin', !r.body.includes('crossorigin')); } catch { t('HTML no crossorigin', false); }

  // 4. Backend market/quotes (may need symbols)
  try { const r = await fetch(BACKEND, '/api/v1/market/quotes'); t('Backend quotes reachable', r.status === 200 || r.status === 422); } catch { t('Backend quotes reachable', false); }

  // 5. Frontend proxy market/quotes
  try { const r = await fetch(FRONTEND, '/api/v1/market/quotes'); t('Proxy quotes reachable', r.status === 200 || r.status === 422); } catch { t('Proxy quotes reachable', false); }

  // 6. React mounted
  try { const c = await cdpEval('document.getElementById("root").children.length'); t('React mounted', c > 0); } catch (e) { t(`React mounted (${e})`, false); }

  // 7. No flicker: check backendConnected state is stable
  try {
    const v1 = await cdpEval('document.body.innerText.substring(0, 100)');
    await new Promise(r => setTimeout(r, 3000));
    const v2 = await cdpEval('document.body.innerText.substring(0, 100)');
    const stable = v1 === v2;
    t('No flicker (3s stable)', stable);
  } catch (e) { t(`No flicker (${e})`, false); }

  // 8. Not stuck on loading screen
  try {
    const text = await cdpEval('document.body.innerText');
    const onLoading = text.includes('正在初始化') || text.includes('正在连接后端');
    t('Past loading screen', !onLoading);
  } catch (e) { t(`Past loading screen (${e})`, false); }

  console.log(`\n===== ${pass} passed, ${fail} failed =====`);
  process.exit(fail > 0 ? 1 : 0);
}
run().catch(e => { console.error(e); process.exit(1); });
