import Sidebar from './components/Sidebar'
import StatusBar from './components/StatusBar'
import DetailPanel from './components/DetailPanel'
import { useAppStore } from './stores/useAppStore'
import type React from 'react'

export default function Layout({ children }: { children: React.ReactNode }) {
  const selectedBond = useAppStore((s) => s.selectedBond)

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <div style={{ width: 200, borderRight: '1px solid #e8e8e8', overflow: 'auto' }}>
          <Sidebar collapsed={false} onCollapse={() => {}} />
        </div>
        <div style={{ flex: 1, overflow: 'auto', background: '#f5f5f5' }}>
          {children}
        </div>
        {selectedBond && <DetailPanel />}
      </div>
      <StatusBar />
    </div>
  )
}
