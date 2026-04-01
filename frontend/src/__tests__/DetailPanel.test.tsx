import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DetailPanel } from '../components/DetailPanel'
import type { Thing, ThingType, Relationship } from '../store'

const closeThingDetail = vi.fn()
const navigateThingDetail = vi.fn()
const goBackThingDetail = vi.fn()

let storeState: Record<string, unknown> = {}

vi.mock('../store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) => selector(storeState),
}))

vi.mock('zustand/react/shallow', () => ({
  useShallow: (fn: unknown) => fn,
}))

const baseThing: Thing = {
  id: 't1',
  title: 'Test Thing',
  type_hint: 'task',
  parent_id: null,
  checkin_date: null,
  importance: 2,
  active: true,
  surface: true,
  data: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-02T00:00:00Z',
  last_referenced: null,
  open_questions: null,
  children_count: null,
  completed_count: null,
}

beforeEach(() => {
  closeThingDetail.mockReset()
  navigateThingDetail.mockReset()
  goBackThingDetail.mockReset()

  storeState = {
    detailThingId: 't1',
    detailThing: baseThing,
    detailRelationships: [] as Relationship[],
    detailHistory: [],
    detailLoading: false,
    closeThingDetail,
    navigateThingDetail,
    goBackThingDetail,
    things: [baseThing],
    thingTypes: [] as ThingType[],
  }
})

describe('DetailPanel', () => {
  it('renders empty state when detailThingId is null', () => {
    storeState.detailThingId = null
    render(<DetailPanel />)
    expect(screen.getByText('Click any Thing in the sidebar to see its details and relationships.')).toBeInTheDocument()
  })

  it('renders thing title', () => {
    render(<DetailPanel />)
    expect(screen.getByText('Test Thing')).toBeInTheDocument()
  })

  it('renders type badge', () => {
    render(<DetailPanel />)
    // The type badge contains icon + space + type_hint, so use a function matcher
    expect(screen.getByText((_, el) => el?.textContent?.includes('task') && el?.classList?.contains('capitalize') || false)).toBeInTheDocument()
  })

  it('renders importance label', () => {
    render(<DetailPanel />)
    expect(screen.getByText(/Medium/)).toBeInTheDocument()
  })

  it('renders loading skeleton when loading', () => {
    storeState.detailLoading = true
    storeState.detailThing = null
    const { container } = render(<DetailPanel />)
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
  })

  it('shows "Not found" when no thing and not loading', () => {
    storeState.detailThing = null
    storeState.detailLoading = false
    render(<DetailPanel />)
    expect(screen.getByText('Not found')).toBeInTheDocument()
  })

  it('shows "Thing not found" in body when no thing', () => {
    storeState.detailThing = null
    storeState.detailLoading = false
    render(<DetailPanel />)
    expect(screen.getByText('Thing not found')).toBeInTheDocument()
  })

  it('calls closeThingDetail on close button click', () => {
    render(<DetailPanel />)
    fireEvent.click(screen.getByLabelText('Close detail panel'))
    expect(closeThingDetail).toHaveBeenCalled()
  })

  it('calls closeThingDetail on Escape key', () => {
    render(<DetailPanel />)
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(closeThingDetail).toHaveBeenCalled()
  })

  it('shows back button when history exists', () => {
    storeState.detailHistory = ['t0']
    render(<DetailPanel />)
    expect(screen.getByLabelText('Go back')).toBeInTheDocument()
  })

  it('hides back button when no history', () => {
    storeState.detailHistory = []
    render(<DetailPanel />)
    expect(screen.queryByLabelText('Go back')).not.toBeInTheDocument()
  })

  it('calls goBackThingDetail on back button click', () => {
    storeState.detailHistory = ['t0']
    render(<DetailPanel />)
    fireEvent.click(screen.getByLabelText('Go back'))
    expect(goBackThingDetail).toHaveBeenCalled()
  })

  it('renders timestamps', () => {
    render(<DetailPanel />)
    expect(screen.getByText(/Created/)).toBeInTheDocument()
    expect(screen.getByText(/Updated/)).toBeInTheDocument()
  })

  it('renders checkin_date when set', () => {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    storeState.detailThing = { ...baseThing, checkin_date: tomorrow.toISOString() }
    render(<DetailPanel />)
    expect(screen.getByText('Tomorrow')).toBeInTheDocument()
  })

  it('renders open questions', () => {
    storeState.detailThing = { ...baseThing, open_questions: ['Why is sky blue?'] }
    render(<DetailPanel />)
    expect(screen.getByText('Open Questions')).toBeInTheDocument()
    expect(screen.getByText('Why is sky blue?')).toBeInTheDocument()
  })

  it('renders data fields', () => {
    storeState.detailThing = { ...baseThing, data: { status: 'active', count: 42 } }
    render(<DetailPanel />)
    expect(screen.getByText('Details')).toBeInTheDocument()
    expect(screen.getByText('status:')).toBeInTheDocument()
    expect(screen.getByText('active')).toBeInTheDocument()
  })

  it('renders children section', () => {
    const child: Thing = { ...baseThing, id: 't2', title: 'Child Thing', parent_id: 't1' }
    storeState.things = [baseThing, child]
    render(<DetailPanel />)
    expect(screen.getByText('Children (1)')).toBeInTheDocument()
    expect(screen.getByText('Child Thing')).toBeInTheDocument()
  })

  it('renders parent section', () => {
    const parent: Thing = { ...baseThing, id: 'tp', title: 'Parent Thing' }
    storeState.detailThing = { ...baseThing, parent_id: 'tp' }
    storeState.things = [parent, { ...baseThing, parent_id: 'tp' }]
    render(<DetailPanel />)
    expect(screen.getByText('Parent')).toBeInTheDocument()
    expect(screen.getByText('Parent Thing')).toBeInTheDocument()
  })

  it('navigates on child click', () => {
    const child: Thing = { ...baseThing, id: 't2', title: 'Child Thing', parent_id: 't1' }
    storeState.things = [baseThing, child]
    render(<DetailPanel />)
    fireEvent.click(screen.getByText('Child Thing'))
    expect(navigateThingDetail).toHaveBeenCalledWith('t2')
  })
})
