# Frontend TypeScript/React 潜在 Bug 扫描报告

扫描范围: `/Users/mac/lianghua/frontend/src` 下的所有 `.ts` / `.tsx` 文件
扫描重点: React Hooks、内存泄漏、竞态条件、类型安全、状态管理、性能、第三方库集成

---

## P0 🔴 useEffect cleanup 中调用 marketWs.disconnect() 导致全局 WS 被断开

- **文件**: `frontend/src/hooks/useWebSocket.ts`
- **行号**: `61-70`
- **类别**: React Hooks / 全局状态污染

**问题描述**: marketWs 是全局共享的 WebSocket 单例。任何使用 useWebSocket 的组件卸载时都会调用 marketWs.disconnect()，这会断开所有其他组件的行情连接。当 Market 页面切换到其他页面再切回时，WS 被断开且不会自动重连（除非其他机制触发）。

**修复建议**: cleanup 中只应取消订阅（unsubMsg()），不应调用 disconnect()。全局 WS 的生命周期应由 App.tsx 统一管理。

---

## P0 🔴 ECharts 实例在组件卸载时未 dispose

- **文件**: `frontend/src/pages/DataPlayer.tsx`
- **行号**: `57-61`
- **类别**: 第三方库集成 / ECharts 实例泄漏

**问题描述**: useEffect(() => { if (chartRef.current && !chartInstance.current) { chartInstance.current = echarts.init(...) } }, [frames.length > 0]) 没有返回 cleanup 函数。当 DataPlayer 页面卸载时，ECharts 实例和底层 Canvas 渲染上下文、事件监听器全部泄漏。

**修复建议**: 添加 cleanup: return () => { chartInstance.current?.dispose(); chartInstance.current = null }

---

## P0 🔴 new Audio() 没有保存引用，无法释放音频资源

- **文件**: `frontend/src/utils/notifications.ts:180, frontend/src/utils/desktopNotifications.ts:169, frontend/src/services/risk/AlertEngine.ts:360`
- **行号**: `多处`
- **类别**: 资源泄漏 / Audio 对象

**问题描述**: 每次播放提示音都创建 new Audio() 对象，但没有任何地方保存引用或调用 pause()/将 src 设为空。在高频预警场景下，浏览器会积累大量 Audio 对象和音频解码资源，导致内存泄漏。

**修复建议**: 使用 Audio 对象池或单例模式：const audio = new Audio(src); audio.play().catch(() => {}); 在不需要时 audio.pause(); audio.src = ''

---

## P0 🔴 loadStrategies 的递归重试 setTimeout 在组件卸载后未清理

- **文件**: `frontend/src/pages/Backtest.tsx`
- **行号**: `45-68`
- **类别**: 竞态条件 / 组件卸载后 setState

**问题描述**: catch 中 setTimeout(() => loadStrategies(retries - 1), 2000) 如果组件卸载后触发，会调用已卸载组件的 setState。虽然 React 不会 crash，但会在 development 模式下触发警告，且代码逻辑无意义地执行。

**修复建议**: 在组件内部用 useRef 保存 timeoutId，在 useEffect cleanup 中 clearTimeout(timeoutId)。

---

## P0 🔴 handleLoadReplay 中的 setTimeout 在组件卸载后未清理

- **文件**: `frontend/src/pages/StrategyReplay.tsx`
- **行号**: `54-59`
- **类别**: 竞态条件 / 组件卸载后 setState

**问题描述**: setTimeout(() => { setSteps(data); setLoading(false); ... }, 500) 在组件卸载后仍会执行 setSteps 和 setLoading。虽然 DataPlayer.tsx 和 StrategyReplay.tsx 的 useEffect 中有 unsubscribe 逻辑，但 setTimeout 中的 setState 在组件卸载后仍会被调用。

**修复建议**: 使用 isMountedRef 标志或在 cleanup 中 clearTimeout。

---

## P0 🔴 模块级别 WS 订阅在 React StrictMode 下丢失

- **文件**: `frontend/src/stores/useAppStore.ts`
- **行号**: `17-26`
- **类别**: 内存泄漏 / 全局事件监听

**问题描述**: _unsub1 和 _unsub2 在模块加载时立即注册。在 React StrictMode 下，App.tsx 的 useEffect 会执行两次（mount -> cleanup -> mount）。cleanup 中调用 cleanupWsListeners() 会取消订阅，但重新挂载时模块代码不会重新执行，导致 WS 状态监听器永久丢失。

**修复建议**: 将 init 逻辑移到 App.tsx 的 useEffect 中，而非模块级别副作用。

---

## P0 🔴 window.fetch 拦截器的并发恢复问题

- **文件**: `frontend/src/components/PerformanceMonitor.tsx`
- **行号**: `180-253`
- **类别**: 内存泄漏 / 全局 fetch 拦截

**问题描述**: 使用 _fetchOverrideDepth 全局计数器管理 fetch 覆盖。在 StrictMode 下组件双重挂载时，depth 增加到 2，cleanup 时减少为 1，不会恢复原始 fetch。如果另一个组件或外部代码也覆盖了 fetch，可能导致恢复逻辑错误。更严重的是，如果组件 crash 了，第二个 useEffect (line 245) 的 cleanup 会恢复 fetch，但如果 crash 发生在第一个 effect 的 wrappedFetch 执行期间，overrideActiveRef 为 true 但第一个 effect 的 cleanup 不会执行。

**修复建议**: 移除全局计数器，使用更安全的单例封装或仅在 enabled 为 true 时覆盖。

---

## P0 🔴 while 循环中多个 await setTimeout 在组件卸载后仍触发 setState

- **文件**: `frontend/src/components/StartupLoading.tsx`
- **行号**: `180-289`
- **类别**: 竞态条件 / 定时器泄漏

**问题描述**: check() 函数内部有多个 await new Promise((r) => setTimeout(r, ...))。虽然 cancelled 标志在 await 后检查，但 setStep/setProgress 在循环开始处（line 188）没有 if (!cancelled) 保护。如果组件在 while 循环中途卸载，stepInterval 会被 cleanup 清除，但 await 后的代码会继续执行到 cancelled 检查点。虽然大部分 setState 在 cancelled 检查后被跳过，但 line 188 的 setProgress 没有保护。

**修复建议**: 在每次 setState 前都检查 if (!cancelled && isMountedRef.current)。

---

## P1 🟠 useEffect 依赖 [api, navigate] 可能导致频繁重新注册 IPC 监听器

- **文件**: `frontend/src/hooks/useElectron.ts`
- **行号**: `45-62`
- **类别**: React Hooks / 依赖数组不稳定

**问题描述**: api 是 window.electronAPI（引用稳定），但 navigate 来自 useNavigate()。虽然 React Router 的 useNavigate 返回稳定引用，但在某些路由上下文变化时可能导致重新注册。每次重新注册时，先取消旧的再注册新的，可能导致短暂的 listener 空窗期。

**修复建议**: 将 navigate 包在 useRef 中，effect 依赖只留 [api]。

---

## P1 🟠 onChartReady 不稳定导致 ECharts 频繁重新初始化

- **文件**: `frontend/src/components/charts/BaseChart.tsx`
- **行号**: `71-83`
- **类别**: React Hooks / 性能问题

**问题描述**: useEffect(() => { echarts.init(...); ... }, [theme, onChartReady]) 中 onChartReady 是函数 prop。如果父组件每次渲染传递新的函数引用（如内联箭头函数），ECharts 实例会被销毁并重建。这会导致明显的性能问题和 Canvas 资源泄漏。

**修复建议**: 使用 useRef 保存 onChartReady，或从 effect 依赖中移除。

---

## P1 🟠 ECharts 初始化与 cleanup 分离导致竞态条件

- **文件**: `frontend/src/components/KlineChart.tsx`
- **行号**: `63-248`
- **类别**: React Hooks / 闭包陷阱

**问题描述**: 初始化在 useEffect([data, showMA, maPeriods]) 中，cleanup 在 useEffect([]) 中。如果 data 快速变化，第一个 effect 会重复调用 setOption，但如果在 StrictMode 下组件双重挂载，cleanup 会先 dispose，然后 data effect 会尝试在已 dispose 的实例上 setOption。虽然代码中有 if (!chartInstance.current) 保护，但 chartInstance.current 在 cleanup 后被设为 null，重挂载时 data effect 会重新初始化。然而在极端情况下，如果 data 在 cleanup 和初始化之间变化，可能导致异常。

**修复建议**: 将初始化和 cleanup 放在同一个 useEffect 中。

---

## P1 🟠 useLongPress 中 timeoutRef 类型声明为 NodeJS.Timeout

- **文件**: `frontend/src/hooks/useResponsive.ts`
- **行号**: `60`
- **类别**: 类型安全 / 跨平台兼容性

**问题描述**: timeoutRef.current: NodeJS.Timeout 在浏览器环境中实际上应该是 number（ReturnType<typeof setTimeout>）。虽然 TypeScript 编译时可能通过（因为 NodeJS.Timeout 和 number 在某些配置下兼容），但这不是正确的类型。clearTimeout(timeoutRef.current) 在浏览器中传入 NodeJS.Timeout 类型虽然在运行时工作，但类型不安全。

**修复建议**: 改为 ReturnType<typeof setTimeout> 或 number。

---

## P1 🟠 clearFiles 的 useCallback 依赖 [files] 导致频繁重新创建

- **文件**: `frontend/src/hooks/useFileDrop.ts`
- **行号**: `222-229`
- **类别**: React Hooks / 性能问题

**问题描述**: clearFiles 依赖 files 数组，每次 files 变化都会重新创建函数引用。更严重的是，clearFiles 遍历 files 并 revokeObjectURL，但如果 files 在 clearFiles 调用后变化（如用户继续拖放），新添加的 preview URL 不会被释放。

**修复建议**: 使用 useRef 保存 files，或确保在组件卸载时统一清理所有 preview URL。

---

## P1 🟠 loadImage 的 useCallback 依赖 [state.isLoading, state.src] 导致闭包陷阱

- **文件**: `frontend/src/hooks/useLazyImage.ts`
- **行号**: `56-92`
- **类别**: React Hooks / 闭包陷阱

**问题描述**: loadImage 依赖 state.isLoading 和 state.src，这意味着每次 state 变化都会重新创建 loadImage。IntersectionObserver 的 useEffect 依赖 [threshold, rootMargin, loadImage]，因此每次 state 变化都会重新创建 observer。虽然 observer.disconnect() 在 cleanup 中执行，但如果图片在加载过程中 state 变化，observer 会被重新创建，可能导致重复加载或内存泄漏。

**修复建议**: 将 state 依赖改为 ref，或使用更稳定的依赖。

---

## P1 🟠 单例引擎在组件卸载后继续通知已卸载的 listener

- **文件**: `frontend/src/utils/dataPlayer.ts / frontend/src/utils/strategyReplay.ts`
- **行号**: `161-182 / 132-153`
- **类别**: 竞态条件 / 组件卸载后回调

**问题描述**: dataPlayer 和 replayEngine 是全局单例。DataPlayer.tsx 和 StrategyReplay.tsx 的 useEffect 中注册了 onFrame/onStep 监听器，cleanup 中 unsubscribe。但如果引擎在组件卸载前已经开始播放（playInterval 在运行），组件卸载后如果引擎没有 stop，虽然 React 组件的 state 更新会被忽略，但 listener 的引用仍然留在引擎的 Set 中。如果组件反复挂载/卸载，Set 中会积累大量过期的 listener 引用。

**修复建议**: 在组件卸载时确保调用 engine.stop() 清空所有 listener，或在引擎中提供 clearListeners() 方法。

---

## P1 🟠 内存监控 interval 每 2 秒触发 setMetrics，可能导致频繁重渲染

- **文件**: `frontend/src/components/PerformanceMonitor.tsx`
- **行号**: `156-177`
- **类别**: React Hooks / 依赖数组问题

**问题描述**: setInterval 每 2 秒调用 memoryMonitor.record() 和 setMetrics(prev => ({...}))。如果 PerformanceMonitor 的 enabled 状态变化，interval 会重新创建。虽然 cleanup 会 clearInterval，但如果 enabled 快速切换，可能导致多个 interval 同时运行（虽然 React 的 cleanup 机制通常能处理）。

**修复建议**: 使用 ref 存储 metrics，只在需要渲染时更新 state。或者增加防抖。

---

## P1 🟠 useMemo(() => loadConfig(), []) 在首次渲染时调用 loadConfig

- **文件**: `frontend/src/pages/ScoreRanking.tsx`
- **行号**: `76`
- **类别**: React Hooks / 性能问题

**问题描述**: loadConfig 读取 localStorage 并在 JSON 解析失败时静默忽略。虽然 useMemo 的依赖是 [] 只会执行一次，但如果 localStorage 数据损坏，静默失败可能导致配置丢失。更关键的是，savedConfig 被用于初始化 state，但后续 localStorage 变化不会同步。

**修复建议**: 添加 JSON 解析失败的日志警告，并考虑使用 storage 事件监听外部变化。

---

## P1 🟠 registerServiceWorker 中的 window.addEventListener('load') 没有 cleanup

- **文件**: `frontend/src/App.tsx`
- **行号**: `75-86`
- **类别**: 全局事件监听 / 未清理

**问题描述**: window.addEventListener('load', () => { ... }, { once: true }) 在 App.tsx 的 useEffect 中通过 registerServiceWorker() 注册。虽然 { once: true } 会在触发后自动移除，但如果 App 在 load 事件触发前卸载（如快速切换应用），listener 会残留。更严重的是，App 的 cleanup 中没有任何地方移除这个 listener。

**修复建议**: 将 registerServiceWorker 返回一个 cleanup 函数，在 App.tsx 的 cleanup 中调用。

---

## P1 🟠 reportError 在 componentDidCatch 中未 await

- **文件**: `frontend/src/components/ErrorBoundary.tsx`
- **行号**: `131-163`
- **类别**: 竞态条件 / 错误边界

**问题描述**: componentDidCatch 调用 this.reportError(error, errorInfo) 但没有 await。reportError 是 async 方法，内部调用 this.setState({ reportSent: true })。虽然 setState 在组件卸载后不会 crash，但如果组件在 reportError 完成前被卸载，setState 会在 development 模式下警告。更关键的是，reportError 中使用了 navigator.onLine 检查，如果网络状态在 async 边界变化，可能导致不一致。

**修复建议**: 在 componentWillUnmount 中设置标志，reportError 中检查标志后再 setState。

---

## P1 🟠 ResizeObserver 在 containerRef 变化时未 unobserve 旧元素

- **文件**: `frontend/src/components/VirtualTable.tsx`
- **行号**: `82-94`
- **类别**: React Hooks / 性能问题

**问题描述**: useEffect(() => { observer.observe(containerRef.current); return () => observer.disconnect() }, []) 中，如果 containerRef.current 在组件生命周期中变化（虽然 React ref 通常不会变化），observer 没有 unobserve 旧元素。虽然通常这不是问题，但在某些动态布局场景下可能导致 observer 监听错误的元素。

**修复建议**: 在 cleanup 中调用 observer.disconnect() 已足够，但最好在 observe 前保存 element 引用。

---

## P1 🟠 useAutoRefresh 的 ms 参数变化时重新创建 interval 但 loadData 通过 ref 更新

- **文件**: `frontend/src/pages/Analysis.tsx`
- **行号**: `17-24`
- **类别**: React Hooks / 依赖数组问题

**问题描述**: useAutoRefresh 的 savedCb.current 在每次渲染时更新，这是正确的。但如果 ms 参数频繁变化，interval 会不断被清除和重新创建。在 ForcedRedemptionTab 等组件中，useAutoRefresh 的 ms 是常量（60000/10000），所以这不是实际问题。

**修复建议**: 如果 ms 确实会动态变化，当前实现是正确的。但如果 ms 是常量，可以移除 useEffect 的 ms 依赖。

---

## P1 🟠 onBackendReady 的 cleanup 在 StrictMode 下可能丢失

- **文件**: `frontend/src/components/StartupLoading.tsx`
- **行号**: `100-115`
- **类别**: 竞态条件 / 组件卸载后 setState

**问题描述**: window.electronAPI?.onBackendReady?.((data: any) => { ... }) 返回 cleanup 函数。在 StrictMode 下，useEffect 执行两次，第一次的 cleanup 会取消监听器，第二次会重新注册。但如果 electronAPI 在第一次 mount 时存在，第二次 mount 时由于某些原因不存在（不太可能），cleanup 会失败。

**修复建议**: 确保 cleanup 函数在 electronAPI 不存在时也能安全执行。

---

## P2 🟡 大量 any 类型使用导致运行时类型安全缺失

- **文件**: `多处（如 frontend/src/services/api.ts, frontend/src/components/BacktestHistoryTab.tsx, frontend/src/pages/ScoreRanking.tsx）`
- **行号**: `大量`
- **类别**: 类型安全 / any 滥用

**问题描述**: services/api.ts 中有大量 any 类型（如 result?: any, strategy: any, data: any[] 等）。组件中也有大量 any（如 BacktestHistoryTab.tsx 的 cols: any[], r: any 等）。这掩盖了潜在的类型错误，导致运行时崩溃难以在编译时发现。

**修复建议**: 逐步替换为明确的类型定义，使用 unknown 替代 any，配合类型守卫。

---

## P2 🟡 const option: any = {...}

- **文件**: `frontend/src/components/KlineChart.tsx`
- **行号**: `102`
- **类别**: 类型安全 / 类型断言

**问题描述**: KlineChart.tsx 中 ECharts 配置对象被声明为 any，失去了类型检查。这可能导致配置项拼写错误、数据格式错误等无法在编译时发现。

**修复建议**: 使用 echarts.EChartsOption 类型，或导入具体的 ECharts 配置类型。

---

## P2 🟡 模块级别的 bondsCache 和 bondsUpdateTimer 无法真正被销毁

- **文件**: `frontend/src/stores/useMarketStore.ts`
- **行号**: `5-11`
- **类别**: 代码质量 / 模块级别副作用

**问题描述**: bondsCache 和 bondsUpdateTimer 是模块级别变量。destroy() 方法只清除 timer，但 bondsCache 不会被清空。在测试环境中，如果多次创建/销毁 store，旧数据会残留。

**修复建议**: 在 destroy() 中同时清空 bondsCache。

---

## P2 🟡 模块级别的 wsSubCleanups、_wsRefCount 等变量在测试环境中可能状态污染

- **文件**: `frontend/src/stores/useSignalStore.ts / useScoreStore.ts / useXuanjiStore.ts`
- **行号**: `模块级别变量`
- **类别**: 代码质量 / 模块级别副作用

**问题描述**: 这些 zustand stores 使用模块级别的 refCount 和 cleanup 数组来管理 WS 订阅。在 jest 测试环境中，如果多个测试文件导入这些模块，模块状态会在测试间共享，导致测试不稳定。

**修复建议**: 在测试 setup 中重置模块状态，或提供显式的 reset 方法。

---

## P2 🟡 useHotkey 的依赖 [id, keys, handler, options] 可能导致频繁重新注册

- **文件**: `frontend/src/utils/hotkeys.ts`
- **行号**: `363-389`
- **类别**: 代码质量 / 全局事件监听

**问题描述**: options 是对象，handler 是函数。如果父组件每次渲染都创建新的引用，会导致频繁重新注册。虽然 cleanup 会取消旧的，但频繁的注册/取消注册在大量快捷键场景下可能影响性能。

**修复建议**: 对 options 进行 useMemo 稳定化，或使用 useRef 保存 handler。

---

## P2 🟡 每个 ErrorBoundary 实例都注册全局 unhandledrejection 监听器

- **文件**: `frontend/src/components/ErrorBoundary.tsx`
- **行号**: `117-124`
- **类别**: 代码质量 / 事件监听管理

**问题描述**: componentDidMount 中 window.addEventListener('unhandledrejection', this.rejectionHandler)。如果页面中有多个 ErrorBoundary（如 App.tsx 中每个 Route 都包裹了一个），每个都会注册监听器。虽然 cleanup 会移除，但在路由快速切换时可能导致短暂的多重监听。

**修复建议**: 使用全局单例模式，或仅在根组件注册一个全局监听器。

---

## P2 🟡 virtualColumns 的 useMemo 依赖 staticColumnDefs 和 columnSort

- **文件**: `frontend/src/pages/Market.tsx`
- **行号**: `232-237`
- **类别**: 性能优化 / 未使用 memo

**问题描述**: staticColumnDefs 是 useMemo([], []) 创建的，引用稳定。columnSort 是 state，变化时 virtualColumns 会重新计算。虽然这是正确的，但 staticColumnDefs 中的 render 函数在每次创建时都是新的函数引用，如果 VirtualTable 内部没有正确处理引用稳定性，可能导致不必要的重渲染。

**修复建议**: staticColumnDefs 中的 render 函数使用 useCallback 或移到组件外部。

---

## P2 🟡 DecompressionStream 在旧版浏览器中不支持

- **文件**: `frontend/src/utils/wsReconnect.ts`
- **行号**: `374-404`
- **类别**: 代码质量 / 错误处理

**问题描述**: handleMessage 中使用了 DecompressionStream('gzip') 来解压二进制数据。这在 Safari 15 之前或某些旧版浏览器中不支持。虽然 try/catch 会捕获错误并回退到 TextDecoder，但回退逻辑假设数据是未压缩的文本，如果实际收到的是压缩数据，会解析失败。

**修复建议**: 提供 pako 或 fflate 的 polyfill，确保在所有浏览器中正确解压。

---

## P2 🟡 requestIdleCallback polyfill 的 setTimeout 没有保存引用

- **文件**: `frontend/src/utils/performanceOptimization.ts`
- **行号**: `180-189`
- **类别**: 代码质量 / 资源管理

**问题描述**: deferLoad 中使用 requestIdleCallback 或 setTimeout 处理延迟加载，但没有保存 timer 引用。如果组件在 setTimeout 触发前卸载，回调仍可能执行并尝试加载资源。

**修复建议**: 保存 setTimeout 的返回值，提供 cleanup 方法。

---

## P2 🟡 rankingInfo: any 和 rankingParams: any 丢失类型安全

- **文件**: `frontend/src/stores/useXuanjiStore.ts`
- **行号**: `17-19`
- **类别**: 代码质量 / 类型定义

**问题描述**: XuanjiState 中 rankingInfo 和 rankingParams 使用 any 类型，导致后续使用时没有类型检查。

**修复建议**: 定义明确的接口类型。

---

## P2 🟡 startConnectionTimeout 和 clearConnectionTimeout 的重复清理逻辑

- **文件**: `frontend/src/utils/wsReconnect.ts`
- **行号**: `339-349`
- **类别**: 代码质量 / 重复定义

**问题描述**: connectViaIPC 中在多个路径（成功、失败、超时）都调用 clearConnectionTimeout，虽然逻辑正确，但存在重复代码。更关键的是，如果 connectViaIPC 被快速调用多次，旧的 connectionTimer 可能不会被清除（虽然 connectViaIPC 中 _connectSeq 会过滤旧事件）。

**修复建议**: 抽象为统一的连接状态机。

---

## 总结

- 严重问题 (P0): 8 个
- 中等问题 (P1): 14 个
- 轻微问题 (P2): 11 个
- **总计**: 33 个问题

建议优先修复 P0 问题，特别是 `useWebSocket.ts` 的全局 WS 断开和 `DataPlayer.tsx` 的 ECharts 泄漏。