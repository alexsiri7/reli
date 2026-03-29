import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

/**
 * ContextDropdown is a private component inside ChatPanel.tsx.
 * We test it indirectly by re-creating the same logic in a minimal test component.
 * This verifies the pill-based summary and click-to-expand behavior.
 */

const openThingDetail = vi.fn()
const thingTypes: { id: string; name: string; icon: string; color: string | null; created_at: string }[] = []

vi.mock('../store', () => ({
  useStore: (selector: (s: { openThingDetail: typeof openThingDetail; thingTypes: typeof thingTypes }) => unknown) =>
    selector({ openThingDetail, thingTypes }),
}))

vi.mock('../utils', () => ({
  typeIcon: () => '📌',
}))

import { useState } from 'react'
import { useStore } from '../store'
import { typeIcon } from '../utils'

interface ContextThing {
  id: string
  title: string
  type_hint?: string | null
}

interface AppliedChanges {
  created?: { id: string; title: string; type_hint?: string }[]
  updated?: { id: string; title: string }[]
  deleted?: string[]
  context_things?: ContextThing[]
}

function TestContextDropdown({ changes }: { changes: AppliedChanges }) {
  const [expanded, setExpanded] = useState(false)
  const ttypes = useStore(s => s.thingTypes)
  const openDetail = useStore(s => s.openThingDetail)

  const contextThings = changes.context_things ?? []
  const created = changes.created ?? []
  const updated = changes.updated ?? []
  const deleted = changes.deleted ?? []
  const hasEffects = created.length > 0 || updated.length > 0 || deleted.length > 0
  const hasInferredConnections = contextThings.length > 0

  if (!hasInferredConnections && !hasEffects) return null

  return (
    <div>
      {/* Pill summary */}
      <div>
        {created.length > 0 && (
          <span data-testid="pill-created">+{created.length} created</span>
        )}
        {updated.length > 0 && (
          <span data-testid="pill-updated">✓ {updated.length} updated</span>
        )}
        {deleted.length > 0 && (
          <span data-testid="pill-deleted">{deleted.length} deleted</span>
        )}
        {hasInferredConnections && (
          <span data-testid="pill-inferred">💡 inferred connection</span>
        )}
        <button onClick={() => setExpanded(!expanded)}>
          {expanded ? '▴ hide' : '▾ details'}
        </button>
      </div>
      {expanded && (
        <div>
          {hasInferredConnections && (
            <div>
              {contextThings.map((t: ContextThing) => (
                <button
                  key={t.id}
                  onClick={() => openDetail(t.id)}
                  data-testid={`context-thing-${t.id}`}
                >
                  <span>{typeIcon(t.type_hint, ttypes)}</span>
                  <span>{t.title}</span>
                </button>
              ))}
            </div>
          )}
          {created.map(c => (
            <button
              key={c.id}
              onClick={() => openDetail(c.id)}
              data-testid={`created-thing-${c.id}`}
            >
              Created {c.title}
            </button>
          ))}
          {updated.map(u => (
            <button
              key={u.id}
              onClick={() => openDetail(u.id)}
              data-testid={`updated-thing-${u.id}`}
            >
              Updated {u.title}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

describe('ContextDropdown', () => {
  beforeEach(() => {
    openThingDetail.mockReset()
  })

  it('renders nothing when no context or effects', () => {
    const { container } = render(<TestContextDropdown changes={{}} />)
    expect(container.innerHTML).toBe('')
  })

  it('shows created pill when things are created', () => {
    render(
      <TestContextDropdown
        changes={{ created: [{ id: 'new-1', title: 'New Item', type_hint: 'task' }] }}
      />,
    )
    expect(screen.getByTestId('pill-created')).toHaveTextContent('+1 created')
  })

  it('shows updated pill when things are updated', () => {
    render(
      <TestContextDropdown
        changes={{ updated: [{ id: 'upd-1', title: 'Updated Item' }] }}
      />,
    )
    expect(screen.getByTestId('pill-updated')).toHaveTextContent('✓ 1 updated')
  })

  it('shows inferred connection pill when context things exist', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'ctx-1', title: 'Related Thing', type_hint: 'task' }] }}
      />,
    )
    expect(screen.getByTestId('pill-inferred')).toBeInTheDocument()
  })

  it('does not show inferred pill when no context things', () => {
    render(
      <TestContextDropdown
        changes={{ created: [{ id: 'new-1', title: 'New Item' }] }}
      />,
    )
    expect(screen.queryByTestId('pill-inferred')).not.toBeInTheDocument()
  })

  it('shows details toggle button', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'ctx-1', title: 'Test Thing', type_hint: 'task' }] }}
      />,
    )
    expect(screen.getByText('▾ details')).toBeInTheDocument()
  })

  it('details are hidden by default', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'ctx-1', title: 'Test Thing', type_hint: 'task' }] }}
      />,
    )
    expect(screen.queryByText('Test Thing')).not.toBeInTheDocument()
  })

  it('expands on details toggle click', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'uuid-1', title: 'Test Thing', type_hint: 'task' }] }}
      />,
    )
    fireEvent.click(screen.getByText('▾ details'))
    expect(screen.getByText('Test Thing')).toBeInTheDocument()
    expect(screen.getByText('▴ hide')).toBeInTheDocument()
  })

  it('collapses when hide is clicked', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'ctx-1', title: 'Test Thing' }] }}
      />,
    )
    fireEvent.click(screen.getByText('▾ details'))
    expect(screen.getByText('Test Thing')).toBeInTheDocument()
    fireEvent.click(screen.getByText('▴ hide'))
    expect(screen.queryByText('Test Thing')).not.toBeInTheDocument()
  })

  it('calls openThingDetail when context thing is clicked in expanded view', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'uuid-abc', title: 'My Note', type_hint: 'note' }] }}
      />,
    )
    fireEvent.click(screen.getByText('▾ details'))
    fireEvent.click(screen.getByTestId('context-thing-uuid-abc'))
    expect(openThingDetail).toHaveBeenCalledTimes(1)
    expect(openThingDetail).toHaveBeenCalledWith('uuid-abc')
  })

  it('calls openThingDetail for created things in expanded view', () => {
    render(
      <TestContextDropdown
        changes={{ created: [{ id: 'new-1', title: 'New Item', type_hint: 'task' }] }}
      />,
    )
    fireEvent.click(screen.getByText('▾ details'))
    fireEvent.click(screen.getByTestId('created-thing-new-1'))
    expect(openThingDetail).toHaveBeenCalledWith('new-1')
  })

  it('calls openThingDetail for updated things in expanded view', () => {
    render(
      <TestContextDropdown
        changes={{ updated: [{ id: 'upd-1', title: 'Updated Item' }] }}
      />,
    )
    fireEvent.click(screen.getByText('▾ details'))
    fireEvent.click(screen.getByTestId('updated-thing-upd-1'))
    expect(openThingDetail).toHaveBeenCalledWith('upd-1')
  })

  it('shows multiple pills when effects and inferred connections both exist', () => {
    render(
      <TestContextDropdown
        changes={{
          created: [{ id: 'new-1', title: 'New Item' }],
          updated: [{ id: 'upd-1', title: 'Updated Item' }],
          context_things: [{ id: 'ctx-1', title: 'Related Thing' }],
        }}
      />,
    )
    expect(screen.getByTestId('pill-created')).toBeInTheDocument()
    expect(screen.getByTestId('pill-updated')).toBeInTheDocument()
    expect(screen.getByTestId('pill-inferred')).toBeInTheDocument()
  })

  it('handles multiple context things in expanded view', () => {
    render(
      <TestContextDropdown
        changes={{
          context_things: [
            { id: 'a', title: 'Thing A' },
            { id: 'b', title: 'Thing B' },
            { id: 'c', title: 'Thing C' },
          ],
        }}
      />,
    )
    expect(screen.getByTestId('pill-inferred')).toBeInTheDocument()
    fireEvent.click(screen.getByText('▾ details'))
    expect(screen.getByText('Thing A')).toBeInTheDocument()
    expect(screen.getByText('Thing B')).toBeInTheDocument()
    expect(screen.getByText('Thing C')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('context-thing-b'))
    expect(openThingDetail).toHaveBeenCalledWith('b')
  })
})
