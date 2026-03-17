import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

let storeState: Record<string, unknown> = {}

vi.mock('../store', () => ({
  useStore: (selector: (s: Record<string, unknown>) => unknown) => selector(storeState),
}))

vi.mock('zustand/react/shallow', () => ({
  useShallow: (fn: unknown) => fn,
}))

vi.mock('../components/RelationshipMiniGraph', () => ({
  RelationshipMiniGraph: ({ relationships }: { relationships: Array<{ id: string; relationship_type: string; related_thing_title: string }> }) => (
    <div data-testid="relationship-mini-graph">
      {relationships.map(r => (
        <span key={r.id} data-testid={`rel-${r.id}`}>
          {r.relationship_type}: {r.related_thing_title}
        </span>
      ))}
    </div>
  ),
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
    fetchUserProfile: vi.fn(),
    updateModelSettings: vi.fn().mockResolvedValue(undefined),
    updateUserSettings: vi.fn().mockResolvedValue(undefined),
    updateUserThing: vi.fn().mockResolvedValue(undefined),
    closeSettings: vi.fn(),
    userProfile: null,
    userProfileLoading: false,
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

// Helper: default model settings so SettingsForm renders (required for profile section)
const withModels = () => {
  storeState.modelSettings = { context: 'gpt-4', reasoning: 'gpt-4', response: 'gpt-4', chat_context_window: 3 }
  storeState.availableModels = [{ id: 'gpt-4' }]
}

const makeProfile = (overrides: Record<string, unknown> = {}) => ({
  thing: {
    id: 't1',
    title: 'Alice',
    type_hint: 'person',
    parent_id: null,
    checkin_date: null,
    priority: 3,
    active: true,
    surface: true,
    data: { preferences: 'concise replies', notes: 'loves hiking', city: 'Portland' },
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    last_referenced: null,
    open_questions: null,
    children_count: null,
    completed_count: null,
    ...overrides,
  },
  relationships: [],
})

describe('MyProfileSection (inline editing)', () => {
  it('shows profile fields inline when profile is loaded', () => {
    withModels()
    storeState.userProfile = makeProfile()
    render(<SettingsPanel />)

    expect(screen.getByDisplayValue('Alice')).toBeInTheDocument()
    expect(screen.getByDisplayValue('concise replies')).toBeInTheDocument()
    expect(screen.getByDisplayValue('loves hiking')).toBeInTheDocument()
    expect(screen.getByDisplayValue('Portland')).toBeInTheDocument()
  })

  it('shows "Save Profile" button only when fields are dirty', () => {
    withModels()
    storeState.userProfile = makeProfile()
    render(<SettingsPanel />)

    // No save button initially (not dirty)
    expect(screen.queryByText('Save Profile')).not.toBeInTheDocument()

    // Change name → save button appears
    fireEvent.change(screen.getByDisplayValue('Alice'), { target: { value: 'Bob' } })
    expect(screen.getByText('Save Profile')).toBeInTheDocument()
  })

  it('calls updateUserThing with correct data on save', async () => {
    withModels()
    storeState.userProfile = makeProfile()
    render(<SettingsPanel />)

    // Edit the name
    fireEvent.change(screen.getByDisplayValue('Alice'), { target: { value: 'Bob' } })
    fireEvent.click(screen.getByText('Save Profile'))

    await waitFor(() => {
      expect(storeState.updateUserThing).toHaveBeenCalledWith({
        title: 'Bob',
        data: expect.objectContaining({
          preferences: 'concise replies',
          notes: 'loves hiking',
          city: 'Portland',
        }),
      })
    })
  })

  it('shows Saved confirmation after saving profile', async () => {
    withModels()
    storeState.userProfile = makeProfile()
    render(<SettingsPanel />)

    fireEvent.change(screen.getByDisplayValue('Alice'), { target: { value: 'Bob' } })
    fireEvent.click(screen.getByText('Save Profile'))

    await waitFor(() => {
      expect(screen.getByText('Saved')).toBeInTheDocument()
    })
  })

  it('renders empty preferences/notes textareas when data is missing', () => {
    withModels()
    storeState.userProfile = makeProfile({ data: null })
    render(<SettingsPanel />)

    expect(screen.getByPlaceholderText(/likes concise/i)).toHaveValue('')
    expect(screen.getByPlaceholderText(/notes for Reli/i)).toHaveValue('')
  })

  it('shows loading skeleton when profile is loading', () => {
    withModels()
    storeState.userProfileLoading = true
    const { container } = render(<SettingsPanel />)

    expect(container.querySelector('.animate-pulse')).toBeTruthy()
    expect(screen.getByText('My Profile')).toBeInTheDocument()
  })

  it('shows relationship graph when relationships exist', () => {
    withModels()
    storeState.userProfile = {
      ...makeProfile(),
      relationships: [
        { id: 'r1', relationship_type: 'works_at', direction: 'outgoing', related_thing_id: 't2', related_thing_title: 'Acme' },
      ],
    }
    render(<SettingsPanel />)

    expect(screen.getByTestId('relationship-mini-graph')).toBeInTheDocument()
    expect(screen.getByText('works_at: Acme')).toBeInTheDocument()
  })

  it('preserves system keys (google_id) during save', async () => {
    withModels()
    storeState.userProfile = makeProfile({ data: { google_id: 'g123', preferences: 'short' } })
    render(<SettingsPanel />)

    // Change preferences to trigger dirty state
    fireEvent.change(screen.getByDisplayValue('short'), { target: { value: 'detailed' } })
    fireEvent.click(screen.getByText('Save Profile'))

    await waitFor(() => {
      expect(storeState.updateUserThing).toHaveBeenCalledWith({
        title: 'Alice',
        data: expect.objectContaining({
          google_id: 'g123',
          preferences: 'detailed',
        }),
      })
    })
  })
})
