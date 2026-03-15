import { useState, useCallback, useEffect, useRef } from 'react'

export const ttsSupported = typeof window !== 'undefined' && 'speechSynthesis' in window

export function useAvailableVoices() {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([])

  useEffect(() => {
    if (!ttsSupported) return

    const loadVoices = () => {
      setVoices(speechSynthesis.getVoices())
    }

    loadVoices()
    speechSynthesis.addEventListener('voiceschanged', loadVoices)
    return () => speechSynthesis.removeEventListener('voiceschanged', loadVoices)
  }, [])

  return voices
}

const TTS_VOICE_KEY = 'reli-tts-voice'

export function getStoredVoiceURI(): string | null {
  return localStorage.getItem(TTS_VOICE_KEY)
}

export function setStoredVoiceURI(uri: string | null) {
  if (uri) {
    localStorage.setItem(TTS_VOICE_KEY, uri)
  } else {
    localStorage.removeItem(TTS_VOICE_KEY)
  }
}

export function useTTS() {
  const [speakingId, setSpeakingId] = useState<string | null>(null)
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null)

  useEffect(() => {
    return () => {
      speechSynthesis.cancel()
    }
  }, [])

  const speak = useCallback((text: string, messageId: string) => {
    if (!ttsSupported) return

    // If already speaking this message, stop it
    if (speakingId === messageId) {
      speechSynthesis.cancel()
      setSpeakingId(null)
      return
    }

    // Cancel any current speech
    speechSynthesis.cancel()

    const utterance = new SpeechSynthesisUtterance(text)
    const storedURI = getStoredVoiceURI()
    if (storedURI) {
      const voice = speechSynthesis.getVoices().find(v => v.voiceURI === storedURI)
      if (voice) utterance.voice = voice
    }

    utterance.onend = () => setSpeakingId(null)
    utterance.onerror = () => setSpeakingId(null)

    utteranceRef.current = utterance
    setSpeakingId(messageId)
    speechSynthesis.speak(utterance)
  }, [speakingId])

  const stop = useCallback(() => {
    speechSynthesis.cancel()
    setSpeakingId(null)
  }, [])

  return { speakingId, speak, stop }
}
