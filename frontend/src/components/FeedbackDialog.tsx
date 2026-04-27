import { useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'
import { capturePageToCanvas, isWithinSizeLimit } from '../lib/screenshot'
import { ScreenshotEditor } from './ScreenshotEditor'

const CATEGORIES = [
  { value: 'bug', label: 'Bug Report' },
  { value: 'feature', label: 'Feature Request' },
  { value: 'other', label: 'Other Feedback' },
]

export function FeedbackDialog() {
  const { closeFeedback, submitFeedback } = useStore(
    useShallow(s => ({
      closeFeedback: s.closeFeedback,
      submitFeedback: s.submitFeedback,
    })),
  )

  const [category, setCategory] = useState('bug')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [result, setResult] = useState<{ success: boolean; issueUrl?: string; error?: string } | null>(null)
  const [captureStep, setCaptureStep] = useState<'form' | 'capturing' | 'editing'>('form')
  const [capturedCanvas, setCapturedCanvas] = useState<HTMLCanvasElement | null>(null)
  const [screenshotBase64, setScreenshotBase64] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDivElement>(null)

  const handleCapture = async () => {
    setCaptureStep('capturing')
    await new Promise(r => setTimeout(r, 350))
    try {
      const canvas = await capturePageToCanvas()
      setCapturedCanvas(canvas)
      setCaptureStep('editing')
    } catch {
      setCaptureStep('form')
    }
  }

  const handleEditorDone = (base64: string) => {
    if (!isWithinSizeLimit(base64)) {
      setResult({ success: false, error: 'Screenshot is too large (max 2MB). Try again.' })
    } else {
      setScreenshotBase64(base64)
    }
    setCaptureStep('form')
    setCapturedCanvas(null)
  }

  const handleEditorCancel = () => {
    setCaptureStep('form')
    setCapturedCanvas(null)
  }

  const handleSubmit = async () => {
    if (!message.trim()) return
    setSubmitting(true)
    setResult(null)
    try {
      const res = await submitFeedback({
        category,
        message: message.trim(),
        user_agent: navigator.userAgent,
        url: window.location.href,
        screenshot_base64: screenshotBase64 ?? undefined,
      })
      setResult(res)
      if (res.success) {
        setMessage('')
      }
    } catch {
      setResult({ success: false, error: 'Failed to submit feedback.' })
    } finally {
      setSubmitting(false)
    }
  }

  if (captureStep === 'capturing') return null

  if (captureStep === 'editing' && capturedCanvas) {
    return (
      <ScreenshotEditor
        canvas={capturedCanvas}
        onDone={handleEditorDone}
        onCancel={handleEditorCancel}
      />
    )
  }

  return (
    <div ref={dialogRef} data-screenshot-exclude className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-surface-container-low rounded-xl shadow-2xl w-full max-w-md mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">Send Feedback</h2>
          <button
            onClick={closeFeedback}
            className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-800 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
            aria-label="Close"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* Content */}
        <div className="px-6 py-5 space-y-4">
          {result?.success ? (
            <div className="text-center py-4">
              <div className="text-green-600 dark:text-green-400 mb-2">
                <svg xmlns="http://www.w3.org/2000/svg" className="h-10 w-10 mx-auto" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-gray-900 dark:text-white mb-1">
                Thank you for your feedback!
              </p>
              {result.issueUrl && (
                <a
                  href={result.issueUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-indigo-500 hover:text-indigo-600 dark:text-indigo-400"
                >
                  View issue on GitHub
                </a>
              )}
              <div className="mt-4">
                <button
                  onClick={closeFeedback}
                  className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
                >
                  Close
                </button>
              </div>
            </div>
          ) : (
            <>
              <p className="text-xs text-gray-400 dark:text-gray-400">
                Report a bug, request a feature, or share your thoughts. Your feedback helps us improve Reli.
              </p>

              {/* Category */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Category
                </label>
                <div className="flex gap-2">
                  {CATEGORIES.map(c => (
                    <button
                      key={c.value}
                      onClick={() => setCategory(c.value)}
                      className={`flex-1 px-3 py-2 text-xs font-medium rounded-lg border transition-colors ${
                        category === c.value
                          ? 'border-indigo-500 bg-indigo-50 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300'
                          : 'border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800'
                      }`}
                    >
                      {c.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Message */}
              <div>
                <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">
                  Description
                </label>
                <textarea
                  value={message}
                  onChange={e => setMessage(e.target.value)}
                  placeholder={
                    category === 'bug'
                      ? 'Describe the bug: what happened and what you expected...'
                      : category === 'feature'
                        ? 'Describe the feature you\'d like to see...'
                        : 'Share your feedback...'
                  }
                  rows={5}
                  maxLength={5000}
                  className="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-400 dark:focus:ring-indigo-500 focus:border-indigo-400 dark:focus:border-indigo-500 resize-none"
                />
                <p className="text-[10px] text-gray-400 dark:text-gray-400 mt-1">
                  Browser and app info will be included automatically.
                </p>
              </div>

              {/* Screenshot */}
              <div>
                {screenshotBase64 ? (
                  <div className="relative inline-block">
                    <img
                      src={`data:image/jpeg;base64,${screenshotBase64}`}
                      alt="Screenshot preview"
                      className="max-h-32 rounded-lg border border-gray-200 dark:border-gray-700 object-contain"
                    />
                    <button
                      onClick={() => setScreenshotBase64(null)}
                      className="absolute -top-1.5 -right-1.5 w-5 h-5 bg-gray-700 text-white rounded-full text-xs flex items-center justify-center hover:bg-gray-600"
                      aria-label="Remove screenshot"
                    >
                      ×
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={handleCapture}
                    type="button"
                    className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-gray-600 dark:text-gray-400 border border-gray-200 dark:border-gray-700 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                  >
                    <svg xmlns="http://www.w3.org/2000/svg" className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V9z" />
                      <path strokeLinecap="round" strokeLinejoin="round" d="M15 13a3 3 0 11-6 0 3 3 0 016 0z" />
                    </svg>
                    Add Screenshot
                  </button>
                )}
              </div>

              {result?.error && (
                <p className="text-xs text-red-600 dark:text-red-400">{result.error}</p>
              )}

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-2">
                <button
                  onClick={closeFeedback}
                  className="px-4 py-2 text-sm text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSubmit}
                  disabled={!message.trim() || submitting}
                  className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed rounded-lg transition-colors"
                >
                  {submitting ? 'Submitting...' : 'Submit Feedback'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
