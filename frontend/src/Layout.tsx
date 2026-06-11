import { useState } from 'react'
import { Drawer, Button, Badge } from 'antd'
import { MenuOutlined, BellOutlined } from '@ant-design/icons'
import Sidebar from './components/Sidebar'
import StatusBar from './components/StatusBar'
import DetailPanel from './components/DetailPanel'
import ThemeToggle from './components/ThemeToggle'
import AlertPanel from './components/AlertPanel'
import TitleBar from './components/electron/TitleBar'
import OfflineIndicator from './components/OfflineIndicator'
import PerformanceMonitor from './components/PerformanceMonitor'
import { useResponsive } from './hooks/useResponsive'
import { useAppStore } from './stores/useAppStore'
import { useAlertStore } from './stores/useAlertStore'
import { isElectron } from './utils/electron'
import './styles/electron.css'
import type React from 'react'

export default function Layout({ children }: { children: React.ReactNode }) {
  const selectedBond = useAppStore((s) => s.selectedBond)
  const [sidebarVisible, setSidebarVisible] = useState(false)
  const [alertVisible, setAlertVisible] = useState(false)
  const triggers = useAlertStore((s) => s.triggers)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const { isMobile } = useResponsive()

  const electron = isElectron()

  return (
    <div
      className={electron ? 'electron-window' : ''}
      data-platform={electron ? window.electronAPI?.platform : undefined}
      style={{
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <TitleBar />
      {isMobile && (
        <div style={{
          height: 48,
          borderBottom: '1px solid #f0f0f0',
          display: 'flex',
          alignItems: 'center',
          padding: '0 12px',
          gap: 8,
        }}>
          <Button icon={<MenuOutlined />} onClick={() => setSidebarVisible(true)} />
          <span style={{ fontWeight: 600, fontSize: 16, flex: 1 }}>LiangHua</span>
          <ThemeToggle />
          <Badge count={triggers.length} size="small">
            <Button icon={<BellOutlined />} onClick={() => setAlertVisible(true)} />
          </Badge>
        </div>
      )}

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {isMobile ? (
          <Drawer
            placement="left"
            open={sidebarVisible}
            onClose={() => setSidebarVisible(false)}
            width={200}
            styles={{ body: { padding: 0 } }}
          >
            <Sidebar collapsed={false} onCollapse={() => {}} />
          </Drawer>
        ) : (
          <div style={{ width: sidebarCollapsed ? 80 : 200, borderRight: '1px solid #f0f0f0', overflow: 'auto', transition: 'width 0.2s', flexShrink: 0 }}>
            <Sidebar collapsed={sidebarCollapsed} onCollapse={setSidebarCollapsed} />
          </div>
        )}

        <div style={{ flex: 1, overflow: 'auto', background: 'var(--bg-color, #f5f5f5)', display: 'flex', flexDirection: 'column' }}>
          <OfflineIndicator />
          <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
            {!isMobile && (
              <div style={{ position: 'absolute', top: 8, right: 16, zIndex: 100, display: 'flex', gap: 8 }}>
                <ThemeToggle />
              </div>
            )}
            {children}
          </div>
        </div>

        {selectedBond && !isMobile && <DetailPanel />}
      </div>

      <StatusBar />

      {isMobile && (
        <AlertPanel visible={alertVisible} onClose={() => setAlertVisible(false)} />
      )}

      {/* 性能监控面板 - 仅在开发环境或设置启用时显示 */}
      <PerformanceMonitor />
    </div>
  )
}
