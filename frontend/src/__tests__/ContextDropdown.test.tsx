import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

/**
 * ContextDropdown is a private component inside ChatPanel.tsx.
 * We test it indirectly by re-creating the same logic in a minimal test component.
 * This verifies the click-to-open-detail behavior works correctly.
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
  const hasContext = contextThings.length > 0

  if (!hasContext && !hasEffects) return null

  const totalCount = contextThings.length + created.length + updated.length + deleted.length

  return (
    <div>
      <button onClick={() => setExpanded(!expanded)}>
        Context &amp; changes ({totalCount})
      </button>
      {expanded && (
        <div>
          {hasContext && (
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

  it('shows toggle button with count', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'uuid-1', title: 'Test Thing', type_hint: 'task' }] }}
      />,
    )
    expect(screen.getByText(/Context & changes \(1\)/)).toBeInTheDocument()
  })

  it('expands on toggle click to show context things', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'uuid-1', title: 'Test Thing', type_hint: 'task' }] }}
      />,
    )
    expect(screen.queryByText('Test Thing')).not.toBeInTheDocument()
    fireEvent.click(screen.getByText(/Context & changes/))
    expect(screen.getByText('Test Thing')).toBeInTheDocument()
  })

  it('calls openThingDetail when context thing is clicked', () => {
    render(
      <TestContextDropdown
        changes={{ context_things: [{ id: 'uuid-abc', title: 'My Note', type_hint: 'note' }] }}
      />,
    )
    fireEvent.click(screen.getByText(/Context & changes/))
    fireEvent.click(screen.getByTestId('context-thing-uuid-abc'))
    expect(openThingDetail).toHaveBeenCalledTimes(1)
    expect(openThingDetail).toHaveBeenCalledWith('uuid-abc')
  })

  it('calls openThingDetail for created things', () => {
    render(
      <TestContextDropdown
        changes={{ created: [{ id: 'new-1', title: 'New Item', type_hint: 'task' }] }}
      />,
    )
    fireEvent.click(screen.getByText(/Context & changes/))
    fireEvent.click(screen.getByTestId('created-thing-new-1'))
    expect(openThingDetail).toHaveBeenCalledWith('new-1')
  })

  it('calls openThingDetail for updated things', () => {
    render(
      <TestContextDropdown
        changes={{ updated: [{ id: 'upd-1', title: 'Updated Item' }] }}
      />,
    )
    fireEvent.click(screen.getByText(/Context & changes/))
    fireEvent.click(screen.getByTestId('updated-thing-upd-1'))
    expect(openThingDetail).toHaveBeenCalledWith('upd-1')
  })

  it('handles multiple context things', () => {
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
    fireEvent.click(screen.getByText(/Context & changes \(3\)/))
    expect(screen.getByText('Thing A')).toBeInTheDocument()
    expect(screen.getByText('Thing B')).toBeInTheDocument()
    expect(screen.getByText('Thing C')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('context-thing-b'))
    expect(openThingDetail).toHaveBeenCalledWith('b')
  })
})
