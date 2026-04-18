import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DueTodayRow } from '../components/BriefingPanel'

const mockItem = {
  thing: { id: 'thing-1', title: 'Write proposal', active: true },
  importance: 1,
  urgency: 0.8,
  score: 0.9,
  reasons: ['Due today'],
}

describe('DueTodayRow', () => {
  it('renders thing title and reason', () => {
    render(<DueTodayRow item={mockItem as never} onDone={vi.fn()} onSnooze={vi.fn()} onChat={vi.fn()} />)
    expect(screen.getByText('Write proposal')).toBeInTheDocument()
    expect(screen.getByText('Due today')).toBeInTheDocument()
  })

  it('calls onDone with thing id when Done clicked', () => {
    const onDone = vi.fn()
    render(<DueTodayRow item={mockItem as never} onDone={onDone} onSnooze={vi.fn()} onChat={vi.fn()} />)
    fireEvent.click(screen.getByText('Done'))
    expect(onDone).toHaveBeenCalledWith('thing-1')
  })

  it('calls onSnooze with thing id when Snooze clicked', () => {
    const onSnooze = vi.fn()
    render(<DueTodayRow item={mockItem as never} onDone={vi.fn()} onSnooze={onSnooze} onChat={vi.fn()} />)
    fireEvent.click(screen.getByText('Snooze'))
    expect(onSnooze).toHaveBeenCalledWith('thing-1')
  })

  it('calls onChat with thing id and title when Chat clicked', () => {
    const onChat = vi.fn()
    render(<DueTodayRow item={mockItem as never} onDone={vi.fn()} onSnooze={vi.fn()} onChat={onChat} />)
    fireEvent.click(screen.getByText('Chat'))
    expect(onChat).toHaveBeenCalledWith('thing-1', 'Write proposal')
  })

  it('renders without reason when reasons array is empty', () => {
    const itemNoReasons = { ...mockItem, reasons: [] }
    render(<DueTodayRow item={itemNoReasons as never} onDone={vi.fn()} onSnooze={vi.fn()} onChat={vi.fn()} />)
    expect(screen.getByText('Write proposal')).toBeInTheDocument()
  })
})
