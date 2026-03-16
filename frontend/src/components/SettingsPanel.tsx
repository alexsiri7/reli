import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { ModelSettings, UsageDashboard } from '../store'

type SettingsTab = 'models' | 'usage'

export function SettingsPanel() {
  const {
    modelSettings,
    availableModels,
    settingsLoading,
    modelsLoading,
    fetchModelSettings,
    fetchAvailableModels,
    closeSettings,
    usageDashboard,
    usageLoading,
    usagePeriod,
    fetchUsageDashboard,
    setUsagePeriod,
  } = useStore(
    useShallow(s => ({
      modelSettings: s.modelSettings,
      availableModels: s.availableModels,
      settingsLoading: s.settingsLoading,
      modelsLoading: s.modelsLoading,
      fetchModelSettings: s.fetchModelSettings,
      fetchAvailableModels: s.fetchAvailableModels,
      closeSettings: s.closeSettings,
      usageDashboard: s.usageDashboard,
      usageLoading: s.usageLoading,
      usagePeriod: s.usagePeriod,
      fetchUsageDashboard: s.fetchUsageDashboard,
      setUsagePeriod: s.setUsagePeriod,
    })),
  )

  const [tab, setTab] = useState<SettingsTab>('models')

  useEffect(() => {
    fetchModelSettings()
    fetchAvailableModels()
  }, [fetchModelSettings, fetchAvailableModels])

  useEffect(() => {
    if (tab === 'usage' && !usageDashboard) {
      fetchUsageDashboard()
    }
  }, [tab, usageDashboard, fetchUsageDashboard])

  const modelOptions = availableModels.map(m => m.id).sort()
  const isLoading = settingsLoading || modelsLoading

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white dark:bg-gray-900 rounded-xl shadow-2xl w-full max-w-lg mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header with tabs */}
        <div className="px-6 pt-4 pb-0 border-b border-gray-200 dark:border-gray-700">
          <div className="flex items-center justify-between mb-3">
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
          <div className="flex gap-4">
            <TabButton active={tab === 'models'} onClick={() => setTab('models')}>Models</TabButton>
            <TabButton active={tab === 'usage'} onClick={() => setTab('usage')}>Usage</TabButton>
          </div>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-5">
          {tab === 'models' && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">AI Models</h3>
              <p className="text-xs text-gray-400 dark:text-gray-500 mb-4">
                Select which models to use for each stage of the chat pipeline.
              </p>

              {isLoading ? (
                <div className="space-y-3 animate-pulse">
                  <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
                  <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
                  <div className="h-10 bg-gray-200 dark:bg-gray-700 rounded" />
                </div>
              ) : modelSettings ? (
                <SettingsForm
                  key={`${modelSettings.context}|${modelSettings.reasoning}|${modelSettings.response}|${modelSettings.chat_context_window}`}
                  initial={modelSettings}
                  modelOptions={modelOptions}
                  onClose={closeSettings}
                />
              ) : (
                <p className="text-sm text-gray-400">Failed to load settings.</p>
              )}
            </div>
          )}

          {tab === 'usage' && (
            <UsageTab
              dashboard={usageDashboard}
              loading={usageLoading}
              period={usagePeriod}
              onPeriodChange={setUsagePeriod}
            />
          )}
        </div>

        {/* Footer for models tab when loading/failed, or usage tab */}
        {tab === 'models' && (isLoading || !modelSettings) && (
          <div className="flex items-center justify-end px-6 py-4 border-t border-gray-200 dark:border-gray-700">
            <button
              onClick={closeSettings}
              className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
            >
              Close
            </button>
          </div>
        )}

        {tab === 'usage' && (
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

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`pb-2 text-sm font-medium border-b-2 transition-colors ${
        active
          ? 'border-indigo-500 text-indigo-600 dark:text-indigo-400'
          : 'border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300'
      }`}
    >
      {children}
    </button>
  )
}

const PERIOD_OPTIONS = [
  { value: 'today', label: 'Today' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'all', label: 'All time' },
]

function UsageTab({
  dashboard,
  loading,
  period,
  onPeriodChange,
}: {
  dashboard: UsageDashboard | null
  loading: boolean
  period: string
  onPeriodChange: (p: string) => void
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300">Token Usage</h3>
        <select
          value={period}
          onChange={e => onPeriodChange(e.target.value)}
          className="px-2 py-1 text-xs rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400"
        >
          {PERIOD_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div className="space-y-3 animate-pulse">
          <div className="h-20 bg-gray-200 dark:bg-gray-700 rounded" />
          <div className="h-32 bg-gray-200 dark:bg-gray-700 rounded" />
        </div>
      ) : dashboard ? (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-3 gap-3 mb-5">
            <StatCard label="Total Tokens" value={formatNumber(dashboard.total_tokens)} />
            <StatCard label="API Calls" value={formatNumber(dashboard.api_calls)} />
            <StatCard label="Est. Cost" value={formatCost(dashboard.cost_usd)} />
          </div>

          {/* Model breakdown */}
          {dashboard.per_model.length > 0 && (
            <div className="mb-5">
              <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
                Model Breakdown
              </h4>
              <div className="border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
                      <th className="text-left px-3 py-2 font-medium">Model</th>
                      <th className="text-right px-3 py-2 font-medium">Tokens</th>
                      <th className="text-right px-3 py-2 font-medium">Calls</th>
                      <th className="text-right px-3 py-2 font-medium">Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
                    {dashboard.per_model.map(m => (
                      <tr key={m.model} className="text-gray-700 dark:text-gray-300">
                        <td className="px-3 py-2 truncate max-w-[180px]" title={m.model}>
                          {shortModelName(m.model)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatNumber(m.total_tokens)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatNumber(m.api_calls)}</td>
                        <td className="px-3 py-2 text-right tabular-nums">{formatCost(m.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Daily breakdown */}
          {dashboard.daily.length > 0 && (
            <div>
              <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400 uppercase tracking-wide mb-2">
                Daily Usage
              </h4>
              <div className="space-y-1">
                {dashboard.daily.map(d => {
                  const maxTokens = Math.max(...dashboard.daily.map(dd => dd.total_tokens), 1)
                  const pct = (d.total_tokens / maxTokens) * 100
                  return (
                    <div key={d.date} className="flex items-center gap-2 text-xs">
                      <span className="w-16 text-gray-500 dark:text-gray-400 shrink-0">
                        {formatDate(d.date)}
                      </span>
                      <div className="flex-1 h-4 bg-gray-100 dark:bg-gray-800 rounded overflow-hidden">
                        <div
                          className="h-full bg-indigo-500/70 rounded"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="w-16 text-right text-gray-600 dark:text-gray-300 tabular-nums shrink-0">
                        {formatNumber(d.total_tokens)}
                      </span>
                      <span className="w-14 text-right text-gray-400 dark:text-gray-500 tabular-nums shrink-0">
                        {formatCost(d.cost_usd)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {dashboard.per_model.length === 0 && dashboard.daily.length === 0 && (
            <p className="text-sm text-gray-400 dark:text-gray-500 text-center py-6">
              No usage data for this period.
            </p>
          )}
        </>
      ) : (
        <p className="text-sm text-gray-400">Failed to load usage data.</p>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-gray-50 dark:bg-gray-800 rounded-lg px-3 py-3 text-center">
      <div className="text-lg font-semibold text-gray-900 dark:text-white tabular-nums">{value}</div>
      <div className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{label}</div>
    </div>
  )
}

function SettingsForm({
  initial,
  modelOptions,
  onClose,
}: {
  initial: ModelSettings
  modelOptions: string[]
  onClose: () => void
}) {
  const updateModelSettings = useStore(s => s.updateModelSettings)
  const [context, setContext] = useState(initial.context)
  const [reasoning, setReasoning] = useState(initial.reasoning)
  const [response, setResponse] = useState(initial.response)
  const [chatContextWindow, setChatContextWindow] = useState(initial.chat_context_window)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const hasChanges =
    context !== initial.context ||
    reasoning !== initial.reasoning ||
    response !== initial.response ||
    chatContextWindow !== initial.chat_context_window

  const handleSave = async () => {
    setSaving(true)
    setSaved(false)
    await updateModelSettings({ context, reasoning, response, chat_context_window: chatContextWindow })
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <>
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

      <div className="mt-6 pt-5 border-t border-gray-200 dark:border-gray-700">
        <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">Chat</h3>
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Context Window Size
          </label>
          <p className="text-xs text-gray-400 dark:text-gray-500 mb-1.5">
            Number of recent messages included as context for AI responses (1–50)
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

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toString()
}

function formatCost(usd: number): string {
  if (usd < 0.01) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function shortModelName(model: string): string {
  // Strip common prefixes like "google/" or "openai/"
  const parts = model.split('/')
  return parts.length > 1 ? parts.slice(1).join('/') : model
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr + 'T00:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
