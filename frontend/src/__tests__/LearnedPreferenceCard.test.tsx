import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { LearnedPreferenceCard } from '../components/BriefingPanel'

const mockPref = { id: 'pref-1', title: 'Prefers async communication', confidence_label: 'strong' }

describe('LearnedPreferenceCard', () => {
  it('renders title and confidence label', () => {
    render(<LearnedPreferenceCard pref={mockPref} onFeedback={vi.fn()} />)
    expect(screen.getByText('Prefers async communication')).toBeInTheDocument()
    expect(screen.getByText('strong')).toBeInTheDocument()
  })

  it('shows feedback buttons before any feedback', () => {
    render(<LearnedPreferenceCard pref={mockPref} onFeedback={vi.fn()} />)
    expect(screen.getByText("That's right")).toBeInTheDocument()
    expect(screen.getByText('Not really')).toBeInTheDocument()
  })

  it("calls onFeedback(id, true) when \"That's right\" clicked", () => {
    const onFeedback = vi.fn()
    render(<LearnedPreferenceCard pref={mockPref} onFeedback={onFeedback} />)
    fireEvent.click(screen.getByText("That's right"))
    expect(onFeedback).toHaveBeenCalledWith('pref-1', true)
  })

  it("calls onFeedback(id, false) when 'Not really' clicked", () => {
    const onFeedback = vi.fn()
    render(<LearnedPreferenceCard pref={mockPref} onFeedback={onFeedback} />)
    fireEvent.click(screen.getByText('Not really'))
    expect(onFeedback).toHaveBeenCalledWith('pref-1', false)
  })

  it("shows 'Thanks!' and hides buttons after positive feedback", () => {
    render(<LearnedPreferenceCard pref={mockPref} onFeedback={vi.fn()} />)
    fireEvent.click(screen.getByText("That's right"))
    expect(screen.getByText('Thanks!')).toBeInTheDocument()
    expect(screen.queryByText("That's right")).not.toBeInTheDocument()
    expect(screen.queryByText('Not really')).not.toBeInTheDocument()
  })

  it("shows 'Got it' after negative feedback", () => {
    render(<LearnedPreferenceCard pref={mockPref} onFeedback={vi.fn()} />)
    fireEvent.click(screen.getByText('Not really'))
    expect(screen.getByText('Got it')).toBeInTheDocument()
  })

  it('does not call onFeedback a second time after feedback given', () => {
    const onFeedback = vi.fn()
    render(<LearnedPreferenceCard pref={mockPref} onFeedback={onFeedback} />)
    fireEvent.click(screen.getByText("That's right"))
    // After feedback sent, buttons are gone — no second click possible
    expect(onFeedback).toHaveBeenCalledTimes(1)
  })
})
