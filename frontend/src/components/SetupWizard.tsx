import { useEffect, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import type { ModelCost } from '../store'

type Step = 'welcome' | 'api-key' | 'models' | 'complete'

export function SetupWizard() {
  const {
    currentUser,
    modelCosts,
    setupLoading,
    availableModels,
    completeSetup,
    fetchModelCosts,
    fetchAvailableModels,
  } = useStore(
    useShallow(s => ({
      currentUser: s.currentUser,
      modelCosts: s.modelCosts,
      setupLoading: s.setupLoading,
      availableModels: s.availableModels,
      completeSetup: s.completeSetup,
      fetchModelCosts: s.fetchModelCosts,
      fetchAvailableModels: s.fetchAvailableModels,
    })),
  )

  const [step, setStep] = useState<Step>('welcome')
  const [displayName, setDisplayName] = useState(currentUser?.name ?? '')
  const [apiKey, setApiKey] = useState('')
  const [contextModel, setContextModel] = useState('')
  const [reasoningModel, setReasoningModel] = useState('')
  const [responseModel, setResponseModel] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [keyVisible, setKeyVisible] = useState(false)
  const [validatingKey, setValidatingKey] = useState(false)

  useEffect(() => {
    fetchModelCosts()
    fetchAvailableModels()
  }, [fetchModelCosts, fetchAvailableModels])

  const validateApiKey = async () => {
    if (!apiKey.trim()) {
      setError('API key is required')
      return false
    }
    setValidatingKey(true)
    setError(null)
    try {
      const res = await fetch('https://router.requesty.ai/v1/models', {
        headers: { Authorization: `Bearer ${apiKey.trim()}` },
      })
      if (!res.ok) {
        setError('Invalid API key. Please check your key and try again.')
        return false
      }
      return true
    } catch {
      // Network error — allow proceeding, key will be validated on first use
      return true
    } finally {
      setValidatingKey(false)
    }
  }

  const handleNext = async () => {
    if (step === 'welcome') {
      if (!displayName.trim()) {
        setError('Please enter your name')
        return
      }
      setError(null)
      setStep('api-key')
    } else if (step === 'api-key') {
      const valid = await validateApiKey()
      if (valid) {
        setStep('models')
      }
    } else if (step === 'models') {
      const success = await completeSetup({
        display_name: displayName.trim(),
        api_key: apiKey.trim(),
        ...(contextModel && { context_model: contextModel }),
        ...(reasoningModel && { reasoning_model: reasoningModel }),
        ...(responseModel && { response_model: responseModel }),
      })
      if (success) {
        setStep('complete')
      }
    }
  }

  const handleBack = () => {
    setError(null)
    if (step === 'api-key') setStep('welcome')
    else if (step === 'models') setStep('api-key')
  }

  const costTiers: Record<string, ModelCost[]> = {}
  for (const m of modelCosts) {
    if (!costTiers[m.tier]) costTiers[m.tier] = []
    costTiers[m.tier].push(m)
  }

  const tierOrder = ['budget', 'standard', 'premium']
  const tierLabels: Record<string, string> = {
    budget: 'Budget (~$0.01/conversation)',
    standard: 'Standard (~$0.02-0.03/conversation)',
    premium: 'Premium (~$0.05-0.10/conversation)',
  }

  const modelOptions = availableModels.map(m => m.id).sort()

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-50 dark:bg-gray-900 p-4">
      <div className="w-full max-w-lg bg-white dark:bg-gray-800 rounded-xl shadow-lg border border-gray-200 dark:border-gray-700 overflow-hidden">
        {/* Progress bar */}
        <div className="flex h-1 bg-gray-100 dark:bg-gray-700">
          {(['welcome', 'api-key', 'models'] as Step[]).map((s, i) => (
            <div
              key={s}
              className={`flex-1 transition-colors duration-300 ${
                i <= ['welcome', 'api-key', 'models'].indexOf(step)
                  ? 'bg-indigo-500'
                  : 'bg-transparent'
              }`}
            />
          ))}
        </div>

        <div className="px-6 py-6 sm:px-8 sm:py-8">
          {step === 'welcome' && (
            <div className="space-y-5">
              <div className="flex flex-col items-center gap-3">
                <img src="/logo.svg" alt="Reli" className="h-14 w-14 rounded-lg" />
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Welcome to Reli</h1>
                <p className="text-sm text-gray-500 dark:text-gray-400 text-center">
                  Let's get you set up. This will only take a minute.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  What should we call you?
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={e => setDisplayName(e.target.value)}
                  placeholder="Your name"
                  autoFocus
                  className="w-full px-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-transparent"
                  onKeyDown={e => e.key === 'Enter' && handleNext()}
                />
              </div>
            </div>
          )}

          {step === 'api-key' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Connect your AI</h2>
                <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
                  Reli uses{' '}
                  <a href="https://requesty.ai" target="_blank" rel="noopener noreferrer" className="text-indigo-600 dark:text-indigo-400 hover:underline">
                    Requesty
                  </a>{' '}
                  to access AI models. Enter your API key to get started.
                </p>
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Requesty API Key
                </label>
                <div className="relative">
                  <input
                    type={keyVisible ? 'text' : 'password'}
                    value={apiKey}
                    onChange={e => { setApiKey(e.target.value); setError(null) }}
                    placeholder="sk-..."
                    autoFocus
                    className="w-full px-3 py-2.5 pr-10 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-transparent font-mono"
                    onKeyDown={e => e.key === 'Enter' && handleNext()}
                  />
                  <button
                    type="button"
                    onClick={() => setKeyVisible(!keyVisible)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
                    aria-label={keyVisible ? 'Hide API key' : 'Show API key'}
                  >
                    {keyVisible ? (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88" />
                      </svg>
                    ) : (
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M2.036 12.322a1.012 1.012 0 0 1 0-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178Z" />
                        <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
                      </svg>
                    )}
                  </button>
                </div>
                <p className="mt-2 text-xs text-gray-400 dark:text-gray-500">
                  Don't have a key?{' '}
                  <a href="https://app.requesty.ai" target="_blank" rel="noopener noreferrer" className="text-indigo-600 dark:text-indigo-400 hover:underline">
                    Sign up at Requesty
                  </a>{' '}
                  to get one. Requesty routes to OpenAI, Anthropic, Google, and more.
                </p>
              </div>

              {modelCosts.length > 0 && (
                <div className="bg-gray-50 dark:bg-gray-700/50 rounded-lg p-4">
                  <h3 className="text-xs font-semibold text-gray-600 dark:text-gray-300 uppercase tracking-wide mb-2">
                    Estimated costs
                  </h3>
                  <div className="space-y-2">
                    {tierOrder.map(tier => {
                      const models = costTiers[tier]
                      if (!models?.length) return null
                      return (
                        <div key={tier}>
                          <p className="text-xs font-medium text-gray-500 dark:text-gray-400">
                            {tierLabels[tier]}
                          </p>
                          <p className="text-xs text-gray-400 dark:text-gray-500">
                            {models.map(m => m.name).join(', ')}
                          </p>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {step === 'models' && (
            <div className="space-y-5">
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">Choose your models</h2>
                <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
                  Reli uses three AI agents. Pick a model for each, or leave blank for defaults.
                </p>
              </div>

              <div className="space-y-4">
                <ModelPickerField
                  label="Context Model"
                  description="Gathers relevant context from your data"
                  value={contextModel}
                  options={modelOptions}
                  onChange={setContextModel}
                  defaultHint="google/gemini-2.5-flash-lite"
                />
                <ModelPickerField
                  label="Reasoning Model"
                  description="Plans actions and makes decisions"
                  value={reasoningModel}
                  options={modelOptions}
                  onChange={setReasoningModel}
                  defaultHint="google/gemini-3-flash-preview"
                />
                <ModelPickerField
                  label="Response Model"
                  description="Generates the final reply"
                  value={responseModel}
                  options={modelOptions}
                  onChange={setResponseModel}
                  defaultHint="google/gemini-2.5-flash-lite"
                />
              </div>

              <p className="text-xs text-gray-400 dark:text-gray-500">
                You can change these anytime in Settings.
              </p>
            </div>
          )}

          {step === 'complete' && (
            <div className="space-y-5 text-center py-4">
              <div className="flex justify-center">
                <div className="h-16 w-16 rounded-full bg-green-100 dark:bg-green-900/30 flex items-center justify-center">
                  <svg className="h-8 w-8 text-green-600 dark:text-green-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                  </svg>
                </div>
              </div>
              <div>
                <h2 className="text-xl font-bold text-gray-900 dark:text-white">You're all set!</h2>
                <p className="mt-1.5 text-sm text-gray-500 dark:text-gray-400">
                  Start chatting with Reli to manage your tasks, notes, and more.
                </p>
              </div>
            </div>
          )}

          {/* Error display */}
          {error && (
            <div className="mt-4 px-3 py-2 text-sm text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-700 rounded-lg">
              {error}
            </div>
          )}

          {/* Navigation buttons */}
          <div className="flex items-center justify-between mt-6 pt-4 border-t border-gray-200 dark:border-gray-700">
            {step !== 'welcome' && step !== 'complete' ? (
              <button
                onClick={handleBack}
                className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg transition-colors"
              >
                Back
              </button>
            ) : (
              <div />
            )}

            {step !== 'complete' ? (
              <button
                onClick={handleNext}
                disabled={setupLoading || validatingKey}
                className="px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
              >
                {validatingKey ? 'Validating...' : setupLoading ? 'Saving...' : step === 'models' ? 'Finish Setup' : 'Continue'}
              </button>
            ) : (
              <button
                onClick={() => window.location.reload()}
                className="w-full px-5 py-2.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg transition-colors"
              >
                Get Started
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function ModelPickerField({
  label,
  description,
  value,
  options,
  onChange,
  defaultHint,
}: {
  label: string
  description: string
  value: string
  options: string[]
  onChange: (v: string) => void
  defaultHint: string
}) {
  return (
    <div>
      <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-0.5">
        {label}
      </label>
      <p className="text-xs text-gray-400 dark:text-gray-500 mb-1.5">{description}</p>
      <select
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500"
      >
        <option value="">Default ({defaultHint})</option>
        {options.map(id => (
          <option key={id} value={id}>{id}</option>
        ))}
      </select>
    </div>
  )
}
