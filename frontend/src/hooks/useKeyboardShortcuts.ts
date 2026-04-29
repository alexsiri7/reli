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
      const store = useStore.getState()

      // Cmd+K — command palette (always, even in inputs)
      if (mod && e.key === 'k') {
        e.preventDefault()
        if (store.commandPaletteOpen) {
          store.closeCommandPalette()
        } else {
          store.openCommandPalette()
        }
        return
      }

      // Esc — close open panels
      if (e.key === 'Escape') {
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

      // Command-based shortcuts
      if (mod) {
        switch (e.key) {
          case 'n':
            e.preventDefault()
            store.setMobileView('chat')
            setTimeout(() => document.getElementById('chat-input')?.focus(), 50)
            break
          case 'b':
            e.preventDefault()
            store.toggleSidebar()
            break
          case '.':
            e.preventDefault()
            store.setMobileView(store.mobileView === 'things' ? 'chat' : 'things')
            break
        }
      } else if (e.key === '/') {
        // / — focus chat input
        e.preventDefault()
        store.setMobileView('chat')
        setTimeout(() => document.getElementById('chat-input')?.focus(), 50)
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [])
}
