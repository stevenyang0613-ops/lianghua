import { useState, useMemo, useEffect, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { Menu, Button, Input, Popover } from 'antd'
import {
  StockOutlined,
  StarOutlined,
  ExperimentOutlined,
  DollarOutlined,
  FundProjectionScreenOutlined,
  DeploymentUnitOutlined,
  AlertOutlined,
  SettingOutlined,
  LeftOutlined,
  RightOutlined,
  ThunderboltOutlined,
  HistoryOutlined,
  BellOutlined,
  BankOutlined,
  FileTextOutlined,
  LineChartOutlined,
  SafetyOutlined,
  RobotOutlined,
  PlayCircleOutlined,
  ShopOutlined,
  DashboardOutlined,
  MessageOutlined,
  SkinOutlined,
  AppstoreOutlined,
  TrophyOutlined,
  CloudSyncOutlined,
  CrownOutlined,
  SwapOutlined,
  ApiOutlined,
  SearchOutlined,
  BarChartOutlined,
} from '@ant-design/icons'
import type { MenuProps } from 'antd'

type MenuItem = Required<MenuProps>['items'][number]

// ── localStorage key for openKeys persistence ──
const OPEN_KEYS_STORAGE_KEY = 'lianghua_sidebar_open_keys'

function loadOpenKeys(): string[] {
  try {
    const raw = localStorage.getItem(OPEN_KEYS_STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveOpenKeys(keys: string[]) {
  try {
    localStorage.setItem(OPEN_KEYS_STORAGE_KEY, JSON.stringify(keys))
  } catch { /* ignore quota / privacy mode errors */ }
}

// Debounced saveOpenKeys：高频展开/折叠时避免频繁同步 I/O
let _saveOpenKeysTimer: ReturnType<typeof setTimeout> | null = null
function saveOpenKeysDebounced(keys: string[]) {
  if (_saveOpenKeysTimer) clearTimeout(_saveOpenKeysTimer)
  _saveOpenKeysTimer = setTimeout(() => saveOpenKeys(keys), 300)
}

// ── 菜单分组定义 ──────────────────────

interface MenuGroup {
  key: string
  label: string
  icon: React.ReactNode
  children: { key: string; icon: React.ReactNode; label: string }[]
}

const menuGroups: MenuGroup[] = [
  {
    key: 'market',
    label: '行情 & 数据',
    icon: <StockOutlined />,
    children: [
      { key: '/', icon: <StockOutlined />, label: '实时行情' },
      { key: '/exchangeable', icon: <StockOutlined />, label: '可交换债' },
      { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
      { key: '/watchlist', icon: <StarOutlined />, label: '自选列表' },
      { key: '/mx-data', icon: <ApiOutlined />, label: '妙想MX数据' },
    ],
  },
  {
    key: 'trade',
    label: '交易',
    icon: <DollarOutlined />,
    children: [
      { key: '/trade', icon: <DollarOutlined />, label: '交易终端' },
      { key: '/paper-trade', icon: <PlayCircleOutlined />, label: '模拟交易' },
      { key: '/auto-trade', icon: <RobotOutlined />, label: '自动交易' },
      { key: '/trade-log', icon: <HistoryOutlined />, label: '交易日志' },
      { key: '/strategy-replay', icon: <LineChartOutlined />, label: '策略回放' },
      { key: '/accounts', icon: <BankOutlined />, label: '账户管理' },
    ],
  },
  {
    key: 'strategy',
    label: '策略 & 分析',
    icon: <ExperimentOutlined />,
    children: [
      { key: '/signals', icon: <AlertOutlined />, label: '交易信号' },
      { key: '/score-ranking', icon: <TrophyOutlined />, label: '评分排名' },
      { key: '/xibu-score', icon: <StarOutlined />, label: '七维详情分析' },
      { key: '/xuanji-index', icon: <CrownOutlined />, label: '璇玑十二因子' },
      { key: '/timing-signal', icon: <ThunderboltOutlined />, label: '多维度择时' },
      { key: '/sector-rotation', icon: <SwapOutlined />, label: '行业轮动' },
      { key: '/sector-rotation-stock', icon: <StockOutlined />, label: '行业轮动·股票版' },
      { key: '/backtest-results', icon: <BarChartOutlined />, label: '三大策略回测' },
      { key: '/backtest', icon: <ExperimentOutlined />, label: '回测中心' },
      { key: '/strategies', icon: <DeploymentUnitOutlined />, label: '策略管理' },
      { key: '/strategy-market', icon: <ShopOutlined />, label: '策略市场' },
    ],
  },
  {
    key: 'system',
    label: '系统',
    icon: <SettingOutlined />,
    children: [
      { key: '/alerts', icon: <BellOutlined />, label: '预警管理' },
      { key: '/risk', icon: <SafetyOutlined />, label: '风控管理' },
      { key: '/analysis', icon: <FundProjectionScreenOutlined />, label: '分析工具' },
      { key: '/reports', icon: <FileTextOutlined />, label: '报告中心' },
      { key: '/data-player', icon: <PlayCircleOutlined />, label: '数据回放' },
      { key: '/messages', icon: <MessageOutlined />, label: '消息中心' },
      { key: '/themes', icon: <SkinOutlined />, label: '主题商店' },
      { key: '/plugins', icon: <AppstoreOutlined />, label: '插件管理' },
      { key: '/sync', icon: <CloudSyncOutlined />, label: '数据同步' },
      { key: '/performance', icon: <ThunderboltOutlined />, label: '性能监控' },
      { key: '/data-source-monitor', icon: <CloudSyncOutlined />, label: '数据源监控' },
      { key: '/enrichment-dashboard', icon: <BarChartOutlined />, label: '数据富化看板' },
      { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
    ],
  },
]

// ── 扁平化索引 ──

const keyToGroup: Record<string, string> = {}
for (const g of menuGroups) {
  for (const child of g.children) {
    keyToGroup[child.key] = g.key
  }
}

// 模块级缓存：sortedKeys 不随路由变化，只需计算一次
const sortedKeysForPrefixMatch = Object.keys(keyToGroup).sort((a, b) => b.length - a.length)

/**
 * 根据当前路径找到所属分组 key
 * 先精确匹配，再按前缀匹配（如 /paper-trade/xxx 归属 trade 分组）
 */
function getGroupForPath(pathname: string): string | undefined {
  // 1. 精确匹配
  if (keyToGroup[pathname]) return keyToGroup[pathname]

  // 2. 前缀匹配：按 key 长度降序，优先匹配更具体的路径
  for (const key of sortedKeysForPrefixMatch) {
    if (key !== '/' && pathname.startsWith(key)) {
      return keyToGroup[key]
    }
  }

  // 3. 兜底：根路径归属 market
  return keyToGroup['/']
}

// ── 组件 ──────────────────────────────

interface SidebarProps {
  collapsed: boolean
  onCollapse: (v: boolean) => void
}

export default function Sidebar({ collapsed, onCollapse }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [search, setSearch] = useState('')
  const [searchPopoverOpen, setSearchPopoverOpen] = useState(false)

  const defaultOpenKeys = useMemo(
    () => (collapsed ? [] : menuGroups.map(g => g.key)),
    [collapsed]
  )

  // #2: localStorage 持久化 openKeys
  // 初始化时：确保当前路由所在的分组始终展开（即使用户之前折叠了）
  const [openKeys, setOpenKeys] = useState<string[]>(() => {
    const saved = loadOpenKeys()
    const base = saved.length > 0 ? saved : menuGroups.map(g => g.key)
    // 确保当前路由所在分组展开
    const currentGroup = getGroupForPath(window.location.pathname)
    if (currentGroup && !base.includes(currentGroup)) {
      return [...base, currentGroup]
    }
    return base
  })

  // 当路由变化时，自动展开新路由所在的分组，并清理无效的过期组
  // 使用函数式更新避免 openKeys 在依赖数组中导致不必要的 effect 重新执行
  useEffect(() => {
    const currentGroup = getGroupForPath(location.pathname)
    if (!currentGroup) return

    setOpenKeys(prev => {
      // 已包含当前组，无需变更
      if (prev.includes(currentGroup)) return prev

      // 清理无效组（不属于任何 menuGroups 的旧 session 残留）
      const validGroupKeys = new Set(menuGroups.map(g => g.key))
      const cleaned = prev.filter(k => validGroupKeys.has(k))
      return [...cleaned, currentGroup]
    })
  }, [location.pathname])

  // 持久化 openKeys 到 localStorage（统一入口，debounced 300ms 减少高频 I/O）
  useEffect(() => {
    saveOpenKeysDebounced(openKeys)
  }, [openKeys])

  // 当从折叠展开时，恢复保存的 keys
  useEffect(() => {
    if (!collapsed) {
      const saved = loadOpenKeys()
      // 确保当前路由分组也在 saved keys 中
      const currentGroup = getGroupForPath(location.pathname)
      if (saved.length > 0) {
        if (currentGroup && !saved.includes(currentGroup)) {
          saved.push(currentGroup)
        }
        setOpenKeys(saved)
      }
    }
  }, [collapsed, location.pathname])

  const selectedKey = location.pathname

  // 构建菜单 items（带搜索过滤）
  const menuItems: MenuItem[] = useMemo(() => {
    const q = search.trim().toLowerCase()
    return menuGroups
      .map(g => {
        const filtered = q
          ? g.children.filter(c => c.label.toLowerCase().includes(q))
          : g.children

        if (filtered.length === 0) return null

        return {
          key: g.key,
          icon: g.icon,
          label: g.label,
          children: filtered.map(c => ({ key: c.key, icon: c.icon, label: c.label })),
        } as MenuItem
      })
      .filter(Boolean) as MenuItem[]
  }, [search])

  // 搜索时自动展开所有含匹配项的 group
  const effectiveOpenKeys = useMemo(() => {
    if (!search.trim()) return openKeys
    return menuGroups
      .filter(g =>
        g.children.some(c => c.label.toLowerCase().includes(search.trim().toLowerCase()))
      )
      .map(g => g.key)
  }, [search, openKeys])

  const handleOpenChange = useCallback((keys: string[]) => {
    if (!search.trim()) {
      setOpenKeys(keys)
      // 持久化由统一的 useEffect 监听 openKeys 变化处理
    }
  }, [search])

  const handleClick: MenuProps['onClick'] = useCallback(({ key }: { key: string }) => {
    if (key.startsWith('/')) {
      navigate(key)
      if (search.trim()) setSearch('')
      setSearchPopoverOpen(false)  // #1: 关闭搜索弹窗
    }
  }, [navigate, search])

  // #1: 搜索框（展开态内嵌 / 折叠态 Popover）
  const searchNode = (
    <Input
      size="small"
      placeholder="搜索菜单..."
      prefix={<SearchOutlined style={{ color: '#bfbfbf' }} />}
      value={search}
      onChange={e => setSearch(e.target.value)}
      allowClear
      autoFocus={collapsed}  // 折叠态弹窗自动聚焦
    />
  )

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      {/* 搜索框 */}
      {collapsed ? (
        <div style={{ padding: '4px', textAlign: 'center' }}>
          <Popover
            trigger="click"
            placement="right"
            open={searchPopoverOpen}
            onOpenChange={setSearchPopoverOpen}
            content={<div style={{ width: 200 }}>{searchNode}</div>}
          >
            <Button type="text" size="small" icon={<SearchOutlined />} />
          </Popover>
        </div>
      ) : (
        <div style={{ padding: '8px 12px 4px' }}>{searchNode}</div>
      )}

      {/* 菜单区域 */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        <Menu
          mode="inline"
          inlineCollapsed={collapsed}
          selectedKeys={[selectedKey]}
          openKeys={effectiveOpenKeys}
          onOpenChange={handleOpenChange}
          items={menuItems}
          onClick={handleClick}
          style={{ borderRight: 0 }}
        />
      </div>

      {/* 收起按钮 */}
      <div
        style={{
          borderTop: '1px solid var(--border-color, #f0f0f0)',
          padding: '4px 0',
          textAlign: 'center',
        }}
      >
        <Button
          type="text"
          size="small"
          icon={collapsed ? <RightOutlined /> : <LeftOutlined />}
          onClick={() => onCollapse(!collapsed)}
          style={{ width: collapsed ? 60 : '100%', color: 'var(--text-color)' }}
        >
          {collapsed ? '' : '收起侧栏'}
        </Button>
      </div>
    </div>
  )
}
