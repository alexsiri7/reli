import { useEffect } from 'react'
import { useStore } from '../store'

/**
 * Returns true if the event has Cmd (Mac) or Ctrl (Win/Linux) held.
 */
function hasModifier(e: KeyboardEvent): boolean {
  return e.metaKey || e.ctrlKey
}

/**
 * Returns true if focus is inside a text input where we should NOT steal keystrokes.
 */
function inTextInput(e: KeyboardEvent): boolean {
  const tag = (e.target as HTMLElement)?.tagName
  const editable = (e.target as HTMLElement)?.isContentEditable
  return tag === 'INPUT' || tag === 'TEXTAREA' || editable
}

/**
 * Registers global keyboard shortcuts for the app.
 * Must be called once at the top level (App component).
 *
 * Shortcuts (Cmd = ⌘ on Mac, Ctrl on Win/Linux):
 *   Cmd+K  — Open command palette
 *   Cmd+N  — Quick-add new Thing
 *   Cmd+B  — Toggle sidebar
 *   Cmd+.  — Toggle briefing / chat mode
 *   /      — Focus chat input (when not in a text field)
 *   Esc    — Close topmost open overlay
 */
export function useKeyboardShortcuts() {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const state = useStore.getState()

      // Esc — close topmost overlay (checked first, always active)
      if (e.key === 'Escape') {
        if (state.commandPaletteOpen) {
          e.preventDefault()
          state.closeCommandPalette()
          return
        }
        if (state.quickAddOpen) {
          e.preventDefault()
          state.closeQuickAdd()
          return
        }
        if (state.settingsOpen) {
          e.preventDefault()
          state.closeSettings()
          return
        }
        if (state.detailThingId) {
          e.preventDefault()
          state.closeThingDetail()
          return
        }
        return
      }

      // Cmd+K — command palette
      if (hasModifier(e) && e.key === 'k') {
        e.preventDefault()
        if (state.commandPaletteOpen) {
          state.closeCommandPalette()
        } else {
          state.openCommandPalette()
        }
        return
      }

      // Cmd+N — quick add
      if (hasModifier(e) && e.key === 'n') {
        e.preventDefault()
        state.openQuickAdd()
        return
      }

      // Cmd+B — toggle sidebar
      if (hasModifier(e) && e.key === 'b') {
        e.preventDefault()
        state.setSidebarOpen(!state.sidebarOpen)
        return
      }

      // Cmd+. — toggle briefing / chat mode
      if (hasModifier(e) && e.key === '.') {
        e.preventDefault()
        state.setChatMode(state.chatMode === 'normal' ? 'planning' : 'normal')
        return
      }

      // / — focus chat input (only when not already in a text field)
      if (e.key === '/' && !inTextInput(e)) {
        e.preventDefault()
        state.focusChatInput()
        return
      }
    }

    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [])
}
