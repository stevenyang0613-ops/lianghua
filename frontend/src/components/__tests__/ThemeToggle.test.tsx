import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const mockSetMode = vi.fn()
vi.mock('../../stores/useThemeStore', () => ({
  useThemeStore: (selector: any) =>
    selector({ mode: 'light', setMode: mockSetMode }),
}))

import ThemeToggle from '../ThemeToggle'

describe('ThemeToggle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('should render the toggle button', () => {
    render(<ThemeToggle />)
    const btn = screen.getByRole('button')
    expect(btn).toBeDefined()
  })

  it('should have three theme options', () => {
    render(<ThemeToggle />)
    const btn = screen.getByRole('button')
    fireEvent.click(btn)
    expect(screen.getByText('浅色')).toBeDefined()
    expect(screen.getByText('深色')).toBeDefined()
    expect(screen.getByText('跟随系统')).toBeDefined()
  })
})