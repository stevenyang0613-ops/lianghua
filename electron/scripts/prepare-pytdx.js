const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

function findPytdx() {
  // 1. 通过 python3 动态探测 site-packages 路径
  try {
    const sitePackages = execSync('python3 -c "import site; print(site.getsitepackages()[0])"', { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'] }).trim();
    const pytdxPath = path.join(sitePackages, 'pytdx');
    if (fs.existsSync(pytdxPath)) return pytdxPath;
  } catch {}

  // 2. 探测 user site-packages
  try {
    const userSite = execSync('python3 -c "import site; print(site.getusersitepackages())"', { encoding: 'utf8', stdio: ['pipe', 'pipe', 'ignore'] }).trim();
    const pytdxPath = path.join(userSite, 'pytdx');
    if (fs.existsSync(pytdxPath)) return pytdxPath;
  } catch {}

  // 3. 探测项目内虚拟环境（多 Python 版本兼容）
  const cwd = process.cwd();
  const venvPatterns = [
    'backend/.venv/lib/python3.13/site-packages/pytdx',
    'backend/.venv/lib/python3.12/site-packages/pytdx',
    'backend/.venv/lib/python3.11/site-packages/pytdx',
    'backend/venv/lib/python3.13/site-packages/pytdx',
    'backend/venv/lib/python3.12/site-packages/pytdx',
    'backend/venv/lib/python3.11/site-packages/pytdx',
  ];
  for (const p of venvPatterns) {
    const full = path.join(cwd, p);
    if (fs.existsSync(full)) return full;
  }

  return null;
}

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function main() {
  const pytdx = findPytdx();
  if (!pytdx) {
    console.log('[prepare-pytdx] pytdx not found, skipping');
    process.exit(0);
  }

  const target = path.join(process.cwd(), 'backend', 'pytdx');
  if (fs.existsSync(target)) {
    fs.rmSync(target, { recursive: true, force: true });
  }
  copyDir(pytdx, target);
  console.log(`[prepare-pytdx] Copied pytdx from ${pytdx} to ${target}`);
}

main();
