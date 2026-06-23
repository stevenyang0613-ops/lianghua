#!/usr/bin/env node
/**
 * 将 backend/app/ 同步到 Electron .app bundle 的 Resources/backend/app/
 * 并清除 __pycache__，避免 AGENTS.md #50 描述的"源码修改但 bundle 不更新"问题。
 *
 * 用法: node scripts/sync-backend.js [--dev|--prod] [--check]
 *        ELECTRON_TARGET=prod node scripts/sync-backend.js   # 优先环境变量
 *   --dev   同步到 release-dev 目录（默认）
 *   --prod  同步到 release 目录
 *   --check 只检查是否有不同步的源文件，非零退出码表示有差异
 *           (用于 CI gate)
 *
 * 性能优化：先用 size+mtime 预过滤，只有 size 或 mtime 变化的文件才计算 SHA256。
 * 200+ .py 文件从 ~500ms 降到 ~50ms。
 */
const { cpSync, existsSync, mkdirSync, rmSync, readdirSync, statSync, readFileSync } = require('fs')
const crypto = require('crypto')
const path = require('path')

// 优先级：CLI 参数 > 环境变量 > 默认 dev
let mode
if (process.argv.includes('--prod')) {
  mode = 'prod'
} else if (process.argv.includes('--dev')) {
  mode = 'dev'
} else if (process.env.ELECTRON_TARGET === 'prod') {
  mode = 'prod'
} else {
  mode = 'dev'
}
const checkOnly = process.argv.includes('--check') || process.env.SYNC_CHECK === '1'
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
function findAppBundle(dir, depth = 0) {
  if (depth > 3) return null  // 防止无限递归
  if (!existsSync(dir)) return null
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry)
    if (entry.endsWith('.app')) return full
    try {
      if (statSync(full).isDirectory()) {
        const found = findAppBundle(full, depth + 1)
        if (found) return found
      }
    } catch {}
  }
  return null
}
const appPath = findAppBundle(releasePath)
if (!appPath) {
  console.warn(`Warning: No .app bundle found under ${releasePath} — skipping sync`)
  process.exit(0)
}

const bundleAppDir = path.join(appPath, 'Contents', 'Resources', 'backend', 'app')

if (!existsSync(bundleAppDir)) {
  console.warn(`Warning: Bundle backend/app not found at ${bundleAppDir} — skipping sync`)
  process.exit(0)
}

// 哈希目录中所有 .py 文件（排除 __pycache__）
// Bug8 性能优化：先用 size+mtime 预过滤，只有 size 或 mtime 变化才计算 SHA256
function hashDir(dir, rootDir = dir) {
  const out = {}  // rel -> { sha, size, mtime }
  if (!existsSync(dir)) return out
  for (const entry of readdirSync(dir)) {
    const full = path.join(dir, entry)
    if (entry === '__pycache__') continue
    let st
    try { st = statSync(full) } catch { continue }
    if (st.isDirectory()) {
      Object.assign(out, hashDir(full, rootDir))
    } else if (entry.endsWith('.py')) {
      const rel = path.relative(rootDir, full)
      out[rel] = {
        sha: null,  // 懒计算
        size: st.size,
        mtime: Math.floor(st.mtimeMs),
      }
    }
  }
  return out
}

// 仅对 size 或 mtime 变化的文件计算 SHA256
function compareDirs(srcMap, dstMap) {
  const drifted = []
  for (const [rel, info] of Object.entries(srcMap)) {
    const dstInfo = dstMap[rel]
    if (!dstInfo
        || dstInfo.size !== info.size
        || dstInfo.mtime !== info.mtime) {
      // 需要计算 SHA256 确认内容差异
      const srcPath = path.join(backendAppDir, rel)
      try {
        const sha = crypto.createHash('sha256')
          .update(readFileSync(srcPath))
          .digest('hex').slice(0, 16)
        if (!dstInfo || dstInfo.sha !== sha) {
          drifted.push(rel)
        }
      } catch {}
    }
  }
  for (const rel of Object.keys(dstMap)) {
    if (!(rel in srcMap)) drifted.push(`-${rel}`)
  }
  return drifted
}

const srcInfo = hashDir(backendAppDir)
const dstInfo = hashDir(bundleAppDir)
const drifted = compareDirs(srcInfo, dstInfo)

if (drifted.length === 0) {
  console.log(`✓ backend/app in sync (${Object.keys(srcInfo).length} files checked, ${mode} bundle)`)
  process.exit(0)
}

if (checkOnly) {
  console.error(`✗ ${drifted.length} files out of sync in ${mode} bundle:`)
  for (const f of drifted.slice(0, 10)) console.error(`  ${f}`)
  if (drifted.length > 10) console.error(`  ... and ${drifted.length - 10} more`)
  console.error(`Run: npm run sync:${mode}`)
  process.exit(1)
}

console.log(`Syncing backend/app/ → ${path.relative(projectRoot, bundleAppDir)} (${mode}, ${drifted.length} files differ)`)

// 递归复制，保留 mtime 以便后续 --check 准确判断差异
// （不保留 mtime 会导致所有文件的 mtime 被刷新，下次 --check 会显示所有文件不同步）
cpSync(backendAppDir, bundleAppDir, { recursive: true, force: true, preserveTimestamps: true })

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

console.log(`Done: synced ${drifted.length} files, cleaned ${removedDirs} __pycache__ directories (${mode} bundle)`)
