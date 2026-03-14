import { useCallback, useEffect, useRef, useState } from 'react'
import { useShallow } from 'zustand/react/shallow'
import { useStore } from '../store'

function MessageBubble({ role, content, streaming }: {
  role: 'user' | 'assistant'
  content: string
  streaming?: boolean
}) {
  const isUser = role === 'user'
  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-indigo-600 text-white text-xs flex items-center justify-center shrink-0 mr-2 mt-1 font-bold">
          R
        </div>
      )}
      <div
        className={`max-w-[75%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isUser
            ? 'bg-indigo-600 text-white rounded-br-sm'
            : 'bg-white dark:bg-gray-800 text-gray-800 dark:text-gray-100 border border-gray-200 dark:border-gray-700 rounded-bl-sm'
        }`}
      >
        {content}
        {streaming && (
          <span className="inline-block w-1.5 h-4 bg-current opacity-75 ml-0.5 animate-pulse align-middle" />
        )}
      </div>
    </div>
  )
}

export function ChatPanel() {
  const { messages, chatLoading, historyLoading, hasMoreHistory, sendMessage, fetchOlderMessages } = useStore(
    useShallow(s => ({
      messages: s.messages,
      chatLoading: s.chatLoading,
      historyLoading: s.historyLoading,
      hasMoreHistory: s.hasMoreHistory,
      sendMessage: s.sendMessage,
      fetchOlderMessages: s.fetchOlderMessages,
    }))
  )
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const prevScrollHeightRef = useRef<number>(0)
  const isLoadingOlderRef = useRef(false)

  // Auto-scroll to bottom on new messages (but not when loading older ones)
  useEffect(() => {
    if (isLoadingOlderRef.current) {
      // Preserve scroll position after prepending older messages
      const container = scrollContainerRef.current
      if (container) {
        const newScrollHeight = container.scrollHeight
        container.scrollTop = newScrollHeight - prevScrollHeightRef.current
      }
      isLoadingOlderRef.current = false
    } else {
      bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  const handleScroll = useCallback(() => {
    const container = scrollContainerRef.current
    if (!container || historyLoading || !hasMoreHistory) return

    if (container.scrollTop < 100) {
      isLoadingOlderRef.current = true
      prevScrollHeightRef.current = container.scrollHeight
      fetchOlderMessages()
    }
  }, [historyLoading, hasMoreHistory, fetchOlderMessages])

  const submit = async () => {
    const text = input.trim()
    if (!text || chatLoading) return
    setInput('')
    await sendMessage(text)
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      submit()
    }
  }

  return (
    <div className="flex-1 flex flex-col bg-gray-50 dark:bg-gray-900 min-w-0">
      {/* Title bar */}
      <div className="px-5 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-950 shrink-0">
        <h2 className="text-sm font-semibold text-gray-700 dark:text-gray-200">Chat</h2>
        <p className="text-xs text-gray-400 dark:text-gray-500">Talk to Reli — create, update, and query your Things</p>
      </div>

      {/* Messages */}
      <div
        ref={scrollContainerRef}
        className="flex-1 overflow-y-auto px-5 py-4"
        onScroll={handleScroll}
      >
        {historyLoading && hasMoreHistory && (
          <div className="flex justify-center py-2">
            <span className="w-4 h-4 border-2 border-gray-300 border-t-indigo-600 rounded-full animate-spin" />
          </div>
        )}
        {messages.length === 0 && !historyLoading && (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="text-5xl mb-4">✨</div>
            <h3 className="text-base font-semibold text-gray-700 dark:text-gray-200">What's on your mind?</h3>
            <p className="text-sm text-gray-400 dark:text-gray-500 mt-1 max-w-xs">
              Try: "Remind me to check the server logs tomorrow" or "I had an idea about the new API design"
            </p>
          </div>
        )}
        {messages.map(msg => (
          <MessageBubble
            key={msg.id}
            role={msg.role}
            content={msg.content}
            streaming={msg.streaming}
          />
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="px-4 pb-4 pt-2 bg-white dark:bg-gray-950 border-t border-gray-200 dark:border-gray-800 shrink-0">
        <div className="flex items-end gap-2 bg-gray-100 dark:bg-gray-800 rounded-2xl px-3 py-2">
          <textarea
            ref={inputRef}
            rows={1}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Message Reli…"
            className="flex-1 bg-transparent resize-none outline-none text-sm text-gray-900 dark:text-gray-100 placeholder-gray-400 dark:placeholder-gray-500 max-h-32 py-1 leading-relaxed"
            style={{ height: 'auto' }}
            onInput={e => {
              const t = e.currentTarget
              t.style.height = 'auto'
              t.style.height = `${t.scrollHeight}px`
            }}
          />
          <button
            onClick={submit}
            disabled={!input.trim() || chatLoading}
            className="shrink-0 w-8 h-8 rounded-xl bg-indigo-600 text-white flex items-center justify-center disabled:opacity-40 disabled:cursor-not-allowed hover:bg-indigo-700 transition-colors"
            title="Send (Enter)"
          >
            {chatLoading ? (
              <span className="w-3.5 h-3.5 border-2 border-white/40 border-t-white rounded-full animate-spin" />
            ) : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 10.5 12 3m0 0 7.5 7.5M12 3v18" />
              </svg>
            )}
          </button>
        </div>
        <p className="text-xs text-gray-400 dark:text-gray-600 text-center mt-1.5">
          Enter to send · Shift+Enter for new line
        </p>
      </div>
    </div>
  )
}
