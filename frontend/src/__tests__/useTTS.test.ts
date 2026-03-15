import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'

// vi.hoisted runs before imports are resolved, so speechSynthesis
// will exist when useTTS.ts evaluates ttsSupported
const { mockSpeak, mockCancel, mockGetVoices, mockAddEventListener, mockRemoveEventListener, getLastUtterance, resetLastUtterance } = vi.hoisted(() => {
  const mockSpeak = vi.fn()
  const mockCancel = vi.fn()
  const mockGetVoices = vi.fn(() => [] as { voiceURI: string; name: string }[])
  const mockAddEventListener = vi.fn()
  const mockRemoveEventListener = vi.fn()

  let _lastUtterance: { text: string; voice: unknown; onend: (() => void) | null; onerror: (() => void) | null } | null = null

  Object.defineProperty(globalThis, 'speechSynthesis', {
    value: {
      speak: mockSpeak,
      cancel: mockCancel,
      getVoices: mockGetVoices,
      addEventListener: mockAddEventListener,
      removeEventListener: mockRemoveEventListener,
    },
    writable: true,
    configurable: true,
  })

  Object.defineProperty(globalThis, 'SpeechSynthesisUtterance', {
    value: class MockUtterance {
      text: string
      voice: unknown = null
      onend: (() => void) | null = null
      onerror: (() => void) | null = null
      constructor(text: string) {
        this.text = text
        _lastUtterance = this
      }
    },
    writable: true,
    configurable: true,
  })

  return {
    mockSpeak,
    mockCancel,
    mockGetVoices,
    mockAddEventListener,
    mockRemoveEventListener,
    getLastUtterance: () => _lastUtterance,
    resetLastUtterance: () => { _lastUtterance = null },
  }
})

import { getStoredVoiceURI, setStoredVoiceURI, useTTS, useAvailableVoices } from '../hooks/useTTS'

beforeEach(() => {
  mockSpeak.mockClear()
  mockCancel.mockClear()
  mockGetVoices.mockReset().mockReturnValue([])
  mockAddEventListener.mockClear()
  mockRemoveEventListener.mockClear()
  resetLastUtterance()
  localStorage.clear()
})

describe('getStoredVoiceURI', () => {
  it('returns null when no voice is stored', () => {
    expect(getStoredVoiceURI()).toBeNull()
  })

  it('returns stored voice URI', () => {
    localStorage.setItem('reli-tts-voice', 'some-voice-uri')
    expect(getStoredVoiceURI()).toBe('some-voice-uri')
  })
})

describe('setStoredVoiceURI', () => {
  it('stores voice URI in localStorage', () => {
    setStoredVoiceURI('test-uri')
    expect(localStorage.getItem('reli-tts-voice')).toBe('test-uri')
  })

  it('removes voice URI when null', () => {
    localStorage.setItem('reli-tts-voice', 'old')
    setStoredVoiceURI(null)
    expect(localStorage.getItem('reli-tts-voice')).toBeNull()
  })
})

describe('useAvailableVoices', () => {
  it('returns empty array initially when no voices', () => {
    const { result } = renderHook(() => useAvailableVoices())
    expect(result.current).toEqual([])
  })

  it('loads voices from speechSynthesis', () => {
    const mockVoices = [{ voiceURI: 'en-US', name: 'English' }]
    mockGetVoices.mockReturnValue(mockVoices)
    const { result } = renderHook(() => useAvailableVoices())
    expect(result.current).toEqual(mockVoices)
  })
})

describe('useTTS', () => {
  it('starts with no speaking message', () => {
    const { result } = renderHook(() => useTTS())
    expect(result.current.speakingId).toBeNull()
  })

  it('speaks a message and sets speakingId', () => {
    const { result } = renderHook(() => useTTS())

    act(() => {
      result.current.speak('Hello world', 'msg-1')
    })

    expect(mockCancel).toHaveBeenCalled()
    expect(mockSpeak).toHaveBeenCalled()
    expect(result.current.speakingId).toBe('msg-1')
  })

  it('stops speaking when same message is toggled', () => {
    const { result } = renderHook(() => useTTS())

    act(() => {
      result.current.speak('Hello', 'msg-1')
    })
    expect(result.current.speakingId).toBe('msg-1')

    act(() => {
      result.current.speak('Hello', 'msg-1')
    })
    expect(result.current.speakingId).toBeNull()
    expect(mockCancel).toHaveBeenCalled()
  })

  it('clears speakingId on utterance end', () => {
    const { result } = renderHook(() => useTTS())

    act(() => {
      result.current.speak('Hello', 'msg-1')
    })
    expect(result.current.speakingId).toBe('msg-1')

    act(() => {
      getLastUtterance()?.onend?.()
    })
    expect(result.current.speakingId).toBeNull()
  })

  it('clears speakingId on utterance error', () => {
    const { result } = renderHook(() => useTTS())

    act(() => {
      result.current.speak('Hello', 'msg-1')
    })

    act(() => {
      getLastUtterance()?.onerror?.()
    })
    expect(result.current.speakingId).toBeNull()
  })

  it('uses stored voice when available', () => {
    const mockVoice = { voiceURI: 'stored-voice', name: 'Stored' }
    mockGetVoices.mockReturnValue([mockVoice])
    localStorage.setItem('reli-tts-voice', 'stored-voice')

    const { result } = renderHook(() => useTTS())

    act(() => {
      result.current.speak('Hello', 'msg-1')
    })

    expect(getLastUtterance()?.voice).toBe(mockVoice)
  })

  it('stop cancels speech and clears speakingId', () => {
    const { result } = renderHook(() => useTTS())

    act(() => {
      result.current.speak('Hello', 'msg-1')
    })

    act(() => {
      result.current.stop()
    })

    expect(mockCancel).toHaveBeenCalled()
    expect(result.current.speakingId).toBeNull()
  })

  it('cancels speech on unmount', () => {
    const { unmount } = renderHook(() => useTTS())
    mockCancel.mockClear()
    unmount()
    expect(mockCancel).toHaveBeenCalled()
  })
})
