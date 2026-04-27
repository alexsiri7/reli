import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

let storeState: Record<string, unknown> = {}

vi.mock('../store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) => selector(storeState),
}))
vi.mock('zustand/react/shallow', () => ({
  useShallow: (fn: unknown) => fn,
}))

vi.mock('../lib/screenshot', () => ({
  capturePageToCanvas: vi.fn().mockResolvedValue(document.createElement('canvas')),
  isWithinSizeLimit: vi.fn().mockReturnValue(true),
}))

vi.mock('../components/ScreenshotEditor', () => ({
  ScreenshotEditor: ({ onDone, onCancel }: { onDone: (b: string) => void; onCancel: () => void }) => (
    <div data-testid="screenshot-editor">
      <button onClick={() => onDone('fakebase64==')}>Use Screenshot</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  ),
}))

import { FeedbackDialog } from '../components/FeedbackDialog'

const mockSubmitFeedback = vi.fn()
const mockCloseFeedback = vi.fn()

beforeEach(() => {
  mockSubmitFeedback.mockReset().mockResolvedValue({ success: true, issueUrl: 'https://github.com/test/1' })
  mockCloseFeedback.mockReset()
  storeState = {
    closeFeedback: mockCloseFeedback,
    submitFeedback: mockSubmitFeedback,
  }
})

describe('FeedbackDialog', () => {
  it('renders Send Feedback header', () => {
    render(<FeedbackDialog />)
    expect(screen.getByText('Send Feedback')).toBeInTheDocument()
  })

  it('calls closeFeedback on Cancel click', () => {
    render(<FeedbackDialog />)
    fireEvent.click(screen.getByText('Cancel'))
    expect(mockCloseFeedback).toHaveBeenCalled()
  })

  it('does not call submitFeedback when message is empty', () => {
    render(<FeedbackDialog />)
    fireEvent.click(screen.getByText('Submit Feedback'))
    expect(mockSubmitFeedback).not.toHaveBeenCalled()
  })

  it('calls submitFeedback with correct data on submit', async () => {
    render(<FeedbackDialog />)
    fireEvent.change(screen.getByPlaceholderText(/Describe the bug/), { target: { value: 'Test message' } })
    fireEvent.click(screen.getByText('Submit Feedback'))
    await waitFor(() => {
      expect(mockSubmitFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          category: 'bug',
          message: 'Test message',
        }),
      )
    })
  })

  it('shows success state with issue URL after successful submit', async () => {
    render(<FeedbackDialog />)
    fireEvent.change(screen.getByPlaceholderText(/Describe the bug/), { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('Submit Feedback'))
    await waitFor(() => {
      expect(screen.getByText('Thank you for your feedback!')).toBeInTheDocument()
    })
    expect(screen.getByText('View issue on GitHub')).toBeInTheDocument()
  })

  it('shows error message on failed submit', async () => {
    mockSubmitFeedback.mockResolvedValue({ success: false, error: 'Something went wrong' })
    render(<FeedbackDialog />)
    fireEvent.change(screen.getByPlaceholderText(/Describe the bug/), { target: { value: 'Test' } })
    fireEvent.click(screen.getByText('Submit Feedback'))
    await waitFor(() => {
      expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    })
  })

  it('shows Add Screenshot button', () => {
    render(<FeedbackDialog />)
    expect(screen.getByText('Add Screenshot')).toBeInTheDocument()
  })

  it('shows screenshot editor after capture flow, and submit includes screenshot_base64', async () => {
    render(<FeedbackDialog />)
    fireEvent.click(screen.getByText('Add Screenshot'))

    await waitFor(() => {
      expect(screen.getByTestId('screenshot-editor')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Use Screenshot'))

    await waitFor(() => {
      expect(screen.getByAltText('Screenshot preview')).toBeInTheDocument()
    })

    fireEvent.change(screen.getByPlaceholderText(/Describe the bug/), { target: { value: 'Bug with screenshot' } })
    fireEvent.click(screen.getByText('Submit Feedback'))
    await waitFor(() => {
      expect(mockSubmitFeedback).toHaveBeenCalledWith(
        expect.objectContaining({
          screenshot_base64: 'fakebase64==',
        }),
      )
    })
  })

  it('removes screenshot when × button is clicked', async () => {
    render(<FeedbackDialog />)
    fireEvent.click(screen.getByText('Add Screenshot'))

    await waitFor(() => {
      expect(screen.getByTestId('screenshot-editor')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText('Use Screenshot'))

    await waitFor(() => {
      expect(screen.getByAltText('Screenshot preview')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByLabelText('Remove screenshot'))

    expect(screen.queryByAltText('Screenshot preview')).not.toBeInTheDocument()
    expect(screen.getByText('Add Screenshot')).toBeInTheDocument()
  })

  it('shows size error when screenshot exceeds limit', async () => {
    const { isWithinSizeLimit } = await import('../lib/screenshot')
    vi.mocked(isWithinSizeLimit).mockReturnValueOnce(false)

    render(<FeedbackDialog />)
    fireEvent.click(screen.getByText('Add Screenshot'))
    await waitFor(() => expect(screen.getByTestId('screenshot-editor')).toBeInTheDocument())
    fireEvent.click(screen.getByText('Use Screenshot'))

    await waitFor(() => {
      expect(screen.getByText('Screenshot is too large (max 2MB). Try again.')).toBeInTheDocument()
    })
    expect(screen.queryByAltText('Screenshot preview')).not.toBeInTheDocument()
    expect(screen.getByText('Add Screenshot')).toBeInTheDocument()
  })

  it('returns to form with error when capture fails', async () => {
    const { capturePageToCanvas } = await import('../lib/screenshot')
    vi.mocked(capturePageToCanvas).mockRejectedValueOnce(new Error('CORS error'))

    render(<FeedbackDialog />)
    fireEvent.click(screen.getByText('Add Screenshot'))

    await waitFor(() => {
      expect(screen.queryByTestId('screenshot-editor')).not.toBeInTheDocument()
      expect(screen.getByText('Add Screenshot')).toBeInTheDocument()
      expect(screen.getByText('Could not capture screenshot. Try again.')).toBeInTheDocument()
    })
  })

  it('returns to form without screenshot when editor is cancelled', async () => {
    render(<FeedbackDialog />)
    fireEvent.click(screen.getByText('Add Screenshot'))

    await waitFor(() => expect(screen.getByTestId('screenshot-editor')).toBeInTheDocument())

    fireEvent.click(screen.getByText('Cancel'))

    expect(screen.queryByTestId('screenshot-editor')).not.toBeInTheDocument()
    expect(screen.getByText('Add Screenshot')).toBeInTheDocument()
    expect(screen.queryByAltText('Screenshot preview')).not.toBeInTheDocument()
  })
})
