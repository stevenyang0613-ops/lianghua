import { useNavigate, useLocation } from 'react-router-dom'
import { Menu, Button } from 'antd'
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
} from '@ant-design/icons'

const menuItems = [
  { key: '/', icon: <StockOutlined />, label: '实时行情' },
  { key: '/exchangeable', icon: <StockOutlined />, label: '可交换债' },
  { key: '/dashboard', icon: <DashboardOutlined />, label: '数据看板' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选列表' },
  { key: '/signals', icon: <AlertOutlined />, label: '交易信号' },
  { key: '/score-ranking', icon: <TrophyOutlined />, label: '评分排名' },
  { key: '/songgang-score', icon: <StarOutlined />, label: '七维详情分析' },
  { key: '/timing-signal', icon: <ThunderboltOutlined />, label: '多维度择时' },
  { key: '/backtest', icon: <ExperimentOutlined />, label: '回测中心' },
  { key: '/trade', icon: <DollarOutlined />, label: '交易终端' },
  { key: '/trade-log', icon: <HistoryOutlined />, label: '交易日志' },
  { key: '/strategy-replay', icon: <LineChartOutlined />, label: '策略回放' },
  { key: '/auto-trade', icon: <RobotOutlined />, label: '自动交易' },
  { key: '/accounts', icon: <BankOutlined />, label: '账户管理' },
  { key: '/alerts', icon: <BellOutlined />, label: '预警管理' },
  { key: '/risk', icon: <SafetyOutlined />, label: '风控管理' },
  { key: '/analysis', icon: <FundProjectionScreenOutlined />, label: '分析工具' },
  { key: '/strategies', icon: <DeploymentUnitOutlined />, label: '策略管理' },
  { key: '/strategy-market', icon: <ShopOutlined />, label: '策略市场' },
  { key: '/reports', icon: <FileTextOutlined />, label: '报告中心' },
  { key: '/data-player', icon: <PlayCircleOutlined />, label: '数据回放' },
  { key: '/messages', icon: <MessageOutlined />, label: '消息中心' },
  { key: '/themes', icon: <SkinOutlined />, label: '主题商店' },
  { key: '/plugins', icon: <AppstoreOutlined />, label: '插件管理' },
  { key: '/sync', icon: <CloudSyncOutlined />, label: '数据同步' },
  { key: '/performance', icon: <ThunderboltOutlined />, label: '性能监控' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
]

interface SidebarProps {
  collapsed: boolean
  onCollapse: (v: boolean) => void
}

export default function Sidebar({ collapsed, onCollapse }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, overflow: 'auto' }}>
        <Menu
          mode="inline"
          inlineCollapsed={collapsed}
          selectedKeys={[location.pathname]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ height: '100%', borderRight: 0 }}
        />
      </div>
      <div style={{ borderTop: '1px solid var(--border-color, #f0f0f0)', padding: '4px 0', textAlign: 'center' }}>
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
