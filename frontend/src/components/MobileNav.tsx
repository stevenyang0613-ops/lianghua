/**
 * 移动端底部导航组件
 */

import { useState, useEffect } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { Badge, Space } from 'antd'
import {
  HomeOutlined, HeartOutlined, LineChartOutlined,
  SyncOutlined, UserOutlined, SettingOutlined,
  BellOutlined, SearchOutlined
} from '@ant-design/icons'
import { useResponsive } from '../hooks/useResponsive'
import { useHapticFeedback } from '../hooks/useResponsive'
import './MobileNav.css'

interface NavItem {
  key: string
  path: string
  icon: React.ReactNode
  label: string
  badge?: number
}

const navItems: NavItem[] = [
  { key: 'market', path: '/market', icon: <HomeOutlined />, label: '市场' },
  { key: 'watchlist', path: '/watchlist', icon: <HeartOutlined />, label: '自选' },
  { key: 'backtest', path: '/backtest', icon: <LineChartOutlined />, label: '回测' },
  { key: 'trade', path: '/trade', icon: <SyncOutlined />, label: '交易' },
  { key: 'settings', path: '/settings', icon: <SettingOutlined />, label: '设置' },
]

export default function MobileNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const { isMobile } = useResponsive()
  const { light: hapticLight } = useHapticFeedback()
  const [activeKey, setActiveKey] = useState('market')
  const [notifications, setNotifications] = useState(0)

  useEffect(() => {
    const currentPath = location.pathname.split('/')[1] || 'market'
    setActiveKey(currentPath)
  }, [location])

  // 非移动端不渲染
  if (!isMobile) {
    return null
  }

  const handleNavClick = (item: NavItem) => {
    hapticLight()
    setActiveKey(item.key)
    navigate(item.path)
  }

  return (
    <div className="mobile-nav">
      {navItems.map(item => (
        <div
          key={item.key}
          className={`mobile-nav-item ${activeKey === item.key ? 'active' : ''}`}
          onClick={() => handleNavClick(item)}
        >
          <Badge count={item.badge} size="small" offset={[0, -2]}>
            <div className="mobile-nav-icon">{item.icon}</div>
          </Badge>
          <span className="mobile-nav-label">{item.label}</span>
        </div>
      ))}
    </div>
  )
}
