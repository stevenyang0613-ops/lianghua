# LiangHua Electron Desktop App

可转债量化交易系统桌面端应用

## 功能特性

### 窗口管理
- ✅ 自定义标题栏（Windows/Linux）
- ✅ 原生标题栏（macOS）
- ✅ 最小化到系统托盘
- ✅ 双击托盘图标显示/隐藏窗口
- ✅ 窗口置顶功能
- ✅ 全屏模式支持

### 菜单系统
- ✅ 完整的应用菜单栏
- ✅ 快捷键支持（Cmd/Ctrl+1-6 切换页面）
- ✅ 上下文菜单（托盘菜单）
- ✅ 开发者工具快捷键（F12）

### 系统集成
- ✅ 原生通知推送
- ✅ 系统托盘图标
- ✅ 全局快捷键（Alt+Cmd/Ctrl+L 显示/隐藏）
- ✅ 外部链接用默认浏览器打开
- ✅ 自动重启 Python 后端

### IPC 通信
- ✅ 主进程 ↔ 渲染进程双向通信
- ✅ 菜单导航事件
- ✅ 数据刷新事件
- ✅ 窗口状态同步

## 快捷键列表

| 快捷键 | 功能 |
|--------|------|
| Cmd/Ctrl+1 | 首页 |
| Cmd/Ctrl+2 | 市场行情 |
| Cmd/Ctrl+3 | 交易策略 |
| Cmd/Ctrl+4 | 回测分析 |
| Cmd/Ctrl+5 | 交易终端 |
| Cmd/Ctrl+6 | 信号监控 |
| Cmd/Ctrl+R | 刷新数据 |
| Cmd/Ctrl+E | 导出报告 |
| Cmd/Ctrl+D | 自选股 |
| Cmd/Ctrl+P | 盈亏分析 |
| Cmd/Ctrl+, | 偏好设置 |
| Cmd/Ctrl+/ | 快捷键帮助 |
| F11 | 全屏切换 |
| F12 | 开发者工具 |
| Alt+Cmd/Ctrl+L | 显示/隐藏窗口（全局）|

## 构建步骤

### 开发模式

```bash
# 1. 安装依赖
npm install

# 2. 编译 Electron TypeScript
npm run build:electron-ts

# 3. 启动开发服务器（前端 + Electron）
npm run dev:electron
```

### 生产构建

```bash
# 构建所有平台
npm run build:electron

# 仅构建 macOS
npm run build:mac

# 仅构建 Windows
npm run build:win

# 仅构建 Linux
npm run build:linux
```

## 项目结构

```
electron/
├── main.ts          # 主进程入口
├── preload.ts       # 预加载脚本（安全桥接）
├── tsconfig.json    # TypeScript 配置
└── dist/            # 编译输出目录

frontend/src/
├── components/electron/
│   ├── TitleBar.tsx          # 自定义标题栏组件
│   └── TitleBar.module.css   # 标题栏样式
├── hooks/
│   └── useElectron.ts        # Electron 集成 Hook
├── utils/
│   └── electron.ts           # Electron 工具函数
└── styles/
    └── electron.css          # Electron 全局样式

shared/types/
└── electron.d.ts    # TypeScript 类型定义
```

## 注意事项

1. **macOS**: 使用原生标题栏，不需要自定义标题栏组件
2. **Windows/Linux**: 使用自定义标题栏，提供更好的视觉体验
3. **Python 后端**: Electron 会自动启动和管理 Python 后端进程
4. **系统托盘**: 关闭窗口会最小化到托盘，不会退出应用

## 开发调试

- 按 `F12` 打开开发者工具
- 查看 Console 标签页的 `[Python]` 和 `[Electron]` 日志
- 使用 `window.electronAPI` 访问 Electron API
