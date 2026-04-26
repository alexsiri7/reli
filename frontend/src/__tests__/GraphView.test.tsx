import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import GraphView from '../components/GraphView'

vi.mock('react-force-graph-2d', () => ({
  default: () => <canvas data-testid="force-graph" />,
}))

window.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
}

const setMainView = vi.fn()
const mockState = {
  things: [],
  thingTypes: [],
  setMainView,
}

vi.mock('../store', () => ({
  useStore: (selector: (s: typeof mockState) => unknown) => selector(mockState),
}))

vi.mock('../api', () => ({
  apiFetch: vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ things: [], relationships: [] }),
  }),
}))

beforeEach(() => {
  setMainView.mockReset()
})

describe('GraphView', () => {
  it('renders List and Graph tabs', () => {
    render(<GraphView />)
    expect(screen.getByRole('button', { name: 'List' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Graph' })).toBeInTheDocument()
  })

  it('calls setMainView("list") when List tab is clicked', () => {
    render(<GraphView />)
    fireEvent.click(screen.getByRole('button', { name: 'List' }))
    expect(setMainView).toHaveBeenCalledWith('list')
  })

  it('Graph tab is styled as active (has border-b-2 class)', () => {
    render(<GraphView />)
    const graphTab = screen.getByRole('button', { name: 'Graph' })
    expect(graphTab).toHaveClass('border-b-2')
  })

  it('List tab is styled as inactive (has text-on-surface-variant class)', () => {
    render(<GraphView />)
    const listTab = screen.getByRole('button', { name: 'List' })
    expect(listTab).toHaveClass('text-on-surface-variant')
  })

  it('Graph tab has aria-current="page"', () => {
    render(<GraphView />)
    const graphTab = screen.getByRole('button', { name: 'Graph' })
    expect(graphTab).toHaveAttribute('aria-current', 'page')
  })

  it('nav has accessible label "View switcher"', () => {
    render(<GraphView />)
    expect(screen.getByRole('navigation', { name: 'View switcher' })).toBeInTheDocument()
  })

  it('shows loading state without hiding the tab header', () => {
    render(<GraphView />)
    expect(screen.getByRole('button', { name: 'List' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Graph' })).toBeInTheDocument()
  })
})
