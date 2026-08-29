export interface StreamCallbacks {
  onStage: (stage: 'context' | 'reasoning' | 'response') => void
  onToken: (text: string) => void
  onComplete: (data: unknown) => void
  onError: (message: string) => void
}

/**
 * Reads an SSE stream from the chat endpoint and dispatches parsed events
 * via the provided callbacks.
 */
export async function readChatStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  callbacks: StreamCallbacks,
): Promise<void> {
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    // Keep the last potentially incomplete line in the buffer
    buffer = lines.pop() ?? ''

    let eventType = ''
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        eventType = line.slice(7).trim()
      } else if (line.startsWith('data: ') && eventType) {
        let data: Record<string, unknown>
        try {
          data = JSON.parse(line.slice(6))
        } catch {
          callbacks.onError(`Malformed JSON in ${eventType} event`)
          eventType = ''
          continue
        }

        if (eventType === 'stage') {
          if (data.status === 'started') {
            callbacks.onStage(data.stage as 'context' | 'reasoning' | 'response')
          }
        } else if (eventType === 'token') {
          callbacks.onToken(data.text as string)
        } else if (eventType === 'complete') {
          callbacks.onComplete(data)
        } else if (eventType === 'error') {
          callbacks.onError((data.message as string) || 'Pipeline error')
        }

        eventType = ''
      }
    }
  }
}
