import { useEffect } from 'react'
import { useStore } from '../store'

/**
 * Global keyboard shortcuts for Reli.
 * Shortcuts fire only when no text input is focused.
 *
 * Cmd/Ctrl+K  - Open command palette (handled by caller via onOpenPalette)
 * ?           - Open command palette
 * s           - Focus sidebar search
 * Escape      - Close detail panel
 */
export function useKeyboardShortcuts({ onOpenPalette }: { onOpenPalette: () => void }) {
  const { closeThingDetail, openSettings } = useStore(s => ({
    closeThingDetail: s.closeThingDetail,
    openSettings: s.openSettings,
  }))

  useEffect(() => {
    function isInputFocused() {
      const el = document.activeElement
      if (!el) return false
      const tag = el.tagName.toLowerCase()
      return tag === 'input' || tag === 'textarea' || (el as HTMLElement).isContentEditable
    }

    function handler(e: KeyboardEvent) {
      // Cmd/Ctrl+K — always open palette
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        onOpenPalette()
        return
      }

      // Remaining shortcuts: skip when typing
      if (isInputFocused()) return

      switch (e.key) {
        case '?':
          e.preventDefault()
          onOpenPalette()
          break
        case 'Escape':
          closeThingDetail()
          break
        case ',':
          if (e.metaKey || e.ctrlKey) {
            e.preventDefault()
            openSettings()
          }
          break
      }
    }

    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [onOpenPalette, closeThingDetail, openSettings])
}
