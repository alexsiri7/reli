import { useEffect } from 'react'
import { useStore } from '../store'

/**
 * Global keyboard shortcuts.
 *
 * | Shortcut         | Action                         |
 * |------------------|-------------------------------|
 * | Cmd/Ctrl+K       | Open command palette          |
 * | Cmd/Ctrl+N       | New Thing (focus chat)        |
 * | Cmd/Ctrl+B       | Toggle sidebar                |
 * | Cmd/Ctrl+.       | Toggle briefing / chat view   |
 * | /                | Focus chat input              |
 * | Esc              | Close open panel / palette    |
 */
export function useKeyboardShortcuts() {
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      const mod = e.metaKey || e.ctrlKey
      const tag = (e.target as HTMLElement)?.tagName ?? ''
      const isInInput = tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement)?.isContentEditable

      // Cmd+K — command palette (always, even in inputs)
      if (mod && e.key === 'k') {
        e.preventDefault()
        const store = useStore.getState()
        if (store.commandPaletteOpen) {
          store.closeCommandPalette()
        } else {
          store.openCommandPalette()
        }
        return
      }

      // Esc — close palette / settings / detail panel
      if (e.key === 'Escape') {
        const store = useStore.getState()
        if (store.commandPaletteOpen) {
          store.closeCommandPalette()
          return
        }
        if (store.settingsOpen) {
          store.closeSettings()
          return
        }
        if (store.feedbackOpen) {
          store.closeFeedback()
          return
        }
        return
      }

      // Shortcuts below should not fire when typing in an input
      if (isInInput) return

      // Cmd+N — new thing (focus chat with starter text)
      if (mod && e.key === 'n') {
        e.preventDefault()
        const store = useStore.getState()
        store.setMobileView('chat')
        setTimeout(() => document.getElementById('chat-input')?.focus(), 50)
        return
      }

      // Cmd+B — toggle sidebar
      if (mod && e.key === 'b') {
        e.preventDefault()
        useStore.getState().toggleSidebar()
        return
      }

      // Cmd+. — toggle between list and chat on mobile / toggle main view
      if (mod && e.key === '.') {
        e.preventDefault()
        const store = useStore.getState()
        store.setMobileView(store.mobileView === 'things' ? 'chat' : 'things')
        return
      }

      // / — focus chat input
      if (e.key === '/') {
        e.preventDefault()
        const store = useStore.getState()
        store.setMobileView('chat')
        setTimeout(() => document.getElementById('chat-input')?.focus(), 50)
        return
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])
}
