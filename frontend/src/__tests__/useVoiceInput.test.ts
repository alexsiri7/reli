import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useVoiceInput } from '../hooks/useVoiceInput'

interface MockRecognitionInstance {
  continuous: boolean
  interimResults: boolean
  lang: string
  start: ReturnType<typeof vi.fn>
  stop: ReturnType<typeof vi.fn>
  abort: ReturnType<typeof vi.fn>
  onresult: ((event: { results: Record<number, { isFinal: boolean; 0: { transcript: string } }>; resultIndex: number; length?: number }) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

let mockRecognitionInstance: MockRecognitionInstance

class MockSpeechRecognition {
  continuous = false
  interimResults = false
  lang = ''
  start = vi.fn()
  stop = vi.fn()
  abort = vi.fn()
  onresult: MockRecognitionInstance['onresult'] = null
  onerror: MockRecognitionInstance['onerror'] = null
  onend: MockRecognitionInstance['onend'] = null

  constructor() {
    mockRecognitionInstance = this
  }
}

beforeEach(() => {
  ;(window as Record<string, unknown>).SpeechRecognition = MockSpeechRecognition
  vi.useFakeTimers()
})

afterEach(() => {
  delete (window as Record<string, unknown>).SpeechRecognition
  vi.useRealTimers()
})

describe('useVoiceInput', () => {
  it('starts with listening=false', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))
    expect(result.current.listening).toBe(false)
  })

  it('starts listening on toggle', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    expect(result.current.listening).toBe(true)
    expect(mockRecognitionInstance.continuous).toBe(true)
    expect(mockRecognitionInstance.interimResults).toBe(true)
    expect(mockRecognitionInstance.start).toHaveBeenCalled()
  })

  it('stops listening on second toggle', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })
    expect(result.current.listening).toBe(true)

    act(() => {
      result.current.toggleListening()
    })
    expect(mockRecognitionInstance.stop).toHaveBeenCalled()
  })

  it('submits transcript on recognition end', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    // Simulate result event with final transcript
    act(() => {
      mockRecognitionInstance.onresult?.({
        results: {
          0: { isFinal: true, 0: { transcript: 'hello world' } },
          length: 1,
        } as Record<number, { isFinal: boolean; 0: { transcript: string } }>,
        resultIndex: 0,
      })
    })

    // Simulate recognition end
    act(() => {
      mockRecognitionInstance.onend?.()
    })

    expect(onTranscript).toHaveBeenCalledWith('hello world')
    expect(result.current.listening).toBe(false)
  })

  it('submits transcript on error', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    // Simulate result then error
    act(() => {
      mockRecognitionInstance.onresult?.({
        results: {
          0: { isFinal: true, 0: { transcript: 'partial text' } },
          length: 1,
        } as Record<number, { isFinal: boolean; 0: { transcript: string } }>,
        resultIndex: 0,
      })
    })

    act(() => {
      mockRecognitionInstance.onerror?.({ error: 'aborted' })
    })

    expect(onTranscript).toHaveBeenCalledWith('partial text')
    expect(result.current.listening).toBe(false)
  })

  it('does not submit empty transcript on end', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    // End without any results
    act(() => {
      mockRecognitionInstance.onend?.()
    })

    expect(onTranscript).not.toHaveBeenCalled()
    expect(result.current.listening).toBe(false)
  })

  it('auto-stops after silence timeout', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    // Simulate a result
    act(() => {
      mockRecognitionInstance.onresult?.({
        results: {
          0: { isFinal: true, 0: { transcript: 'test' } },
          length: 1,
        } as Record<number, { isFinal: boolean; 0: { transcript: string } }>,
        resultIndex: 0,
      })
    })

    // Advance past silence timeout (3000ms)
    act(() => {
      vi.advanceTimersByTime(3000)
    })

    expect(mockRecognitionInstance.stop).toHaveBeenCalled()
  })

  it('resets silence timer on each result', () => {
    const onTranscript = vi.fn()
    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    // First result
    act(() => {
      mockRecognitionInstance.onresult?.({
        results: {
          0: { isFinal: true, 0: { transcript: 'first ' } },
          length: 1,
        } as Record<number, { isFinal: boolean; 0: { transcript: string } }>,
        resultIndex: 0,
      })
    })

    // Advance 2s (not enough for timeout)
    act(() => {
      vi.advanceTimersByTime(2000)
    })

    // Second result resets the timer
    act(() => {
      mockRecognitionInstance.onresult?.({
        results: {
          0: { isFinal: true, 0: { transcript: 'first ' } },
          1: { isFinal: true, 0: { transcript: 'second' } },
          length: 2,
        } as Record<number, { isFinal: boolean; 0: { transcript: string } }>,
        resultIndex: 1,
      })
    })

    // Advance another 2s (still not enough since timer was reset)
    act(() => {
      vi.advanceTimersByTime(2000)
    })

    // Should NOT have stopped yet
    expect(mockRecognitionInstance.stop).not.toHaveBeenCalled()

    // Advance to complete the timeout
    act(() => {
      vi.advanceTimersByTime(1000)
    })

    expect(mockRecognitionInstance.stop).toHaveBeenCalled()
  })

  it('aborts recognition on unmount', () => {
    const onTranscript = vi.fn()
    const { result, unmount } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    unmount()
    expect(mockRecognitionInstance.abort).toHaveBeenCalled()
  })

  it('sets language from navigator.language', () => {
    const onTranscript = vi.fn()
    Object.defineProperty(navigator, 'language', { value: 'fr-FR', configurable: true })

    const { result } = renderHook(() => useVoiceInput(onTranscript))

    act(() => {
      result.current.toggleListening()
    })

    expect(mockRecognitionInstance.lang).toBe('fr-FR')

    Object.defineProperty(navigator, 'language', { value: 'en-US', configurable: true })
  })
})
