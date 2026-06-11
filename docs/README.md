# LiangHua 可转债量化交易系统

## 项目简介

LiangHua 是一个专业的可转债量化交易桌面应用，提供实时行情、交易信号、策略回测、风险管理等功能。

## 技术栈

- **前端**: React 18 + TypeScript + Vite
- **UI 框架**: Ant Design 5.x
- **图表**: ECharts 5.x
- **状态管理**: Zustand
- **桌面应用**: Electron 42
- **后端**: Python FastAPI

## 目录结构

```
lianghua/
├── frontend/                # 前端代码
│   ├── src/
│   │   ├── components/      # 组件
│   │   ├── pages/           # 页面
│   │   ├── stores/          # 状态管理
│   │   ├── hooks/           # 自定义 Hooks
│   │   ├── utils/           # 工具函数
│   │   ├── locales/         # 国际化
│   │   └── __tests__/       # 测试文件
│   └── public/              # 静态资源
├── backend/                 # 后端代码
├── docs/                    # 文档
└── release/                 # 打包输出
```

## 快速开始

### 安装依赖

```bash
npm install
cd frontend && npm install
```

### 开发模式

```bash
npm run dev
```

### 构建生产版本

```bash
npm run build
```

### 打包 Electron

```bash
npm run package:mac
npm run package:win
```

## 核心功能

### 1. 市场行情

- 实时可转债行情
- 技术指标分析
- 自选列表管理

### 2. 策略回测

- 历史数据回测
- 策略参数优化
- 收益分析报告

### 3. 交易信号

- 实时信号推送
- 信号历史记录
- 自定义信号策略

### 4. 风险控制

- 仓位管理
- 止损止盈
- 风险预警

## 配置说明

### 环境变量

创建 `.env` 文件:

```env
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws
```

### 主题配置

编辑 `src/styles/theme.ts` 自定义主题颜色。

## 测试

```bash
npm run test
npm run test:coverage
```

## 贡献指南

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建 Pull Request

## 许可证

MIT License
