import { useStore } from '../store'
import { useShallow } from 'zustand/react/shallow'

export interface DisclosureLevel {
  thingsCount: number
  showOnboarding: boolean        // 0 things: guided onboarding
  showBriefing: boolean          // 5+ things: briefing is meaningful
  showConnectionDiscovery: boolean  // 10+ things: relationship discovery
  showFocusBoard: boolean        // 20+ things: priority board useful
  showCommandPaletteHint: boolean   // 50+ things: command palette essential
  showGraphView: boolean         // 100+ things: graph view, advanced features
}

export function useProgressiveDisclosure(): DisclosureLevel {
  const things = useStore(useShallow(s => s.things))
  const count = things.length

  return {
    thingsCount: count,
    showOnboarding: count === 0,
    showBriefing: count >= 5,
    showConnectionDiscovery: count >= 10,
    showFocusBoard: count >= 20,
    showCommandPaletteHint: count >= 50,
    showGraphView: count >= 100,
  }
}
