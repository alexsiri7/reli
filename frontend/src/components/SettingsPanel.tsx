import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { ModelSettings, UserSettings, UserProfileRelationship } from '../store'
import { useTheme, setTheme } from '../hooks/useTheme'

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
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const hasModelChanges =
    context !== initial.context ||
    reasoning !== initial.reasoning ||
    response !== initial.response ||
    chatContextWindow !== initial.chat_context_window

  const hasApiKeyChange = reqApiKey.length > 0

  const hasChanges = hasModelChanges || hasApiKeyChange

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
        <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
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
          <p className="text-xs text-gray-400 dark:text-gray-500 mt-1">
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
        <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
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
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-1.5">
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

function MyProfileSection() {
  const { userProfile, userProfileLoading, updateUserThing, fetchUserProfile } = useStore(
    useShallow(s => ({
      userProfile: s.userProfile,
      userProfileLoading: s.userProfileLoading,
      updateUserThing: s.updateUserThing,
      fetchUserProfile: s.fetchUserProfile,
    })),
  )

  const [editing, setEditing] = useState(false)
  const [editName, setEditName] = useState('')
  const [editData, setEditData] = useState<Record<string, string>>({})
  const [newFieldKey, setNewFieldKey] = useState('')
  const [newFieldValue, setNewFieldValue] = useState('')
  const [profileSaving, setProfileSaving] = useState(false)
  const [profileSaved, setProfileSaved] = useState(false)

  // Non-editable system keys that shouldn't be shown in the editable fields
  const systemKeys = new Set(['google_id'])

  const startEditing = () => {
    if (!userProfile) return
    setEditName(userProfile.thing.title)
    const data: Record<string, string> = {}
    if (userProfile.thing.data) {
      for (const [k, v] of Object.entries(userProfile.thing.data)) {
        if (!systemKeys.has(k)) {
          data[k] = String(v ?? '')
        }
      }
    }
    setEditData(data)
    setNewFieldKey('')
    setNewFieldValue('')
    setEditing(true)
  }

  const handleSaveProfile = async () => {
    if (!userProfile) return
    setProfileSaving(true)
    setProfileSaved(false)

    // Rebuild data preserving system keys
    const newData: Record<string, unknown> = {}
    if (userProfile.thing.data) {
      for (const key of systemKeys) {
        if (key in userProfile.thing.data) {
          newData[key] = userProfile.thing.data[key]
        }
      }
    }
    for (const [k, v] of Object.entries(editData)) {
      newData[k] = v
    }
    // Add the new field if both key and value are provided
    if (newFieldKey.trim() && newFieldValue.trim()) {
      newData[newFieldKey.trim()] = newFieldValue.trim()
    }

    await updateUserThing({ title: editName, data: newData })
    await fetchUserProfile()
    setProfileSaving(false)
    setProfileSaved(true)
    setEditing(false)
    setTimeout(() => setProfileSaved(false), 2000)
  }

  const removeField = (key: string) => {
    const updated = { ...editData }
    delete updated[key]
    setEditData(updated)
  }

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
        <p className="text-xs text-gray-400 dark:text-gray-500">Profile not available.</p>
      </div>
    )
  }

  const { thing, relationships } = userProfile
  const displayData = thing.data
    ? Object.entries(thing.data).filter(([k]) => !systemKeys.has(k))
    : []

  // Format relationship type for display: replace underscores/hyphens with spaces
  const formatRelType = (type: string) => type.replace(/[_-]/g, ' ')

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">My Profile</h3>
        {profileSaved && (
          <span className="text-xs text-green-600 dark:text-green-400">Saved</span>
        )}
      </div>
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
        What Reli knows about you. Edit your name and personal details.
      </p>

      {editing ? (
        <div className="space-y-3">
          {/* Name */}
          <div>
            <label className="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">Name</label>
            <input
              type="text"
              value={editName}
              onChange={e => setEditName(e.target.value)}
              className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400"
            />
          </div>

          {/* Editable data fields */}
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

          {/* Add new field */}
          <div className="flex items-center gap-2 pt-1">
            <input
              type="text"
              placeholder="Field name"
              value={newFieldKey}
              onChange={e => setNewFieldKey(e.target.value)}
              className="w-24 flex-shrink-0 px-3 py-1.5 text-sm rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 placeholder:text-gray-300 dark:placeholder:text-gray-600"
            />
            <input
              type="text"
              placeholder="Value"
              value={newFieldValue}
              onChange={e => setNewFieldValue(e.target.value)}
              className="flex-1 px-3 py-1.5 text-sm rounded-lg border border-dashed border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 placeholder:text-gray-300 dark:placeholder:text-gray-600"
            />
            <div className="w-6" /> {/* spacer to align with remove buttons */}
          </div>

          {/* Edit actions */}
          <div className="flex items-center justify-end gap-2 pt-2">
            <button
              onClick={() => setEditing(false)}
              className="px-3 py-1.5 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveProfile}
              disabled={profileSaving || !editName.trim()}
              className="px-3 py-1.5 text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
            >
              {profileSaving ? 'Saving...' : 'Save Profile'}
            </button>
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          {/* Display name */}
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-indigo-100 dark:bg-indigo-900 flex items-center justify-center text-indigo-600 dark:text-indigo-300 font-medium text-sm">
              {thing.title.charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-white">{thing.title}</p>
              <p className="text-xs text-gray-400 dark:text-gray-500">{thing.type_hint}</p>
            </div>
          </div>

          {/* Data fields */}
          {displayData.length > 0 && (
            <div className="space-y-1.5 pl-[52px]">
              {displayData.map(([key, value]) => (
                <div key={key} className="flex items-center gap-2 text-xs">
                  <span className="text-gray-400 dark:text-gray-500 capitalize">{key}:</span>
                  <span className="text-gray-700 dark:text-gray-300">{String(value)}</span>
                </div>
              ))}
            </div>
          )}

          {/* Edit button */}
          <div className="pl-[52px]">
            <button
              onClick={startEditing}
              className="text-xs text-indigo-500 hover:text-indigo-600 dark:text-indigo-400 dark:hover:text-indigo-300 transition-colors"
            >
              Edit profile
            </button>
          </div>

          {/* Relationships (read-only) */}
          {relationships.length > 0 && (
            <div className="mt-3 pt-3 border-t border-gray-100 dark:border-gray-800">
              <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">Learned Relationships</h4>
              <div className="space-y-1.5">
                {relationships.map((rel: UserProfileRelationship) => (
                  <div key={rel.id} className="flex items-center gap-2 text-xs">
                    <span className="text-gray-400 dark:text-gray-500 capitalize">{formatRelType(rel.relationship_type)}:</span>
                    <span className="text-gray-700 dark:text-gray-300">{rel.related_thing_title}</span>
                    {rel.direction === 'incoming' && (
                      <span className="text-gray-300 dark:text-gray-600 text-[10px]">(incoming)</span>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
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

  return (
    <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
      <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Appearance</h3>
      <div className="flex gap-2">
        {themeOptions.map(opt => (
          <button
            key={opt.value}
            onClick={() => setTheme(opt.value)}
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
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-1.5">{description}</p>
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
