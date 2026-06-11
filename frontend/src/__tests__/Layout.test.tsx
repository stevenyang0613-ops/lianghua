import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

vi.mock('../components/Sidebar', () => ({
  default: () => null,
}))
vi.mock('../components/StatusBar', () => ({
  default: () => null,
}))
vi.mock('../components/DetailPanel', () => ({
  default: () => null,
}))
vi.mock('../components/ThemeToggle', () => ({
  default: () => null,
}))
vi.mock('../components/AlertPanel', () => ({
  default: () => null,
}))
vi.mock('../components/electron/TitleBar', () => ({
  default: () => null,
}))
vi.mock('../hooks/useResponsive', () => ({
  useResponsive: () => ({ isMobile: false }),
}))
vi.mock('../stores/useAppStore', () => ({
  useAppStore: (selector: any) => selector({ selectedBond: null }),
}))
vi.mock('../stores/useAlertStore', () => ({
  useAlertStore: (selector: any) => selector({ triggers: [] }),
}))
vi.mock('../utils/electron', () => ({
  isElectron: () => false,
}))
vi.mock('../styles/electron.css', () => ({}))

import Layout from '../Layout'

describe('Layout', () => {
  it('should render children content', () => {
    render(
      <BrowserRouter>
        <Layout><div data-testid="child">child content</div></Layout>
      </BrowserRouter>
    )
    expect(screen.getByTestId('child')).toBeDefined()
  })
})