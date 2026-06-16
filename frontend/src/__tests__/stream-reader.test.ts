import { describe, it, expect, vi } from 'vitest'
import { readChatStream, type StreamCallbacks } from '../chat/stream-reader'

/** Build a ReadableStreamDefaultReader from string chunks. */
function fakeReader(
  chunks: string[],
): ReadableStreamDefaultReader<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return {
    read: async () => {
      if (i < chunks.length) {
        return { done: false, value: encoder.encode(chunks[i++]) }
      }
      return { done: true, value: undefined }
    },
    cancel: async () => {},
    releaseLock: () => {},
    closed: Promise.resolve(undefined),
  } as unknown as ReadableStreamDefaultReader<Uint8Array>
}

function makeCallbacks() {
  return {
    onStage: vi.fn(),
    onToken: vi.fn(),
    onComplete: vi.fn(),
    onError: vi.fn(),
  } satisfies StreamCallbacks
}

describe('readChatStream', () => {
  it('dispatches stage, token, and complete events correctly', async () => {
    const cb = makeCallbacks()
    const reader = fakeReader([
      'event: stage\ndata: {"stage":"context","status":"started"}\n\n',
      'event: token\ndata: {"text":"Hello"}\n\n',
      'event: complete\ndata: {"result":"ok"}\n\n',
    ])

    await readChatStream(reader, cb)

    expect(cb.onStage).toHaveBeenCalledWith('context')
    expect(cb.onToken).toHaveBeenCalledWith('Hello')
    expect(cb.onComplete).toHaveBeenCalledWith({ result: 'ok' })
    expect(cb.onError).not.toHaveBeenCalled()
  })

  it('survives malformed JSON and continues to next event', async () => {
    const cb = makeCallbacks()
    const reader = fakeReader([
      'event: stage\ndata: NOT_JSON\n\nevent: complete\ndata: {"done":true}\n\n',
    ])

    await readChatStream(reader, cb)

    expect(cb.onError).toHaveBeenCalledWith(
      expect.stringContaining('Malformed JSON'),
    )
    expect(cb.onComplete).toHaveBeenCalledWith({ done: true })
  })

  it('calls onError when an error event is received', async () => {
    const cb = makeCallbacks()
    const reader = fakeReader([
      'event: error\ndata: {"message":"Pipeline error occurred"}\n\n',
    ])

    await readChatStream(reader, cb)

    expect(cb.onError).toHaveBeenCalledWith('Pipeline error occurred')
  })
})
