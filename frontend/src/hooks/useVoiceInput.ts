import { useState, useCallback, useRef, useEffect } from 'react'

interface SpeechRecognitionEvent {
  results: { [index: number]: { [index: number]: { transcript: string }; isFinal: boolean }; length: number }
  resultIndex: number
}

interface SpeechRecognitionInstance extends EventTarget {
  continuous: boolean
  interimResults: boolean
  lang: string
  start(): void
  stop(): void
  abort(): void
  onresult: ((event: SpeechRecognitionEvent) => void) | null
  onerror: ((event: { error: string }) => void) | null
  onend: (() => void) | null
}

type SpeechRecognitionConstructor = new () => SpeechRecognitionInstance

function getSpeechRecognition(): SpeechRecognitionConstructor | null {
  const w = window as unknown as Record<string, unknown>
  return (w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null) as SpeechRecognitionConstructor | null
}

export const speechRecognitionSupported = !!getSpeechRecognition()

const SILENCE_TIMEOUT_MS = 3000

export function useVoiceInput(onTranscript: (text: string) => void) {
  const [listening, setListening] = useState(false)
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null)
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const transcriptRef = useRef<string>('')

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current !== null) {
      clearTimeout(silenceTimerRef.current)
      silenceTimerRef.current = null
    }
  }, [])

  const stopAndSubmit = useCallback(() => {
    clearSilenceTimer()
    const recognition = recognitionRef.current
    if (recognition) {
      recognition.stop()
    }
  }, [clearSilenceTimer])

  useEffect(() => {
    return () => {
      clearSilenceTimer()
      recognitionRef.current?.abort()
    }
  }, [clearSilenceTimer])

  const toggleListening = useCallback(() => {
    if (listening) {
      stopAndSubmit()
      return
    }

    const SpeechRecognition = getSpeechRecognition()
    if (!SpeechRecognition) return

    transcriptRef.current = ''
    const recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = navigator.language || 'en-US'

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      // Reset silence timer on every result (interim or final)
      clearSilenceTimer()
      silenceTimerRef.current = setTimeout(stopAndSubmit, SILENCE_TIMEOUT_MS)

      // Build full transcript from all results
      let finalTranscript = ''
      for (let i = 0; i < event.results.length; i++) {
        const result = event.results[i]
        if (result?.isFinal) {
          finalTranscript += result[0]?.transcript ?? ''
        }
      }
      transcriptRef.current = finalTranscript
    }

    recognition.onerror = () => {
      clearSilenceTimer()
      // Submit any accumulated transcript before cleaning up
      const text = transcriptRef.current.trim()
      if (text) {
        onTranscript(text)
        transcriptRef.current = ''
      }
      setListening(false)
      recognitionRef.current = null
    }

    recognition.onend = () => {
      clearSilenceTimer()
      const text = transcriptRef.current.trim()
      if (text) {
        onTranscript(text)
        transcriptRef.current = ''
      }
      setListening(false)
      recognitionRef.current = null
    }

    recognitionRef.current = recognition
    recognition.start()
    setListening(true)

    // Start initial silence timer — if user doesn't speak at all
    silenceTimerRef.current = setTimeout(stopAndSubmit, SILENCE_TIMEOUT_MS)
  }, [listening, onTranscript, clearSilenceTimer, stopAndSubmit])

  return { listening, toggleListening }
}
