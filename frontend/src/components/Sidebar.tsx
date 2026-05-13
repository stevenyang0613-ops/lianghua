import { useNavigate, useLocation } from 'react-router-dom'
import { Menu } from 'antd'
import {
  DashboardOutlined,
  StockOutlined,
  StarOutlined,
  ExperimentOutlined,
  DollarOutlined,
  FundProjectionScreenOutlined,
  DeploymentUnitOutlined,
  SettingOutlined,
} from '@ant-design/icons'

const menuItems = [
  { key: '/', icon: <StockOutlined />, label: '实时行情' },
  { key: '/watchlist', icon: <StarOutlined />, label: '自选列表' },
  { key: '/backtest', icon: <ExperimentOutlined />, label: '回测中心' },
  { key: '/trade', icon: <DollarOutlined />, label: '交易终端' },
  { key: '/analysis', icon: <FundProjectionScreenOutlined />, label: '分析工具' },
  { key: '/strategies', icon: <DeploymentUnitOutlined />, label: '策略管理' },
  { key: '/settings', icon: <SettingOutlined />, label: '系统设置' },
]

interface SidebarProps {
  collapsed: boolean
  onCollapse: (v: boolean) => void
}

export default function Sidebar({ collapsed }: SidebarProps) {
  const navigate = useNavigate()
  const location = useLocation()

  return (
    <Menu
      mode="inline"
      inlineCollapsed={collapsed}
      selectedKeys={[location.pathname]}
      items={menuItems}
      onClick={({ key }) => navigate(key)}
      style={{ height: '100%', borderRight: 0 }}
    />
  )
}
