import { useState } from 'react'
import Sidebar from './components/Sidebar'
import StatusBar from './components/StatusBar'
import DetailPanel from './components/DetailPanel'
import type React from 'react'

export default function Layout({ children }: { children: React.ReactNode }) {
  const [collapsed] = useState(false)
  const [detailVisible] = useState(false)

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <div style={{ width: collapsed ? 80 : 200, borderRight: '1px solid #e8e8e8', transition: 'width 0.2s', overflow: 'auto' }}>
          <Sidebar collapsed={collapsed} onCollapse={() => {}} />
        </div>
        <div style={{ flex: 1, overflow: 'auto', background: '#f5f5f5' }}>
          {children}
        </div>
        {detailVisible && (
          <DetailPanel visible={detailVisible} />
        )}
      </div>
      <StatusBar />
    </div>
  )
}
