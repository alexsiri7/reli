import { useEffect, useMemo, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { ModelSettings, UserSettings, UserProfileRelationship, RequestyModel } from '../store'
import { useTheme, setTheme } from '../hooks/useTheme'
import { ttsSupported, useAvailableVoices, getStoredVoiceURI, setStoredVoiceURI } from '../hooks/useTTS'
import { RelationshipMiniGraph } from './RelationshipMiniGraph'
import { usePushNotifications } from '../hooks/usePushNotifications'

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

  const sortedModels = useMemo(
    () => [...availableModels].sort((a, b) => a.id.localeCompare(b.id)),
    [availableModels],
  )
  const modelOptions = sortedModels.map(m => m.id)
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
                models={sortedModels}
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
  models,
  onClose,
}: {
  initial: ModelSettings
  initialUserSettings: UserSettings | null
  modelOptions: string[]
  models: RequestyModel[]
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
  const [staleThresholdDays, setStaleThresholdDays] = useState(initialUserSettings?.stale_threshold_days ?? 14)
  const [saving, setSaving] = useState(false)

  const hasModelChanges =
    context !== initial.context ||
    reasoning !== initial.reasoning ||
    response !== initial.response ||
    chatContextWindow !== initial.chat_context_window

  const hasApiKeyChange = reqApiKey.length > 0
  const hasStaleThresholdChange = staleThresholdDays !== (initialUserSettings?.stale_threshold_days ?? 14)

  const hasChanges = hasModelChanges || hasApiKeyChange || hasStaleThresholdChange

  const handleSave = async () => {
    setSaving(true)

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

    // Save stale threshold if changed
    if (hasStaleThresholdChange) {
      await updateUserSettings({ stale_threshold_days: staleThresholdDays })
    }

    setSaving(false)
    onClose()
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
          Pick a preset or customise each model individually.
        </p>

        {/* Presets */}
        <div className="flex gap-2 mb-4">
          {MODEL_PRESETS.map(preset => {
            const active =
              context === preset.context &&
              reasoning === preset.reasoning &&
              response === preset.response
            const ts = COST_TIER_STYLES[preset.tier]
            return (
              <button
                key={preset.label}
                type="button"
                onClick={() => {
                  setContext(preset.context)
                  setReasoning(preset.reasoning)
                  setResponse(preset.response)
                }}
                title={preset.description}
                className={`flex-1 px-3 py-2 text-xs font-medium rounded-lg border transition-colors ${
                  active
                    ? `${ts.bg} ${ts.color} ring-1 ring-current`
                    : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:border-gray-300 dark:hover:border-gray-600'
                }`}
              >
                {preset.label}
              </button>
            )
          })}
        </div>

        <div className="space-y-4">
          <ModelPicker
            label="Context Model"
            description="Gathers context from your data"
            value={context}
            options={modelOptions}
            models={models}
            onChange={setContext}
          />
          <ModelPicker
            label="Reasoning Model"
            description="Plans actions and makes decisions"
            value={reasoning}
            options={modelOptions}
            models={models}
            onChange={setReasoning}
          />
          <ModelPicker
            label="Response Model"
            description="Generates the final reply"
            value={response}
            options={modelOptions}
            models={models}
            onChange={setResponse}
          />
        </div>
        <ModelCostSummary
          contextModel={context}
          reasoningModel={reasoning}
          responseModel={response}
          models={models}
        />
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
      {/* Staleness Detection */}
      <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Staleness Detection</h3>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Stale Threshold (days)
          </label>
          <p className="text-xs text-gray-400 dark:text-gray-400 mb-1.5">
            Things not updated for this many days are flagged as stale or neglected (1-365)
          </p>
          <input
            type="number"
            min={1}
            max={365}
            value={staleThresholdDays}
            onChange={e => {
              const v = parseInt(e.target.value, 10)
              if (!isNaN(v)) setStaleThresholdDays(Math.max(1, Math.min(365, v)))
            }}
            className="w-24 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
          />
        </div>
      </div>
      <NotificationsSection />
      <VoiceSection />
      <ThemeSection />
      <ProactivitySection />
      <div className="flex items-center justify-end gap-3 mt-5 pt-4 border-t border-gray-200 dark:border-gray-700">
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
        <p className="text-xs text-gray-400 dark:text-gray-400">
          As we talk, I'll learn how you like to work. You can always edit what I've picked up.
        </p>
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

const proactivityOptions = [
  { value: 'off', label: 'Off', description: 'No conflict alerts' },
  { value: 'low', label: 'Low', description: 'Critical only' },
  { value: 'medium', label: 'Medium', description: 'Warnings & critical' },
  { value: 'high', label: 'High', description: 'All alerts' },
]

function ProactivitySection() {
  const { userSettings, updateUserSettings } = useStore(useShallow(s => ({
    userSettings: s.userSettings,
    updateUserSettings: s.updateUserSettings,
  })))
  const current = userSettings?.proactivity_level || 'medium'

  return (
    <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
      <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Proactive Alerts</h3>
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">How aggressively Reli flags blockers, conflicts, and scheduling issues</p>
      <div className="flex gap-2">
        {proactivityOptions.map(opt => (
          <button
            key={opt.value}
            onClick={() => updateUserSettings({ proactivity_level: opt.value })}
            className={`flex-1 flex flex-col items-center gap-0.5 px-2 py-2 rounded-lg border text-sm transition-colors ${
              current === opt.value
                ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
            }`}
            title={opt.description}
          >
            <span className="font-medium">{opt.label}</span>
            <span className="text-[10px] text-gray-400 dark:text-gray-500 leading-tight">{opt.description}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function NotificationsSection() {
  const { permission, prefs, requestPermission, updatePrefs } = usePushNotifications()
  const supported = 'Notification' in window

  if (!supported) return null

  return (
    <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
      <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Push Notifications</h3>
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-3">
        Get notified about calendar events and urgent tasks even when Reli is in the background.
      </p>

      {permission === 'denied' ? (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Notifications are blocked in your browser. Enable them in browser settings to use this feature.
        </p>
      ) : permission === 'default' ? (
        <button
          onClick={requestPermission}
          className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
        >
          Enable notifications
        </button>
      ) : (
        <div className="space-y-2.5">
          {/* Master toggle */}
          <label className="flex items-center justify-between gap-3 cursor-pointer">
            <span className="text-sm text-gray-700 dark:text-gray-300">Notifications enabled</span>
            <button
              role="switch"
              aria-checked={prefs.enabled}
              onClick={() => updatePrefs({ enabled: !prefs.enabled })}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                prefs.enabled ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-gray-600'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                  prefs.enabled ? 'translate-x-4' : 'translate-x-1'
                }`}
              />
            </button>
          </label>

          {prefs.enabled && (
            <div className="ml-1 space-y-2 border-l-2 border-gray-100 dark:border-gray-700 pl-3">
              {/* Calendar events */}
              <label className="flex items-center justify-between gap-3 cursor-pointer">
                <div>
                  <span className="text-sm text-gray-700 dark:text-gray-300">Calendar events</span>
                  <p className="text-xs text-gray-400 dark:text-gray-500">30 minutes before each event</p>
                </div>
                <button
                  role="switch"
                  aria-checked={prefs.calendarEvents}
                  onClick={() => updatePrefs({ calendarEvents: !prefs.calendarEvents })}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    prefs.calendarEvents ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-gray-600'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                      prefs.calendarEvents ? 'translate-x-4' : 'translate-x-1'
                    }`}
                  />
                </button>
              </label>

              {/* Urgent tasks */}
              <label className="flex items-center justify-between gap-3 cursor-pointer">
                <div>
                  <span className="text-sm text-gray-700 dark:text-gray-300">Urgent task check-ins</span>
                  <p className="text-xs text-gray-400 dark:text-gray-500">Overdue or approaching deadlines</p>
                </div>
                <button
                  role="switch"
                  aria-checked={prefs.urgentTasks}
                  onClick={() => updatePrefs({ urgentTasks: !prefs.urgentTasks })}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    prefs.urgentTasks ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-gray-600'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                      prefs.urgentTasks ? 'translate-x-4' : 'translate-x-1'
                    }`}
                  />
                </button>
              </label>

              {/* Insights */}
              <label className="flex items-center justify-between gap-3 cursor-pointer">
                <div>
                  <span className="text-sm text-gray-700 dark:text-gray-300">High-priority insights</span>
                  <p className="text-xs text-gray-400 dark:text-gray-500">Proactive suggestions from Reli</p>
                </div>
                <button
                  role="switch"
                  aria-checked={prefs.insights}
                  onClick={() => updatePrefs({ insights: !prefs.insights })}
                  className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    prefs.insights ? 'bg-indigo-600' : 'bg-gray-300 dark:bg-gray-600'
                  }`}
                >
                  <span
                    className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform ${
                      prefs.insights ? 'translate-x-4' : 'translate-x-1'
                    }`}
                  />
                </button>
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function formatCost(cost: number | null | undefined): string {
  if (cost == null) return '—'
  if (cost < 0.01) return '<$0.01'
  return `$${cost.toFixed(2)}`
}

/** Format cost in per-1K-token units (more intuitive than per 1M) */
function formatCostPer1K(costPerMillion: number | null | undefined): string {
  if (costPerMillion == null) return '—'
  const per1k = costPerMillion / 1000
  if (per1k < 0.0001) return '<$0.0001'
  if (per1k < 0.001) return `$${per1k.toFixed(4)}`
  if (per1k < 0.01) return `$${per1k.toFixed(3)}`
  return `$${per1k.toFixed(2)}`
}

function parseModelId(id: string): { provider: string; name: string } {
  const slash = id.indexOf('/')
  if (slash === -1) return { provider: '', name: id }
  return { provider: id.slice(0, slash), name: id.slice(slash + 1) }
}

function costTier(model: RequestyModel): 'budget' | 'standard' | 'premium' | 'unknown' {
  const cost = model.input_cost_per_million
  if (cost == null) return 'unknown'
  if (cost <= 0.15) return 'budget'
  if (cost <= 1.5) return 'standard'
  return 'premium'
}

const COST_TIER_STYLES = {
  budget: { label: 'Budget', color: 'text-green-600 dark:text-green-400', bg: 'bg-green-50 dark:bg-green-950 border-green-200 dark:border-green-800' },
  standard: { label: 'Standard', color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-950 border-amber-200 dark:border-amber-800' },
  premium: { label: 'Premium', color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-950 border-red-200 dark:border-red-800' },
  unknown: { label: '?', color: 'text-gray-400', bg: 'bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700' },
} as const

const PROVIDER_LABELS: Record<string, string> = {
  google: 'Google',
  openai: 'OpenAI',
  anthropic: 'Anthropic',
  meta: 'Meta',
  mistralai: 'Mistral',
  deepseek: 'DeepSeek',
}

interface ModelPreset {
  label: string
  description: string
  tier: 'budget' | 'standard' | 'premium'
  context: string
  reasoning: string
  response: string
}

const MODEL_PRESETS: ModelPreset[] = [
  {
    label: 'Budget',
    description: 'Lowest cost, good for simple tasks',
    tier: 'budget',
    context: 'google/gemini-2.5-flash-lite',
    reasoning: 'google/gemini-2.5-flash-lite',
    response: 'google/gemini-2.5-flash-lite',
  },
  {
    label: 'Balanced',
    description: 'Good quality at moderate cost',
    tier: 'standard',
    context: 'google/gemini-2.5-flash-lite',
    reasoning: 'google/gemini-2.5-flash',
    response: 'google/gemini-2.5-flash-lite',
  },
  {
    label: 'Premium',
    description: 'Best quality, higher cost',
    tier: 'premium',
    context: 'google/gemini-2.5-flash',
    reasoning: 'anthropic/claude-sonnet-4-20250514',
    response: 'google/gemini-2.5-flash',
  },
]

function ModelCostSummary({
  contextModel,
  reasoningModel,
  responseModel,
  models,
}: {
  contextModel: string
  reasoningModel: string
  responseModel: string
  models: RequestyModel[]
}) {
  const modelMap = useMemo(() => {
    const map = new Map<string, RequestyModel>()
    for (const m of models) map.set(m.id, m)
    return map
  }, [models])

  const ctx = modelMap.get(contextModel)
  const rsn = modelMap.get(reasoningModel)
  const rsp = modelMap.get(responseModel)

  const hasCosts = ctx?.input_cost_per_million != null || rsn?.input_cost_per_million != null || rsp?.input_cost_per_million != null

  if (!hasCosts) return null

  const rows: { label: string; model: RequestyModel | undefined; id: string }[] = [
    { label: 'Context', model: ctx, id: contextModel },
    { label: 'Reasoning', model: rsn, id: reasoningModel },
    { label: 'Response', model: rsp, id: responseModel },
  ]

  return (
    <div className="mt-3 p-3 rounded-lg bg-gray-50 dark:bg-gray-800/50 border border-gray-100 dark:border-gray-700">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 mb-2">Cost per 1K tokens</div>
      <div className="space-y-1.5">
        {rows.map(({ label, model, id }) => {
          const { name } = parseModelId(id)
          const displayName = model?.name ?? name
          const inp = model?.input_cost_per_million
          const out = model?.output_cost_per_million
          const tier = model ? costTier(model) : 'unknown'
          const ts = COST_TIER_STYLES[tier]
          return (
            <div key={label} className="flex items-center gap-2 text-xs">
              <span className="w-16 text-gray-500 dark:text-gray-400 shrink-0">{label}</span>
              <span className="flex-1 text-gray-700 dark:text-gray-300 truncate" title={id}>{displayName}</span>
              {inp != null ? (
                <span className="shrink-0 text-gray-500 dark:text-gray-400 tabular-nums">
                  <span className="text-gray-700 dark:text-gray-300">{formatCostPer1K(inp)}</span>
                  {' '}in
                  {out != null && <> / <span className="text-gray-700 dark:text-gray-300">{formatCostPer1K(out)}</span> out</>}
                </span>
              ) : (
                <span className="shrink-0 text-gray-400">—</span>
              )}
              <span className={`shrink-0 text-[9px] font-semibold uppercase px-1 py-0.5 rounded border ${ts.bg} ${ts.color}`}>
                {ts.label}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ModelPicker({
  label,
  description,
  value,
  options,
  models,
  onChange,
}: {
  label: string
  description: string
  value: string
  options: string[]
  models: RequestyModel[]
  onChange: (v: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)

  const modelMap = useMemo(() => {
    const map = new Map<string, RequestyModel>()
    for (const m of models) map.set(m.id, m)
    return map
  }, [models])

  const grouped = useMemo(() => {
    const q = search.toLowerCase()
    const filtered = options.filter(id => id.toLowerCase().includes(q))
    const groups = new Map<string, string[]>()
    for (const id of filtered) {
      const { provider } = parseModelId(id)
      const key = provider || 'other'
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key)!.push(id)
    }
    // Sort models within each group by input cost (cheapest first)
    for (const [, ids] of groups) {
      ids.sort((a, b) => {
        const ma = modelMap.get(a)
        const mb = modelMap.get(b)
        const ca = ma?.input_cost_per_million ?? Infinity
        const cb = mb?.input_cost_per_million ?? Infinity
        return ca - cb
      })
    }
    // Sort groups: put the provider of the current value first, then alphabetical
    const { provider: currentProvider } = parseModelId(value)
    const entries = [...groups.entries()].sort((a, b) => {
      if (a[0] === currentProvider) return -1
      if (b[0] === currentProvider) return 1
      return a[0].localeCompare(b[0])
    })
    return entries
  }, [options, search, value, modelMap])

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
        setSearch('')
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  // Focus search on open
  useEffect(() => {
    if (open) searchRef.current?.focus()
  }, [open])

  const selected = modelMap.get(value)
  const { provider: selProvider, name: selName } = parseModelId(value)
  const selTier = selected ? costTier(selected) : 'unknown'
  const tierStyle = COST_TIER_STYLES[selTier]

  return (
    <div ref={containerRef} className="relative">
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
        {label}
      </label>
      <p className="text-xs text-gray-400 dark:text-gray-400 mb-1.5">{description}</p>

      {/* Trigger button */}
      <button
        type="button"
        onClick={() => { setOpen(!open); setSearch('') }}
        className="w-full px-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-left flex items-center gap-3 hover:border-gray-300 dark:hover:border-gray-600 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="font-medium text-gray-900 dark:text-gray-100 truncate">{selName}</div>
          <div className="text-xs text-gray-400 dark:text-gray-500 truncate">
            {PROVIDER_LABELS[selProvider] || selProvider}
            {selected?.input_cost_per_million != null && (
              <> &middot; {formatCost(selected.input_cost_per_million)} in / {formatCost(selected.output_cost_per_million)} out per 1M tokens</>
            )}
          </div>
        </div>
        <span className={`shrink-0 text-[10px] font-semibold uppercase px-1.5 py-0.5 rounded border ${tierStyle.bg} ${tierStyle.color}`}>
          {tierStyle.label}
        </span>
        <svg className={`shrink-0 h-4 w-4 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 left-0 right-0 mt-1 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-xl max-h-72 flex flex-col">
          {/* Search */}
          <div className="p-2 border-b border-gray-100 dark:border-gray-700">
            <input
              ref={searchRef}
              type="text"
              placeholder="Search models..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full px-2.5 py-1.5 text-sm rounded-md border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-900 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            />
          </div>

          {/* Model list */}
          <div className="overflow-y-auto flex-1">
            {grouped.length === 0 && (
              <div className="px-3 py-4 text-sm text-gray-400 text-center">No models found</div>
            )}
            {grouped.map(([provider, ids]) => (
              <div key={provider}>
                <div className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500 bg-gray-50 dark:bg-gray-850 sticky top-0">
                  {PROVIDER_LABELS[provider] || provider}
                </div>
                {ids.map(id => {
                  const m = modelMap.get(id)
                  const { name } = parseModelId(id)
                  const tier = m ? costTier(m) : 'unknown'
                  const ts = COST_TIER_STYLES[tier]
                  const isSelected = id === value
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => { onChange(id); setOpen(false); setSearch('') }}
                      className={`w-full text-left px-3 py-2 flex items-center gap-2 text-sm transition-colors ${
                        isSelected
                          ? 'bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                          : 'text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-750'
                      }`}
                    >
                      {isSelected && (
                        <svg className="shrink-0 h-3.5 w-3.5 text-indigo-500" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                        </svg>
                      )}
                      {!isSelected && <span className="shrink-0 w-3.5" />}
                      <div className="flex-1 min-w-0">
                        <div className="truncate font-medium">{name}</div>
                        {m?.input_cost_per_million != null && (
                          <div className="text-[11px] text-gray-400 dark:text-gray-500">
                            {formatCost(m.input_cost_per_million)} in / {formatCost(m.output_cost_per_million)} out per 1M tokens
                          </div>
                        )}
                      </div>
                      <span className={`shrink-0 text-[9px] font-semibold uppercase px-1 py-0.5 rounded border ${ts.bg} ${ts.color}`}>
                        {ts.label}
                      </span>
                    </button>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
