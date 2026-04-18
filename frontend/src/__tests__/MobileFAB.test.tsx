import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MobileFAB } from '../components/MobileFAB'

const createThing = vi.fn()

vi.mock('../store', () => ({
  useStore: (selector: (s: { createThing: typeof createThing }) => unknown) =>
    selector({ createThing }),
}))

beforeEach(() => {
  createThing.mockReset()
  createThing.mockResolvedValue(undefined)
})

describe('MobileFAB', () => {
  it('renders FAB button', () => {
    render(<MobileFAB />)
    expect(screen.getByLabelText('Quick add')).toBeInTheDocument()
  })

  it('toggles type menu open/closed on FAB click', () => {
    render(<MobileFAB />)
    const fab = screen.getByLabelText('Quick add')
    fireEvent.click(fab)
    expect(screen.getByText('Add task')).toBeInTheDocument()
    fireEvent.click(fab)
    expect(screen.queryByText('Add task')).not.toBeInTheDocument()
  })

  it('shows creation form after type selection and hides menu', () => {
    render(<MobileFAB />)
    fireEvent.click(screen.getByLabelText('Quick add'))
    fireEvent.click(screen.getByText('Add task'))
    expect(screen.queryByText('Quick note')).not.toBeInTheDocument()
    expect(screen.getByPlaceholderText('Title…')).toBeInTheDocument()
  })

  it('does not submit when title is empty', async () => {
    render(<MobileFAB />)
    fireEvent.click(screen.getByLabelText('Quick add'))
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.submit(screen.getByPlaceholderText('Title…').closest('form')!)
    expect(createThing).not.toHaveBeenCalled()
  })

  it('calls createThing and clears form on success', async () => {
    render(<MobileFAB />)
    fireEvent.click(screen.getByLabelText('Quick add'))
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.change(screen.getByPlaceholderText('Title…'), { target: { value: 'New task' } })
    fireEvent.submit(screen.getByPlaceholderText('Title…').closest('form')!)
    await waitFor(() => expect(createThing).toHaveBeenCalledWith('New task', 'task'))
    expect(screen.queryByPlaceholderText('Title…')).not.toBeInTheDocument()
  })

  it('shows error message when createThing throws', async () => {
    createThing.mockRejectedValue(new Error('Network error'))
    render(<MobileFAB />)
    fireEvent.click(screen.getByLabelText('Quick add'))
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.change(screen.getByPlaceholderText('Title…'), { target: { value: 'New task' } })
    fireEvent.submit(screen.getByPlaceholderText('Title…').closest('form')!)
    await waitFor(() => expect(screen.getByText('Network error')).toBeInTheDocument())
  })

  it('dismisses form on Escape key', () => {
    render(<MobileFAB />)
    fireEvent.click(screen.getByLabelText('Quick add'))
    fireEvent.click(screen.getByText('Add task'))
    fireEvent.keyDown(screen.getByPlaceholderText('Title…'), { key: 'Escape' })
    expect(screen.queryByPlaceholderText('Title…')).not.toBeInTheDocument()
  })

  it('closes type menu when backdrop is clicked', () => {
    render(<MobileFAB />)
    fireEvent.click(screen.getByLabelText('Quick add'))
    expect(screen.getByText('Add task')).toBeInTheDocument()
    const backdrop = document.querySelector('.fixed.inset-0') as HTMLElement
    fireEvent.click(backdrop)
    expect(screen.queryByText('Add task')).not.toBeInTheDocument()
  })
})
