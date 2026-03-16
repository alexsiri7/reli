import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

let storeState: Record<string, unknown> = {}

vi.mock('../store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) => selector(storeState),
}))

vi.mock('zustand/react/shallow', () => ({
  useShallow: (fn: unknown) => fn,
}))

import { SettingsPanel } from '../components/SettingsPanel'

beforeEach(() => {
  storeState = {
    modelSettings: null,
    userSettings: null,
    availableModels: [],
    settingsLoading: false,
    modelsLoading: false,
    fetchModelSettings: vi.fn(),
    fetchAvailableModels: vi.fn(),
    fetchUserSettings: vi.fn(),
    updateModelSettings: vi.fn().mockResolvedValue(undefined),
    updateUserSettings: vi.fn().mockResolvedValue(undefined),
    closeSettings: vi.fn(),
  }
})

describe('SettingsPanel', () => {
  it('renders settings header', () => {
    render(<SettingsPanel />)
    expect(screen.getByText('Settings')).toBeInTheDocument()
  })

  it('renders close button', () => {
    render(<SettingsPanel />)
    expect(screen.getByLabelText('Close settings')).toBeInTheDocument()
  })

  it('calls closeSettings on close button click', () => {
    render(<SettingsPanel />)
    fireEvent.click(screen.getByLabelText('Close settings'))
    expect(storeState.closeSettings).toHaveBeenCalled()
  })

  it('shows loading state', () => {
    storeState.settingsLoading = true
    const { container } = render(<SettingsPanel />)
    expect(container.querySelector('.animate-pulse')).toBeTruthy()
  })

  it('shows failed to load message when settings are null and not loading', () => {
    storeState.modelSettings = null
    storeState.settingsLoading = false
    storeState.modelsLoading = false
    render(<SettingsPanel />)
    expect(screen.getByText('Failed to load settings.')).toBeInTheDocument()
  })

  it('fetches settings and models on mount', () => {
    render(<SettingsPanel />)
    expect(storeState.fetchModelSettings).toHaveBeenCalled()
    expect(storeState.fetchAvailableModels).toHaveBeenCalled()
  })

  it('renders model selects when settings are loaded', () => {
    storeState.modelSettings = { context: 'gpt-4', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
    storeState.availableModels = [{ id: 'gpt-4' }, { id: 'gpt-3.5' }]
    render(<SettingsPanel />)
    expect(screen.getByText('Context Model')).toBeInTheDocument()
    expect(screen.getByText('Reasoning Model')).toBeInTheDocument()
    expect(screen.getByText('Response Model')).toBeInTheDocument()
  })

  it('save button is disabled when no changes', () => {
    storeState.modelSettings = { context: 'gpt-4', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
    storeState.availableModels = [{ id: 'gpt-4' }, { id: 'gpt-3.5' }]
    render(<SettingsPanel />)
    const saveBtn = screen.getByText('Save')
    expect(saveBtn).toBeDisabled()
  })

  it('save button is enabled after changing a model', () => {
    storeState.modelSettings = { context: 'gpt-4', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
    storeState.availableModels = [{ id: 'gpt-4' }, { id: 'gpt-3.5' }]
    render(<SettingsPanel />)

    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0]!, { target: { value: 'gpt-3.5' } })

    const saveBtn = screen.getByText('Save')
    expect(saveBtn).not.toBeDisabled()
  })

  it('calls updateModelSettings on save', async () => {
    storeState.modelSettings = { context: 'gpt-4', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
    storeState.availableModels = [{ id: 'gpt-4' }, { id: 'gpt-3.5' }]
    render(<SettingsPanel />)

    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0]!, { target: { value: 'gpt-3.5' } })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => {
      expect(storeState.updateModelSettings).toHaveBeenCalledWith(
        expect.objectContaining({
          context: 'gpt-3.5',
          reasoning: 'gpt-4',
          response: 'gpt-4',
        })
      )
    })
  })

  it('shows Saved confirmation after save', async () => {
    storeState.modelSettings = { context: 'gpt-4', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
    storeState.availableModels = [{ id: 'gpt-4' }, { id: 'gpt-3.5' }]
    render(<SettingsPanel />)

    const selects = screen.getAllByRole('combobox')
    fireEvent.change(selects[0]!, { target: { value: 'gpt-3.5' } })
    fireEvent.click(screen.getByText('Save'))

    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument()
    })
  })

  it('shows cancel button that calls closeSettings', () => {
    storeState.modelSettings = { context: 'gpt-4', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
    storeState.availableModels = [{ id: 'gpt-4' }, { id: 'gpt-3.5' }]
    render(<SettingsPanel />)

    fireEvent.click(screen.getByText('Cancel'))
    expect(storeState.closeSettings).toHaveBeenCalled()
  })

  it('shows current model in dropdown even if not in available options', () => {
    storeState.modelSettings = { context: 'custom-model', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
    storeState.availableModels = [{ id: 'gpt-4' }, { id: 'gpt-3.5' }]
    render(<SettingsPanel />)

    const selects = screen.getAllByRole('combobox')
    const firstSelect = selects[0]!
    expect(firstSelect).toHaveValue('custom-model')
  })
})
