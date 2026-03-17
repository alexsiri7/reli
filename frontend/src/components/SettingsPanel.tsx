import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { ModelSettings, UserSettings, UserProfileRelationship } from '../store'
import { useTheme, setTheme } from '../hooks/useTheme'
import { ttsSupported, useAvailableVoices, getStoredVoiceURI, setStoredVoiceURI } from '../hooks/useTTS'
import { RelationshipMiniGraph } from './RelationshipMiniGraph'

export function SettingsPanel() {
  const {
    modelSettings,
    userSettings,
    availableModels,
    settingsLoading,
    modelsLoading,
    fetchModelSettings,
    fetchAvailableModels,
    fetchUserSettings,
    fetchUserProfile,
    closeSettings,
  } = useStore(
    useShallow(s => ({
      modelSettings: s.modelSettings,
      userSettings: s.userSettings,
      availableModels: s.availableModels,
      settingsLoading: s.settingsLoading,
      modelsLoading: s.modelsLoading,
      fetchModelSettings: s.fetchModelSettings,
      fetchAvailableModels: s.fetchAvailableModels,
      fetchUserSettings: s.fetchUserSettings,
      fetchUserProfile: s.fetchUserProfile,
      closeSettings: s.closeSettings,
    })),
  )

  useEffect(() => {
    fetchModelSettings()
    fetchAvailableModels()
    fetchUserSettings()
    fetchUserProfile()
  }, [fetchModelSettings, fetchAvailableModels, fetchUserSettings, fetchUserProfile])

  const modelOptions = availableModels.map(m => m.id).sort()
  const isLoading = settingsLoading || modelsLoading

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Settings</h2>
          <button
            onClick={closeSettings}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            aria-label="Close settings"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-5">
          <div>
            {isLoading ? (
              <div className="space-y-3 animate-pulse">
                <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
                <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
                <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
              </div>
            ) : modelSettings ? (
              <SettingsForm
                key={`${modelSettings.context}|${modelSettings.reasoning}|${modelSettings.response}|${modelSettings.chat_context_window}|${userSettings?.requesty_api_key}`}
                initial={modelSettings}
                initialUserSettings={userSettings}
                modelOptions={modelOptions}
                onClose={closeSettings}
              />
            ) : (
              <p className="text-sm text-gray-400">Failed to load settings.</p>
            )}
          </div>
        </div>

        {/* Footer rendered inside SettingsForm when loaded, or simple close when not */}
        {(isLoading || !modelSettings) && (
          <div className="flex items-center justify-end px-6 py-4 border-t border-gray-200 dark:border-gray-700">
            <button
              onClick={closeSettings}
              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
            >
              Close
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

function SettingsForm({
  initial,
  initialUserSettings,
  modelOptions,
  onClose,
}: {
  initial: ModelSettings
  initialUserSettings: UserSettings | null
  modelOptions: string[]
  onClose: () => void
}) {
  const updateModelSettings = useStore(s => s.updateModelSettings)
  const updateUserSettings = useStore(s => s.updateUserSettings)
  const [context, setContext] = useState(initial.context)
  const [reasoning, setReasoning] = useState(initial.reasoning)
  const [response, setResponse] = useState(initial.response)
  const [chatContextWindow, setChatContextWindow] = useState(initial.chat_context_window)
  const [reqApiKey, setReqApiKey] = useState('')
  const [reqApiKeyDisplay, setReqApiKeyDisplay] = useState(initialUserSettings?.requesty_api_key || '')
  const [interactionStyle, setInteractionStyle] = useState(initialUserSettings?.interaction_style || 'adaptive')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const hasModelChanges =
    context !== initial.context ||
    reasoning !== initial.reasoning ||
    response !== initial.response ||
    chatContextWindow !== initial.chat_context_window

  const hasApiKeyChange = reqApiKey.length > 0
  const hasInteractionStyleChange = interactionStyle !== (initialUserSettings?.interaction_style || 'adaptive')

  const hasChanges = hasModelChanges || hasApiKeyChange || hasInteractionStyleChange

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)

    // Save model settings (these go to per-user DB when auth is active)
    if (hasModelChanges) {
      await updateModelSettings({ context, reasoning, response, chat_context_window: chatContextWindow })
    }

    // Save API key if changed
    if (hasApiKeyChange) {
      await updateUserSettings({ requesty_api_key: reqApiKey })
      setReqApiKeyDisplay(reqApiKey.length <= 4 ? '****' : '*'.repeat(reqApiKey.length - 4) + reqApiKey.slice(-4))
      setReqApiKey('')
    }

    // Save interaction style if changed
    if (hasInteractionStyleChange) {
      await updateUserSettings({ interaction_style: interactionStyle })
    }

    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <>
      {/* My Profile Section */}
      <MyProfileSection />

      {/* API Key Section */}
      <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">API Key</h3>
        <p className="text-xs text-gray-400 dark:text-gray-400 mb-4">
          Your personal API key for LLM access via Requesty. This key is stored securely per-user.
        </p>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Requesty API Key
          </label>
          <div className="relative">
            <input
              type="password"
              value={reqApiKey}
              onChange={e => setReqApiKey(e.target.value)}
              placeholder={reqApiKeyDisplay || 'Enter your API key'}
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
            />
            {reqApiKeyDisplay && !reqApiKey && (
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-green-600 dark:text-green-400">
                configured
              </span>
            )}
          </div>
          <p className="text-xs text-gray-400 dark:text-gray-400 mt-1">
            Get your key at{' '}
            <a href="https://requesty.ai" target="_blank" rel="noopener noreferrer" className="text-indigo-500 hover:text-indigo-600">
              requesty.ai
            </a>
          </p>
        </div>
      </div>

      {/* Model Selection */}
      <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">AI Models</h3>
        <p className="text-xs text-gray-400 dark:text-gray-400 mb-4">
          Select which models to use for each stage of the chat pipeline.
        </p>
        <div className="space-y-4">
          <ModelSelect
            label="Context Model"
            description="Gathers context from your data"
            value={context}
            options={modelOptions}
            onChange={setContext}
          />
          <ModelSelect
            label="Reasoning Model"
            description="Plans actions and makes decisions"
            value={reasoning}
            options={modelOptions}
            onChange={setReasoning}
          />
          <ModelSelect
            label="Response Model"
            description="Generates the final reply"
            value={response}
            options={modelOptions}
            onChange={setResponse}
          />
        </div>
      </div>

      <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Chat</h3>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Context Window Size
          </label>
          <p className="text-xs text-gray-400 dark:text-gray-400 mb-1.5">
            Number of recent messages included as context for AI responses (1-50)
          </p>
          <input
            type="number"
            min={1}
            max={50}
            value={chatContextWindow}
            onChange={e => {
              const v = parseInt(e.target.value, 10)
              if (!isNaN(v)) setChatContextWindow(Math.max(1, Math.min(50, v)))
            }}
            className="w-24 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
          />
        </div>
      </div>
      {/* Interaction Style */}
      <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Interaction Style</h3>
        <p className="text-xs text-gray-400 dark:text-gray-400 mb-4">
          Choose how Reli communicates with you. Adaptive mode dynamically adjusts based on context.
        </p>
        <div className="space-y-2">
          {[
            { value: 'adaptive', label: 'Adaptive', desc: 'Automatically switches between coaching and consultant based on context' },
            { value: 'coaching', label: 'Coach', desc: 'Guides you with questions and helps you discover solutions' },
            { value: 'consultant', label: 'Consultant', desc: 'Gives direct answers, recommendations, and action items' },
          ].map(opt => (
            <label
              key={opt.value}
              className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                interactionStyle === opt.value
                  ? 'border-indigo-400 dark:border-indigo-500 bg-indigo-50 dark:bg-indigo-900/20'
                  : 'border-gray-200 dark:border-gray-700 hover:border-gray-300 dark:hover:border-gray-600'
              }`}
            >
              <input
                type="radio"
                name="interaction-style"
                value={opt.value}
                checked={interactionStyle === opt.value}
                onChange={e => setInteractionStyle(e.target.value)}
                className="mt-0.5 text-indigo-600 focus:ring-indigo-500"
              />
              <div>
                <span className="text-sm font-medium text-gray-900 dark:text-gray-100">{opt.label}</span>
                <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{opt.desc}</p>
              </div>
            </label>
          ))}
        </div>
      </div>

      <VoiceSection />
      <ThemeSection />
      <div className="flex items-center justify-end gap-3 mt-5 pt-4 border-t border-gray-200 dark:border-gray-700">
        {saved && (
          <span className="text-sm text-green-600 dark:text-green-400">Saved</span>
        )}
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={!hasChanges || saving}
          className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
        >
          {saving ? 'Saving...' : 'Save'}
        </button>
      </div>
    </>
  )
}

// Keys that are promoted to dedicated fields and hidden from the generic list
const PROMOTED_KEYS = new Set(['preferences', 'notes'])
// Keys managed by the system — never editable
const SYSTEM_KEYS = new Set(['google_id'])

function MyProfileSection() {
  const { userProfile, userProfileLoading, updateUserThing, fetchUserProfile } = useStore(
    useShallow(s => ({
      userProfile: s.userProfile,
      userProfileLoading: s.userProfileLoading,
      updateUserThing: s.updateUserThing,
      fetchUserProfile: s.fetchUserProfile,
    })),
  )

  if (userProfileLoading) {
    return (
      <div>
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">My Profile</h3>
        <div className="space-y-2 animate-pulse">
          <div className="h-8 bg-gray-200 dark:bg-gray-700 rounded w-3/4" />
          <div className="h-6 bg-gray-200 dark:bg-gray-700 rounded w-1/2" />
        </div>
      </div>
    )
  }

  if (!userProfile) {
    return (
      <div>
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">My Profile</h3>
        <p className="text-xs text-gray-400 dark:text-gray-400">Profile not available.</p>
      </div>
    )
  }

  // Key on thing.updated_at so the form remounts (resetting state) after save
  return (
    <ProfileForm
      key={userProfile.thing.updated_at}
      userProfile={userProfile}
      updateUserThing={updateUserThing}
      fetchUserProfile={fetchUserProfile}
    />
  )
}

function ProfileForm({
  userProfile,
  updateUserThing,
  fetchUserProfile,
}: {
  userProfile: { thing: { id: string; title: string; type_hint: string | null; data: Record<string, unknown> | null; updated_at: string }; relationships: UserProfileRelationship[] }
  updateUserThing: (updates: { title?: string; data?: Record<string, unknown> }) => Promise<void>
  fetchUserProfile: () => Promise<void>
}) {
  const thing = userProfile.thing

  // Derive initial values from the profile (no useEffect needed — remount resets state)
  const initPrefs = thing.data?.preferences != null ? String(thing.data.preferences) : ''
  const initNotes = thing.data?.notes != null ? String(thing.data.notes) : ''
  const initData: Record<string, string> = {}
  if (thing.data) {
    for (const [k, v] of Object.entries(thing.data)) {
      if (!SYSTEM_KEYS.has(k) && !PROMOTED_KEYS.has(k)) {
        initData[k] = String(v ?? '')
      }
    }
  }

  const [editName, setEditName] = useState(thing.title)
  const [editPreferences, setEditPreferences] = useState(initPrefs)
  const [editNotes, setEditNotes] = useState(initNotes)
  const [editData, setEditData] = useState<Record<string, string>>(initData)
  const [newFieldKey, setNewFieldKey] = useState('')
  const [newFieldValue, setNewFieldValue] = useState('')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileSaved, setProfileSaved] = useState(false)

  // Dirty detection — compare current edits to stored profile
  const isDirty = (() => {
    if (editName !== thing.title) return true
    const storedPrefs = thing.data?.preferences != null ? String(thing.data.preferences) : ''
    if (editPreferences !== storedPrefs) return true
    const storedNotes = thing.data?.notes != null ? String(thing.data.notes) : ''
    if (editNotes !== storedNotes) return true

    // Check generic data fields
    const storedData: Record<string, string> = {}
    if (thing.data) {
      for (const [k, v] of Object.entries(thing.data)) {
        if (!SYSTEM_KEYS.has(k) && !PROMOTED_KEYS.has(k)) {
          storedData[k] = String(v ?? '')
        }
      }
    }
    const editKeys = Object.keys(editData).sort()
    const storedKeys = Object.keys(storedData).sort()
    if (editKeys.length !== storedKeys.length) return true
    for (let i = 0; i < editKeys.length; i++) {
      if (editKeys[i] !== storedKeys[i]) return true
      if (editData[editKeys[i]!] !== storedData[editKeys[i]!]) return true
    }

    // Pending new field counts as a change
    if (newFieldKey.trim() && newFieldValue.trim()) return true

    return false
  })()

  const handleSaveProfile = async () => {
    setProfileSaving(true)
    setProfileSaved(false)

    // Rebuild data preserving system keys
    const newData: Record<string, unknown> = {}
    if (thing.data) {
      for (const key of SYSTEM_KEYS) {
        if (key in thing.data) {
          newData[key] = thing.data[key]
        }
      }
    }

    // Promoted fields
    if (editPreferences.trim()) newData.preferences = editPreferences.trim()
    if (editNotes.trim()) newData.notes = editNotes.trim()

    // Generic fields
    for (const [k, v] of Object.entries(editData)) {
      newData[k] = v
    }
    // Add the new field if both key and value are provided
    if (newFieldKey.trim() && newFieldValue.trim()) {
      newData[newFieldKey.trim()] = newFieldValue.trim()
    }

    await updateUserThing({ title: editName, data: newData })
    await fetchUserProfile()
    setNewFieldKey('')
    setNewFieldValue('')
    setProfileSaving(false)
    setProfileSaved(true)
    setTimeout(() => setProfileSaved(false), 2000)
  }

  const removeField = (key: string) => {
    const updated = { ...editData }
    delete updated[key]
    setEditData(updated)
  }

  const { relationships } = userProfile

  const inputClass =
    'w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500'

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">My Profile</h3>
        {profileSaved && (
          <span className="text-xs text-green-600 dark:text-green-400">Saved</span>
        )}
      </div>
      <p className="text-xs text-gray-400 dark:text-gray-400 mb-4">
        What Reli knows about you. Edit your name and personal details.
      </p>

      <div className="space-y-4">
        {/* Avatar + Name */}
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center text-indigo-600 dark:text-indigo-300 font-medium text-sm flex-shrink-0">
            {(editName || thing.title).charAt(0).toUpperCase()}
          </div>
          <div className="flex-1">
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Name</label>
            <input
              type="text"
              value={editName}
              onChange={e => setEditName(e.target.value)}
              className={inputClass}
            />
          </div>
        </div>

        {/* Preferences */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Preferences</label>
          <textarea
            value={editPreferences}
            onChange={e => setEditPreferences(e.target.value)}
            placeholder="e.g. likes concise responses, prefers bullet points"
            rows={2}
            className={inputClass + ' resize-none'}
          />
        </div>

        {/* Notes */}
        <div>
          <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Notes</label>
          <textarea
            value={editNotes}
            onChange={e => setEditNotes(e.target.value)}
            placeholder="Any notes for Reli to remember about you"
            rows={2}
            className={inputClass + ' resize-none'}
          />
        </div>

        {/* Other data fields */}
        {Object.entries(editData).length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400">Other Details</h4>
            {Object.entries(editData).map(([key, value]) => (
              <div key={key} className="flex items-center gap-2">
                <label className="text-xs font-medium text-gray-600 dark:text-gray-400 w-24 flex-shrink-0 capitalize">{key}</label>
                <input
                  type="text"
                  value={value}
                  onChange={e => setEditData({ ...editData, [key]: e.target.value })}
                  className="flex-1 px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400"
                />
                <button
                  onClick={() => removeField(key)}
                  className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                  title="Remove field"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Add new field */}
        <div>
          <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Add Field</h4>
          <div className="flex items-center gap-2">
            <input
              type="text"
              placeholder="Field name"
              value={newFieldKey}
              onChange={e => setNewFieldKey(e.target.value)}
              className="w-24 flex-shrink-0 px-3 py-1.5 text-sm rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 placeholder:text-gray-300 dark:placeholder:text-gray-500"
            />
            <input
              type="text"
              placeholder="Value"
              value={newFieldValue}
              onChange={e => setNewFieldValue(e.target.value)}
              className="flex-1 px-3 py-1.5 text-sm rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 placeholder:text-gray-300 dark:placeholder:text-gray-500"
            />
          </div>
        </div>

        {/* Save button — appears when dirty */}
        {isDirty && (
          <div className="flex items-center justify-end gap-2 pt-1">
            <button
              onClick={handleSaveProfile}
              disabled={profileSaving || !editName.trim()}
              className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
            >
              {profileSaving ? 'Saving...' : 'Save Profile'}
            </button>
          </div>
        )}

        {/* Relationship Graph */}
        <RelationshipMiniGraph
          userThingId={thing.id}
          userThingTitle={editName || thing.title}
          relationships={relationships}
        />
      </div>
    </div>
  )
}

function VoiceSection() {
  const voices = useAvailableVoices()
  const [selectedURI, setSelectedURI] = useState(getStoredVoiceURI)

  if (!ttsSupported) return null

  return (
    <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
      <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Text-to-Speech</h3>
      <div>
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
          Voice
        </label>
        <p className="text-xs text-gray-400 dark:text-gray-400 mb-1.5">
          Choose the voice used when reading messages aloud
        </p>
        {voices.length > 1 ? (
          <select
            value={selectedURI ?? ''}
            onChange={e => {
              const uri = e.target.value || null
              setSelectedURI(uri)
              setStoredVoiceURI(uri)
            }}
            className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
          >
            <option value="">Default</option>
            {voices.map(v => (
              <option key={v.voiceURI} value={v.voiceURI}>
                {v.name} ({v.lang})
              </option>
            ))}
          </select>
        ) : (
          <p className="text-xs text-gray-400 dark:text-gray-400 italic">
            Only one voice available on this device
          </p>
        )}
      </div>
    </div>
  )
}

const themeOptions = [
  { value: 'light' as const, label: 'Light', icon: 'M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z' },
  { value: 'dark' as const, label: 'Dark', icon: 'M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z' },
  { value: 'system' as const, label: 'System', icon: 'M9 17.25v1.007a3 3 0 0 1-.879 2.122L7.5 21h9l-.621-.621A3 3 0 0 1 15 18.257V17.25m6-12V15a2.25 2.25 0 0 1-2.25 2.25H5.25A2.25 2.25 0 0 1 3 15V5.25A2.25 2.25 0 0 1 5.25 3h13.5A2.25 2.25 0 0 1 21 5.25Z' },
]

function ThemeSection() {
  const { theme } = useTheme()
  const updateUserSettings = useStore(s => s.updateUserSettings)

  const handleThemeChange = (value: 'light' | 'dark' | 'system') => {
    setTheme(value)
    updateUserSettings({ theme: value })
  }

  return (
    <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
      <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Appearance</h3>
      <div className="flex gap-2">
        {themeOptions.map(opt => (
          <button
            key={opt.value}
            onClick={() => handleThemeChange(opt.value)}
            className={`flex-1 flex flex-col items-center gap-1.5 px-3 py-2.5 rounded-lg border text-sm transition-colors ${
              theme === opt.value
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d={opt.icon} />
            </svg>
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  )
}

function ModelSelect({
  label,
  description,
  value,
  options,
  onChange,
}: {
  label: string
  description: string
  value: string
  options: string[]
  onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
        {label}
      </label>
      <p className="text-xs text-gray-400 dark:text-gray-400 mb-1.5">{description}</p>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
      >
        {value && !options.includes(value) && (
          <option value={value}>{value}</option>
        )}
        {options.map(id => (
          <option key={id} value={id}>
            {id}
          </option>
        ))}
      </select>
    </div>
  )
}
