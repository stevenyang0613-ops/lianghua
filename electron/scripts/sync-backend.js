#!/usr/bin/env node
/**
 * 将 backend/app/ 同步到 Electron .app bundle 的 Resources/backend/app/
 * 并清除 __pycache__，避免 AGENTS.md #50 描述的"源码修改但 bundle 不更新"问题。
 *
 * 用法: node scripts/sync-backend.js [--dev|--prod]
 *   --dev  同步到 release-dev 目录
 *   --prod 同步到 release 目录
 */
const { cpSync, existsSync, mkdirSync, rmSync, readdirSync, statSync } = require('fs')
const path = require('path')

const mode = process.argv.includes('--prod') ? 'prod' : 'dev'
const projectRoot = path.join(__dirname, '..', '..')
const backendAppDir = path.join(projectRoot, 'backend', 'app')

if (!existsSync(backendAppDir)) {
  console.error('Error: backend/app not found at', backendAppDir)
  process.exit(1)
}

// 查找 .app bundle
const releaseDir = mode === 'prod' ? 'release' : 'release-dev'
const electronDir = path.join(__dirname, '..')
const releasePath = path.join(electronDir, releaseDir)

if (!existsSync(releasePath)) {
  console.warn(`Warning: ${releaseDir}/ directory not found — skipping sync`)
  console.warn('This is normal before the first build.')
  process.exit(0)
}

// 查找 .app
const { readdirSync: ls } = require('fs')
const appDir = ls(releasePath).find(d => d.endsWith('.app'))
if (!appDir) {
  console.warn(`Warning: No .app bundle found in ${releasePath} — skipping sync`)
  process.exit(0)
}

const bundleAppDir = path.join(releasePath, appDir, 'Contents', 'Resources', 'backend', 'app')

if (!existsSync(bundleAppDir)) {
  console.warn(`Warning: Bundle backend/app not found at ${bundleAppDir} — skipping sync`)
  process.exit(0)
}

// 同步 backend/app/ → bundle Resources/backend/app/
console.log(`Syncing backend/app/ → ${path.relative(projectRoot, bundleAppDir)}`)

// 递归复制
cpSync(backendAppDir, bundleAppDir, { recursive: true, force: true })

// 清除 __pycache__
let removedDirs = 0
function cleanPycache(dir) {
  if (!existsSync(dir)) return
  for (const entry of readdirSync(dir)) {
    const fullPath = path.join(dir, entry)
    if (entry === '__pycache__') {
      try {
        rmSync(fullPath, { recursive: true })
        removedDirs++
      } catch (e) {
        console.warn(`Warning: Failed to remove ${fullPath}: ${e.message}`)
      }
      continue
    }
    try {
      if (statSync(fullPath).isDirectory()) cleanPycache(fullPath)
    } catch {}
  }
}
cleanPycache(bundleAppDir)

console.log(`Done: synced backend/app, cleaned ${removedDirs} __pycache__ directories`)
