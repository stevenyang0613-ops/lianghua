import { useState, useEffect } from 'react'
import { MinusOutlined, CloseOutlined, FullscreenOutlined, FullscreenExitOutlined } from '@ant-design/icons'
import styles from './TitleBar.module.css'

interface TitleBarProps {
  title?: string
}

export default function TitleBar({ title = 'LiangHua - 可转债量化交易系统' }: TitleBarProps) {
  const [isMaximized, setIsMaximized] = useState(false)
  const [isElectron, setIsElectron] = useState(false)
  const [platform, setPlatform] = useState('')

  useEffect(() => {
    const api = window.electronAPI
    setIsElectron(!!api?.isElectron)
    setPlatform(api?.platform || '')

    if (api?.isElectron) {
      api.isMaximized().then(setIsMaximized)

      const unsubscribe = api.onWindowFocus((focused: boolean) => {
        document.body.classList.toggle('window-inactive', !focused)
      })

      return () => {
        unsubscribe?.()
      }
    }
  }, [])

  const handleMinimize = () => {
    window.electronAPI?.minimizeWindow()
  }

  const handleMaximize = () => {
    window.electronAPI?.maximizeWindow()
    setIsMaximized(!isMaximized)
  }

  const handleClose = () => {
    window.electronAPI?.closeWindow()
  }

  // Only show custom title bar in Electron on Windows/Linux
  if (!isElectron || platform === 'darwin') {
    return null
  }

  return (
    <div className={styles.titleBar} data-platform={platform}>
      <div className={styles.dragRegion}>
        <div className={styles.icon}>
          <svg width="16" height="16" viewBox="0 0 1024 1024">
            <rect x="0" y="0" width="1024" height="1024" rx="180" fill="#1a1a2e"/>
            <line x1="300" y1="550" x2="300" y2="420" stroke="#00d4aa" strokeWidth="12"/>
            <rect x="285" y="420" width="30" height="50" rx="4" fill="#00d4aa"/>
            <line x1="450" y1="450" x2="450" y2="400" stroke="#e94560" strokeWidth="12"/>
            <rect x="435" y="400" width="30" height="50" rx="4" fill="#e94560"/>
          </svg>
        </div>
        <span className={styles.title}>{title}</span>
      </div>
      <div className={styles.controls}>
        <button
          className={styles.controlButton}
          onClick={handleMinimize}
          title="最小化"
        >
          <MinusOutlined />
        </button>
        <button
          className={styles.controlButton}
          onClick={handleMaximize}
          title={isMaximized ? '还原' : '最大化'}
        >
          {isMaximized ? <FullscreenExitOutlined /> : <FullscreenOutlined />}
        </button>
        <button
          className={`${styles.controlButton} ${styles.closeButton}`}
          onClick={handleClose}
          title="关闭"
        >
          <CloseOutlined />
        </button>
      </div>
    </div>
  )
}
