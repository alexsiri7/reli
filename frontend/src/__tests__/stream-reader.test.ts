import { describe, it, expect, vi } from 'vitest'
import { readChatStream, type StreamCallbacks } from '../chat/stream-reader'

function makeReader(chunks: string[]): ReadableStreamDefaultReader<Uint8Array> {
  const encoder = new TextEncoder()
  let i = 0
  return {
    read: vi.fn().mockImplementation(async () => {
      if (i >= chunks.length) return { done: true, value: undefined }
      return { done: false, value: encoder.encode(chunks[i++]) }
    }),
    cancel: vi.fn(),
    closed: Promise.resolve(undefined),
    releaseLock: vi.fn(),
  } as unknown as ReadableStreamDefaultReader<Uint8Array>
}

function makeCallbacks(): StreamCallbacks & { calls: Record<string, unknown[]> } {
  const calls: Record<string, unknown[]> = { stage: [], token: [], complete: [], error: [] }
  return {
    calls,
    onStage: (s) => { calls.stage.push(s) },
    onToken: (t) => { calls.token.push(t) },
    onComplete: (d) => { calls.complete.push(d) },
    onError: (m) => { calls.error.push(m) },
  }
}

describe('readChatStream', () => {
  it('dispatches stage, token, and complete events', async () => {
    const reader = makeReader([
      'event: stage\ndata: {"stage":"context","status":"started"}\n\n',
      'event: token\ndata: {"text":"Hello"}\n\n',
      'event: complete\ndata: {"reply":"Hello world"}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.stage).toEqual(['context'])
    expect(cb.calls.token).toEqual(['Hello'])
    expect(cb.calls.complete).toEqual([{ reply: 'Hello world' }])
  })

  it('handles chunked data split across reads', async () => {
    // Split mid-line so buffer reassembles the complete event+data in one iteration
    const reader = makeReader([
      'event: tok',
      'en\ndata: {"text":"hi"}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.token).toEqual(['hi'])
  })

  it('dispatches error events via onError callback', async () => {
    const reader = makeReader([
      'event: error\ndata: {"message":"Pipeline error"}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.error).toEqual(['Pipeline error'])
  })

  it('uses default message when error event has no message field', async () => {
    const reader = makeReader([
      'event: error\ndata: {}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.error).toEqual(['Pipeline error'])
  })

  it('ignores stage events with status != started', async () => {
    const reader = makeReader([
      'event: stage\ndata: {"stage":"context","status":"complete"}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.stage).toEqual([])
  })

  it('handles malformed JSON gracefully', async () => {
    const reader = makeReader([
      'event: token\ndata: {invalid json\n\nevent: token\ndata: {"text":"after"}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.error).toEqual(['Malformed SSE data for event "token"'])
    expect(cb.calls.token).toEqual(['after'])
  })

  it('handles multiple events in a single chunk', async () => {
    const reader = makeReader([
      'event: token\ndata: {"text":"a"}\n\nevent: token\ndata: {"text":"b"}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.token).toEqual(['a', 'b'])
  })

  it('ignores data lines without a preceding event type', async () => {
    const reader = makeReader([
      'data: {"text":"orphan"}\n\nevent: token\ndata: {"text":"valid"}\n\n',
    ])
    const cb = makeCallbacks()

    await readChatStream(reader, cb)

    expect(cb.calls.token).toEqual(['valid'])
  })
})
