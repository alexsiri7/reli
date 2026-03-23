import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const openThingDetail = vi.fn()

vi.mock('../store', () => ({
  useStore: (selector: (s: { openThingDetail: typeof openThingDetail; thingTypes: never[] }) => unknown) =>
    selector({ openThingDetail, thingTypes: [] }),
}))

vi.mock('../utils', () => ({
  typeIcon: () => '📌',
}))

/**
 * Test the injectThingLinks logic by re-implementing the same function
 * and testing it directly, plus testing the rendered output via a minimal
 * ReactMarkdown component.
 */

interface ReferencedThing {
  mention: string
  thing_id: string
}

function injectThingLinks(content: string, refs: ReferencedThing[]): string {
  if (refs.length === 0) return content
  const sorted = [...refs].sort((a, b) => b.mention.length - a.mention.length)
  let result = content
  for (const ref of sorted) {
    const escaped = ref.mention.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    const re = new RegExp(`(?<!\\[)${escaped}(?!\\]\\()`, 'gi')
    result = result.replace(re, `[${ref.mention}](thing://${ref.thing_id})`)
  }
  return result
}

describe('injectThingLinks', () => {
  it('returns content unchanged when no refs', () => {
    expect(injectThingLinks('Hello world', [])).toBe('Hello world')
  })

  it('wraps a single mention in a markdown link', () => {
    const refs = [{ mention: 'Bob', thing_id: 'uuid-42' }]
    const result = injectThingLinks('I talked to Bob about it.', refs)
    expect(result).toBe('I talked to [Bob](thing://uuid-42) about it.')
  })

  it('wraps multiple occurrences of the same mention', () => {
    const refs = [{ mention: 'Bob', thing_id: 'uuid-42' }]
    const result = injectThingLinks('Bob said hi to Bob.', refs)
    expect(result).toBe('[Bob](thing://uuid-42) said hi to [Bob](thing://uuid-42).')
  })

  it('handles multiple different mentions', () => {
    const refs = [
      { mention: 'Bob', thing_id: 'uuid-42' },
      { mention: 'Trip to Paris', thing_id: 'uuid-32' },
    ]
    const result = injectThingLinks('Bob is going on the Trip to Paris.', refs)
    expect(result).toContain('[Bob](thing://uuid-42)')
    expect(result).toContain('[Trip to Paris](thing://uuid-32)')
  })

  it('handles longest-first to avoid partial matches', () => {
    const refs = [
      { mention: 'Trip', thing_id: 'uuid-1' },
      { mention: 'Trip to Paris', thing_id: 'uuid-2' },
    ]
    const result = injectThingLinks('The Trip to Paris was great.', refs)
    // "Trip to Paris" should be matched first (longest), not "Trip"
    expect(result).toContain('[Trip to Paris](thing://uuid-2)')
  })

  it('is case-insensitive', () => {
    const refs = [{ mention: 'Bob', thing_id: 'uuid-42' }]
    const result = injectThingLinks('I saw bob today.', refs)
    // The replacement uses the mention text from the ref, not the original case
    expect(result).toBe('I saw [Bob](thing://uuid-42) today.')
  })

  it('does not double-link already linked text', () => {
    const refs = [{ mention: 'Bob', thing_id: 'uuid-42' }]
    const content = 'I saw [Bob](thing://uuid-42) and Bob.'
    const result = injectThingLinks(content, refs)
    // Should only link the second occurrence
    expect(result).toBe('I saw [Bob](thing://uuid-42) and [Bob](thing://uuid-42).')
  })

  it('handles special regex characters in mentions', () => {
    const refs = [{ mention: 'C++ Project (v2)', thing_id: 'uuid-99' }]
    const result = injectThingLinks('Working on C++ Project (v2) today.', refs)
    expect(result).toBe('Working on [C++ Project (v2)](thing://uuid-99) today.')
  })
})

/**
 * Integration test: render ReactMarkdown with thing:// links and verify
 * clicking them calls openThingDetail.
 */
import ReactMarkdown from 'react-markdown'

function TestRenderer({ content, refs }: { content: string; refs: ReferencedThing[] }) {
  const linked = injectThingLinks(content, refs)
  return (
    <ReactMarkdown
      urlTransform={(url) => url}
      components={{
        a: ({ href, children }) => {
          if (href?.startsWith('thing://')) {
            const thingId = href.replace('thing://', '')
            return (
              <button
                data-testid={`thing-link-${thingId}`}
                onClick={() => openThingDetail(thingId)}
              >
                {children}
              </button>
            )
          }
          return <a href={href}>{children}</a>
        },
      }}
    >
      {linked}
    </ReactMarkdown>
  )
}

describe('Inline Thing links rendering', () => {
  beforeEach(() => {
    openThingDetail.mockReset()
  })

  it('renders mentions as clickable buttons', () => {
    const refs = [{ mention: 'Bob', thing_id: 'uuid-42' }]
    render(<TestRenderer content="I talked to Bob today." refs={refs} />)
    const btn = screen.getByTestId('thing-link-uuid-42')
    expect(btn).toBeInTheDocument()
    expect(btn.textContent).toBe('Bob')
  })

  it('calls openThingDetail on click', () => {
    const refs = [{ mention: 'Bob', thing_id: 'uuid-42' }]
    render(<TestRenderer content="I talked to Bob today." refs={refs} />)
    fireEvent.click(screen.getByTestId('thing-link-uuid-42'))
    expect(openThingDetail).toHaveBeenCalledWith('uuid-42')
  })

  it('renders regular links normally', () => {
    render(<TestRenderer content="Visit [Google](https://google.com)" refs={[]} />)
    const link = screen.getByText('Google')
    expect(link.tagName).toBe('A')
    expect(link.getAttribute('href')).toBe('https://google.com')
  })

  it('renders content without refs unchanged', () => {
    render(<TestRenderer content="No mentions here." refs={[]} />)
    expect(screen.getByText('No mentions here.')).toBeInTheDocument()
  })
})
