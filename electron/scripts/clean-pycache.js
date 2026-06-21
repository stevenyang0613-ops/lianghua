#!/usr/bin/env node
/**
 * 递归清理 backend/app 目录下的 Python 缓存文件
 * 清理范围：__pycache__ 目录、.pyc/.pyo 文件、*.egg-info 目录
 * 跨平台兼容：纯 Node.js fs API，不依赖 find/rimraf 等外部工具
 */
const { rmSync, existsSync, readdirSync, statSync } = require('fs')
const path = require('path')

// 候选路径：
// 1. Electron .app bundle: Resources/backend/app（__dirname 是 scripts/，上两级到 app root）
// 2. 项目开发环境: ../../backend/app（scripts/ → electron/ → project root → backend/app）
const candidates = [
  path.join(__dirname, '..', 'backend', 'app'),           // .app bundle
  path.join(__dirname, '..', '..', 'backend', 'app'),     // 项目根目录
]

const backendAppDir = candidates.find(p => existsSync(p))

if (!backendAppDir) {
  console.warn('Warning: backend/app directory not found at any candidate path:')
  candidates.forEach(p => console.warn('  -', p))
  console.warn('This is normal if running from inside an Electron .app bundle or during CI.')
  process.exit(0)
}

// 需要删除的文件扩展名
const CLEANUP_EXTENSIONS = new Set(['.pyc', '.pyo'])

// 需要删除的目录名（后缀匹配）
const CLEANUP_DIR_SUFFIXES = ['.egg-info']

let removedDirs = 0
let removedFiles = 0

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

    // 清理 .egg-info 等后缀目录
    if (CLEANUP_DIR_SUFFIXES.some(suffix => entry.endsWith(suffix))) {
      try {
        const stat = statSync(fullPath)
        if (stat.isDirectory()) {
          rmSync(fullPath, { recursive: true })
          removedDirs++
        }
      } catch (e) {
        console.warn(`Warning: Failed to remove ${fullPath}: ${e.message}`)
      }
      continue
    }

    // 清理 .pyc/.pyo 文件
    const ext = path.extname(entry)
    if (CLEANUP_EXTENSIONS.has(ext)) {
      try {
        rmSync(fullPath)
        removedFiles++
      } catch (e) {
        console.warn(`Warning: Failed to remove ${fullPath}: ${e.message}`)
      }
      continue
    }

    // 递归子目录
    try {
      if (statSync(fullPath).isDirectory()) {
        cleanPycache(fullPath)
      }
    } catch (e) {
      // 权限不足等，跳过
    }
  }
}

console.log('Cleaning Python cache from', backendAppDir)
cleanPycache(backendAppDir)
console.log(`Done: removed ${removedDirs} directories, ${removedFiles} files`)
