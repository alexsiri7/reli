import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import GraphView from '../components/GraphView'
import { apiFetch } from '../api'

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
    json: () => Promise.resolve({ nodes: [], edges: [] }),
  }),
}))

beforeEach(() => {
  setMainView.mockReset()
})

describe('GraphView', () => {
  it('renders List and Graph tabs', () => {
    render(<GraphView />)
    expect(screen.getByRole('button', { name: 'List' })).toBeInTheDocument()
    expect(screen.getByText('Graph')).toBeInTheDocument()
  })

  it('calls setMainView("list") when List tab is clicked', () => {
    render(<GraphView />)
    fireEvent.click(screen.getByRole('button', { name: 'List' }))
    expect(setMainView).toHaveBeenCalledWith('list')
  })

  it('marks Graph as the current view via aria-current and List as not current', () => {
    render(<GraphView />)
    expect(screen.getByText('Graph')).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: 'List' })).not.toHaveAttribute('aria-current')
  })

  it('nav has accessible label "View switcher"', () => {
    render(<GraphView />)
    expect(screen.getByRole('navigation', { name: 'View switcher' })).toBeInTheDocument()
  })

  it('shows loading copy with tabs visible during loading', () => {
    render(<GraphView />)
    expect(screen.getByText('Loading graph…')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'List' })).toBeInTheDocument()
    expect(screen.getByText('Graph')).toBeInTheDocument()
  })

  it('shows error copy with tabs visible when fetch fails', async () => {
    vi.mocked(apiFetch).mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: () => Promise.resolve({}),
    } as Response)
    render(<GraphView />)
    await waitFor(() => {
      expect(screen.getByText(/Failed to fetch graph/)).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'List' })).toBeInTheDocument()
    expect(screen.getByText('Graph')).toBeInTheDocument()
  })

  it('shows empty-state copy with tabs visible when graph has no nodes', async () => {
    render(<GraphView />)
    await waitFor(() => {
      expect(screen.getByText('No things to display in graph view.')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'List' })).toBeInTheDocument()
    expect(screen.getByText('Graph')).toBeInTheDocument()
  })
})
