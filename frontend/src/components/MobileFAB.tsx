import { useState, useRef, useEffect } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'

interface QuickAddOption {
  label: string
  typeHint: string
  icon: string
  placeholder: string
}

const QUICK_ADD_OPTIONS: QuickAddOption[] = [
  { label: 'Add task', typeHint: 'task', icon: '✓', placeholder: 'What needs to be done?' },
  { label: 'Quick note', typeHint: 'note', icon: '📝', placeholder: 'What do you want to note?' },
  { label: 'Capture idea', typeHint: 'idea', icon: '💡', placeholder: 'What\'s the idea?' },
  { label: 'Remember person', typeHint: 'person', icon: '👤', placeholder: 'Who do you want to remember?' },
]

export function MobileFAB() {
  const { createThing } = useStore(
    useShallow(s => ({ createThing: s.createThing }))
  )

  const [menuOpen, setMenuOpen] = useState(false)
  const [activeOption, setActiveOption] = useState<QuickAddOption | null>(null)
  const [title, setTitle] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (activeOption && inputRef.current) {
      inputRef.current.focus()
    }
  }, [activeOption])

  const handleFABClick = () => {
    setMenuOpen(prev => !prev)
    setActiveOption(null)
    setTitle('')
  }

  const handleOptionClick = (option: QuickAddOption) => {
    setActiveOption(option)
    setMenuOpen(false)
    setTitle('')
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!title.trim() || !activeOption || submitting) return
    setSubmitting(true)
    await createThing({ title: title.trim(), type_hint: activeOption.typeHint })
    setSubmitting(false)
    setActiveOption(null)
    setTitle('')
  }

  const handleClose = () => {
    setMenuOpen(false)
    setActiveOption(null)
    setTitle('')
  }

  return (
    <>
      {/* Backdrop to close menu/form */}
      {(menuOpen || activeOption) && (
        <div
          className="fixed inset-0 z-30"
          onClick={handleClose}
        />
      )}

      {/* Quick-add form */}
      {activeOption && (
        <div className="fixed bottom-20 left-4 right-4 z-40 bg-white dark:bg-gray-900 rounded-2xl shadow-xl border border-gray-200 dark:border-gray-700 p-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">{activeOption.icon}</span>
            <span className="text-sm font-medium text-gray-700 dark:text-gray-300">{activeOption.label}</span>
          </div>
          <form onSubmit={handleSubmit}>
            <input
              ref={inputRef}
              type="text"
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder={activeOption.placeholder}
              className="w-full px-3 py-2 rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <div className="flex gap-2 mt-3">
              <button
                type="button"
                onClick={handleClose}
                className="flex-1 py-2 rounded-lg text-sm font-medium text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={!title.trim() || submitting}
                className="flex-1 py-2 rounded-lg text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {submitting ? 'Adding…' : 'Add'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* FAB menu */}
      {menuOpen && (
        <div className="fixed bottom-20 right-4 z-40 flex flex-col-reverse gap-2">
          {QUICK_ADD_OPTIONS.map(option => (
            <button
              key={option.typeHint}
              onClick={() => handleOptionClick(option)}
              className="flex items-center gap-3 self-end bg-white dark:bg-gray-900 rounded-full shadow-lg border border-gray-200 dark:border-gray-700 pl-4 pr-5 py-2.5 text-sm font-medium text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
            >
              <span>{option.icon}</span>
              {option.label}
            </button>
          ))}
        </div>
      )}

      {/* FAB button */}
      <button
        onClick={handleFABClick}
        aria-label="Create new thing"
        className={`fixed bottom-20 right-4 z-40 w-14 h-14 rounded-full shadow-lg flex items-center justify-center transition-all duration-200 ${
          menuOpen
            ? 'bg-gray-600 dark:bg-gray-500 rotate-45'
            : 'bg-indigo-600 hover:bg-indigo-700'
        }`}
      >
        <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
      </button>
    </>
  )
}
