const http = require('http');
const BACKEND = 8765;
const FRONTEND = 8766;

function fetch(port, path, method = 'GET') {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('timeout')), 5000);
    const opts = { hostname: '127.0.0.1', port, path, method, headers: { 'Content-Type': 'application/json' } };
    const req = http.request(opts, (res) => {
      let data = '';
      res.on('data', (c) => { data += c; });
      res.on('end', () => { clearTimeout(timer); resolve({ status: res.statusCode, body: data }); });
    });
    req.on('error', (e) => { clearTimeout(timer); reject(e); });
    req.end();
  });
}

async function run() {
  let pass = 0, fail = 0;
  const t = (name, ok) => { if (ok) { console.log(`✅ ${name}`); pass++; } else { console.log(`❌ ${name}`); fail++; } };

  // 1. Backend health
  try { const r = await fetch(BACKEND, '/api/v1/health'); t('Backend health', r.status === 200); } catch { t('Backend health', false); }

  // 2. Frontend proxy health
  try { const r = await fetch(FRONTEND, '/api/v1/health'); t('Frontend API proxy', r.status === 200); } catch { t('Frontend API proxy', false); }

  // 3. Frontend index.html (no crossorigin)
  try { const r = await fetch(FRONTEND, '/'); t('Frontend HTML no crossorigin', r.status === 200 && !r.body.includes('crossorigin')); } catch { t('Frontend HTML no crossorigin', false); }

  // 4. Backend market/quotes endpoint exists (may need symbols param)
  try {
    const r = await fetch(BACKEND, '/api/v1/market/quotes');
    t('Backend market/quotes reachable', r.status === 200 || r.status === 422);
  } catch { t('Backend market/quotes reachable', false); }

  // 5. Frontend proxy market/quotes
  try {
    const r = await fetch(FRONTEND, '/api/v1/market/quotes');
    t('Frontend proxy market/quotes', r.status === 200 || r.status === 422);
  } catch { t('Frontend proxy market/quotes', false); }

  // 6. Frontend JS asset loads
  try {
    const idx = await fetch(FRONTEND, '/');
    const m = idx.body.match(/src="\.\/assets\/([^"]+\.js)"/);
    if (m) { const r = await fetch(FRONTEND, `/assets/${m[1]}`); t('Frontend JS asset', r.status === 200); }
    else t('Frontend JS asset', false);
  } catch { t('Frontend JS asset', false); }

  console.log(`\n===== ${pass} passed, ${fail} failed =====`);
  process.exit(fail > 0 ? 1 : 0);
}
run().catch(e => { console.error(e); process.exit(1); });
