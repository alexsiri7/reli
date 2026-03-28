import { useState } from 'react'
import { useStore } from '../store'

interface FABAction {
  label: string
  icon: string
  onClick: () => void
}

export function MobileFAB({ onOpenPalette }: { onOpenPalette: () => void }) {
  const [open, setOpen] = useState(false)

  const { sendMessage, setMobileView } = useStore(s => ({
    sendMessage: s.sendMessage,
    setMobileView: s.setMobileView,
  }))

  const actions: FABAction[] = [
    {
      label: 'New Task',
      icon: '📋',
      onClick: () => {
        setOpen(false)
        sendMessage('Add a new task: ')
        setMobileView('chat')
      },
    },
    {
      label: 'New Note',
      icon: '📝',
      onClick: () => {
        setOpen(false)
        sendMessage('Add a new note: ')
        setMobileView('chat')
      },
    },
    {
      label: 'New Idea',
      icon: '💡',
      onClick: () => {
        setOpen(false)
        sendMessage('Add a new idea: ')
        setMobileView('chat')
      },
    },
    {
      label: 'Search',
      icon: '🔍',
      onClick: () => {
        setOpen(false)
        onOpenPalette()
      },
    },
  ]

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          className="fixed inset-0 z-[40]"
          onClick={() => setOpen(false)}
        />
      )}

      <div className="md:hidden fixed bottom-20 right-4 z-[50] flex flex-col-reverse items-end gap-3">
        {/* Action items */}
        {open && actions.map((action, i) => (
          <div
            key={i}
            className="flex items-center gap-2 animate-fade-in-up"
            style={{ animationDelay: `${i * 40}ms` }}
          >
            <span className="bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 text-xs font-medium px-2.5 py-1 rounded-full shadow-md border border-gray-200 dark:border-gray-700 whitespace-nowrap">
              {action.label}
            </span>
            <button
              onClick={action.onClick}
              className="w-10 h-10 rounded-full bg-white dark:bg-gray-800 shadow-md border border-gray-200 dark:border-gray-700 flex items-center justify-center text-lg transition-transform active:scale-95"
              aria-label={action.label}
            >
              {action.icon}
            </button>
          </div>
        ))}

        {/* Main FAB */}
        <button
          onClick={() => setOpen(o => !o)}
          className={`w-14 h-14 rounded-full bg-indigo-600 dark:bg-indigo-500 text-white shadow-lg flex items-center justify-center transition-all active:scale-95 ${
            open ? 'rotate-45' : ''
          }`}
          aria-label={open ? 'Close quick actions' : 'Quick actions'}
          aria-expanded={open}
        >
          <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
          </svg>
        </button>
      </div>
    </>
  )
}
