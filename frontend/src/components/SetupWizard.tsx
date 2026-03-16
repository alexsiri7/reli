import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'

const MODEL_COST_ESTIMATES: Record<string, string> = {
  'google/gemini-2.5-flash-lite': '~$0.01/conversation',
  'google/gemini-2.5-flash': '~$0.02/conversation',
  'google/gemini-3-flash-preview': '~$0.03/conversation',
  'google/gemini-2.5-pro': '~$0.10/conversation',
  'openai/gpt-4o-mini': '~$0.01/conversation',
  'openai/gpt-4o': '~$0.05/conversation',
  'openai/gpt-4.1-mini': '~$0.02/conversation',
  'openai/gpt-4.1': '~$0.08/conversation',
  'anthropic/claude-3.5-haiku': '~$0.02/conversation',
  'anthropic/claude-sonnet-4': '~$0.08/conversation',
}

function getCostEstimate(modelId: string): string {
  if (MODEL_COST_ESTIMATES[modelId]) return MODEL_COST_ESTIMATES[modelId]!
  const lower = modelId.toLowerCase()
  if (lower.includes('flash-lite') || lower.includes('mini')) return '~$0.01/conv'
  if (lower.includes('flash') || lower.includes('haiku')) return '~$0.02/conv'
  if (lower.includes('pro') || lower.includes('opus') || lower.includes('gpt-4o')) return '~$0.05-0.10/conv'
  return ''
}

export function SetupWizard() {
  const {
    currentUser,
    setupDisplayName,
    availableModels,
    modelsLoading,
    fetchAvailableModels,
    completeSetup,
  } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      setupDisplayName: s.setupDisplayName,
      availableModels: s.availableModels,
      modelsLoading: s.modelsLoading,
      fetchAvailableModels: s.fetchAvailableModels,
      completeSetup: s.completeSetup,
    })),
  )

  const [step, setStep] = useState(0)
  const [displayName, setDisplayName] = useState(setupDisplayName || currentUser?.name || '')
  const [apiKey, setApiKey] = useState('')
  const [contextModel, setContextModel] = useState('')
  const [reasoningModel, setReasoningModel] = useState('')
  const [responseModel, setResponseModel] = useState('')
  const [saving, setSaving] = useState(false)
  const [apiKeyError, setApiKeyError] = useState('')

  // Fetch available models when user enters API key step
  useEffect(() => {
    if (step === 1 && apiKey.length > 10) {
      // After entering key, try to fetch models to validate it
      const timer = setTimeout(() => {
        fetchAvailableModels()
      }, 500)
      return () => clearTimeout(timer)
    }
  }, [step, apiKey, fetchAvailableModels])

  // Compute default model choices from available models
  const modelIds = availableModels.map(m => m.id)
  const effectiveContextModel = contextModel && modelIds.includes(contextModel)
    ? contextModel
    : modelIds.find(id => id.includes('gemini-2.5-flash-lite')) || modelIds[0] || ''
  const effectiveReasoningModel = reasoningModel && modelIds.includes(reasoningModel)
    ? reasoningModel
    : modelIds.find(id => id.includes('gemini-3-flash-preview')) || modelIds.find(id => id.includes('gemini-2.5-flash')) || modelIds[0] || ''
  const effectiveResponseModel = responseModel && modelIds.includes(responseModel)
    ? responseModel
    : modelIds.find(id => id.includes('gemini-2.5-flash-lite')) || modelIds[0] || ''

  const handleComplete = async () => {
    if (!apiKey.trim()) {
      setApiKeyError('API key is required to use Reli')
      setStep(1)
      return
    }
    setSaving(true)
    await completeSetup({
      display_name: displayName.trim(),
      requesty_api_key: apiKey.trim(),
      context_model: effectiveContextModel || undefined,
      reasoning_model: effectiveReasoningModel || undefined,
      response_model: effectiveResponseModel || undefined,
    })
    setSaving(false)
  }

  const modelOptions = availableModels.map(m => m.id).sort()

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900 p-4">
      <div className="w-full max-w-md bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Progress bar */}
        <div className="h-1 bg-gray-100 dark:bg-gray-700">
          <div
            className="h-full bg-indigo-500 transition-all duration-300"
            style={{ width: `${((step + 1) / 3) * 100}%` }}
          />
        </div>

        <div className="px-6 py-8">
          {/* Step 0: Welcome + Display Name */}
          {step === 0 && (
            <div className="space-y-6">
              <div className="text-center">
                <img src="/logo.svg" alt="Reli" className="h-12 w-12 rounded-lg mx-auto mb-3" />
                <h1 className="text-xl font-bold text-gray-900 dark:text-white">Welcome to Reli</h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">
                  Let's get you set up in just a couple of steps.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  What should we call you?
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  placeholder="Your name"
                  autoFocus
                  className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:focus:ring-indigo-500"
                />
              </div>

              <button
                onClick={() => setStep(1)}
                className="w-full px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
              >
                Continue
              </button>
            </div>
          )}

          {/* Step 1: API Key */}
          {step === 1 && (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Connect your AI</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Reli uses your own API key to power conversations. We route through Requesty to give you access to all major models.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
                  Requesty API Key
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={e => { setApiKey(e.target.value); setApiKeyError('') }}
                  placeholder="rqst-..."
                  autoFocus
                  className={`w-full px-3 py-2 text-sm rounded-lg border bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:focus:ring-indigo-500 ${
                    apiKeyError
                      ? 'border-red-300 dark:border-red-600'
                      : 'border-gray-200 dark:border-gray-700'
                  }`}
                />
                {apiKeyError && (
                  <p className="text-xs text-red-600 dark:text-red-400 mt-1">{apiKeyError}</p>
                )}
                <p className="text-xs text-gray-400 dark:text-gray-500 mt-2">
                  Don't have a key?{' '}
                  <a
                    href="https://requesty.ai"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-500 hover:text-indigo-600 font-medium"
                  >
                    Sign up at Requesty
                  </a>
                  {' '}(free tier available) or{' '}
                  <a
                    href="https://platform.openai.com/api-keys"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-indigo-500 hover:text-indigo-600 font-medium"
                  >
                    use an OpenAI key
                  </a>
                  .
                </p>
              </div>

              <div className="bg-gray-50 dark:bg-gray-900/50 rounded-lg p-3 text-xs text-gray-500 dark:text-gray-400">
                <p className="font-medium text-gray-600 dark:text-gray-300 mb-1">Typical costs per conversation:</p>
                <ul className="space-y-0.5">
                  <li>Gemini Flash Lite &mdash; ~$0.01</li>
                  <li>GPT-4o Mini &mdash; ~$0.01</li>
                  <li>Gemini Flash / Claude Haiku &mdash; ~$0.02</li>
                  <li>GPT-4o / Claude Sonnet &mdash; ~$0.05</li>
                  <li>Gemini Pro &mdash; ~$0.10</li>
                </ul>
              </div>

              <div className="flex gap-3">
                <button
                  onClick={() => setStep(0)}
                  className="px-4 py-2.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={() => {
                    if (!apiKey.trim()) {
                      setApiKeyError('API key is required to use Reli')
                      return
                    }
                    fetchAvailableModels()
                    setStep(2)
                  }}
                  className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
                >
                  Continue
                </button>
              </div>
            </div>
          )}

          {/* Step 2: Model Preferences */}
          {step === 2 && (
            <div className="space-y-6">
              <div>
                <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Choose your models</h2>
                <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                  Pick which AI models to use. You can change these anytime in Settings.
                </p>
              </div>

              {modelsLoading ? (
                <div className="space-y-3 animate-pulse">
                  <div className="h-16 bg-gray-200 dark:bg-gray-700 rounded" />
                  <div className="h-16 bg-gray-200 dark:bg-gray-700 rounded" />
                  <div className="h-16 bg-gray-200 dark:bg-gray-700 rounded" />
                </div>
              ) : modelOptions.length > 0 ? (
                <div className="space-y-4">
                  <ModelSelectField
                    label="Context Model"
                    description="Gathers context from your data"
                    value={effectiveContextModel}
                    options={modelOptions}
                    onChange={setContextModel}
                  />
                  <ModelSelectField
                    label="Reasoning Model"
                    description="Plans actions and makes decisions"
                    value={effectiveReasoningModel}
                    options={modelOptions}
                    onChange={setReasoningModel}
                  />
                  <ModelSelectField
                    label="Response Model"
                    description="Generates the final reply"
                    value={effectiveResponseModel}
                    options={modelOptions}
                    onChange={setResponseModel}
                  />
                </div>
              ) : (
                <div className="text-sm text-gray-500 dark:text-gray-400 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-lg p-3">
                  Could not load models. Your API key may be invalid, or the model service is temporarily unavailable. You can skip this step and configure models later in Settings.
                </div>
              )}

              <div className="flex gap-3">
                <button
                  onClick={() => setStep(1)}
                  className="px-4 py-2.5 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
                >
                  Back
                </button>
                <button
                  onClick={handleComplete}
                  disabled={saving}
                  className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  {saving ? 'Setting up...' : 'Start using Reli'}
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ModelSelectField({
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
  const cost = getCostEstimate(value)
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-0.5">
        {label}
      </label>
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-1">{description}</p>
      <div className="flex items-center gap-2">
        <select
          value={value}
          onChange={e => onChange(e.target.value)}
          className="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500"
        >
          {value && !options.includes(value) && (
            <option value={value}>{value}</option>
          )}
          {options.map(id => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>
        {cost && (
          <span className="text-xs text-gray-400 dark:text-gray-500 whitespace-nowrap">{cost}</span>
        )}
      </div>
    </div>
  )
}
