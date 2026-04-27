import { useCallback, useEffect, useRef, useState } from 'react'


type Tool = 'redact' | 'highlight' | 'arrow' | 'text'

type Op =
  | { kind: 'redact'; x: number; y: number; w: number; h: number }
  | { kind: 'highlight'; x: number; y: number; w: number; h: number }
  | { kind: 'arrow'; x1: number; y1: number; x2: number; y2: number }
  | { kind: 'text'; x: number; y: number; text: string }

interface ScreenshotEditorProps {
  canvas: HTMLCanvasElement
  onDone: (base64: string) => void
  onCancel: () => void
}

function toCanvasCoords(e: React.PointerEvent, canvasEl: HTMLCanvasElement) {
  const rect = canvasEl.getBoundingClientRect()
  const scaleX = canvasEl.width / rect.width
  const scaleY = canvasEl.height / rect.height
  return {
    x: (e.clientX - rect.left) * scaleX,
    y: (e.clientY - rect.top) * scaleY,
  }
}

function drawArrow(ctx: CanvasRenderingContext2D, x1: number, y1: number, x2: number, y2: number) {
  const headLen = 16
  const angle = Math.atan2(y2 - y1, x2 - x1)

  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.strokeStyle = '#ef4444'
  ctx.lineWidth = 3
  ctx.stroke()

  ctx.beginPath()
  ctx.moveTo(x2, y2)
  ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6))
  ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6))
  ctx.closePath()
  ctx.fillStyle = '#ef4444'
  ctx.fill()
}

function renderOps(ctx: CanvasRenderingContext2D, bg: HTMLCanvasElement, ops: Op[]) {
  ctx.drawImage(bg, 0, 0)
  for (const op of ops) {
    ctx.save()
    switch (op.kind) {
      case 'redact':
        ctx.fillStyle = '#000'
        ctx.fillRect(op.x, op.y, op.w, op.h)
        break
      case 'highlight':
        ctx.fillStyle = 'rgba(255,255,0,0.4)'
        ctx.fillRect(op.x, op.y, op.w, op.h)
        break
      case 'arrow':
        drawArrow(ctx, op.x1, op.y1, op.x2, op.y2)
        break
      case 'text':
        ctx.font = 'bold 24px sans-serif'
        ctx.strokeStyle = '#fff'
        ctx.lineWidth = 4
        ctx.strokeText(op.text, op.x, op.y)
        ctx.fillStyle = '#ef4444'
        ctx.fillText(op.text, op.x, op.y)
        break
    }
    ctx.restore()
  }
}

export function ScreenshotEditor({ canvas: bgCanvas, onDone, onCancel }: ScreenshotEditorProps) {
  const [tool, setTool] = useState<Tool>('redact')
  const [ops, setOps] = useState<Op[]>([])
  const [drawing, setDrawing] = useState<{ startX: number; startY: number } | null>(null)
  const [textInput, setTextInput] = useState<{ x: number; y: number; clientX: number; clientY: number } | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const el = canvasRef.current
    if (!el) return
    el.width = bgCanvas.width
    el.height = bgCanvas.height
  }, [bgCanvas])

  useEffect(() => {
    const el = canvasRef.current
    if (!el) return
    const ctx = el.getContext('2d')
    if (!ctx) return
    renderOps(ctx, bgCanvas, ops)
  }, [bgCanvas, ops])

  const handlePointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    const el = canvasRef.current
    if (!el) return
    e.currentTarget.setPointerCapture(e.pointerId)
    const { x, y } = toCanvasCoords(e, el)
    setDrawing({ startX: x, startY: y })
  }, [])

  const handlePointerMove = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing) return
    const el = canvasRef.current
    if (!el) return
    const ctx = el.getContext('2d')
    if (!ctx) return
    const { x, y } = toCanvasCoords(e, el)

    renderOps(ctx, bgCanvas, ops)

    ctx.save()
    if (tool === 'redact') {
      ctx.fillStyle = '#000'
      ctx.fillRect(drawing.startX, drawing.startY, x - drawing.startX, y - drawing.startY)
    } else if (tool === 'highlight') {
      ctx.fillStyle = 'rgba(255,255,0,0.4)'
      ctx.fillRect(drawing.startX, drawing.startY, x - drawing.startX, y - drawing.startY)
    } else if (tool === 'arrow') {
      drawArrow(ctx, drawing.startX, drawing.startY, x, y)
    }
    ctx.restore()
  }, [drawing, bgCanvas, ops, tool])

  const handlePointerUp = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing) return
    const el = canvasRef.current
    if (!el) return
    const { x, y } = toCanvasCoords(e, el)

    if (tool === 'text') {
      setTextInput({ x: drawing.startX, y: drawing.startY, clientX: e.clientX, clientY: e.clientY })
      setDrawing(null)
      return
    } else if (tool === 'arrow') {
      setOps(prev => [...prev, { kind: 'arrow', x1: drawing.startX, y1: drawing.startY, x2: x, y2: y }])
    } else {
      setOps(prev => [...prev, {
        kind: tool,
        x: drawing.startX,
        y: drawing.startY,
        w: x - drawing.startX,
        h: y - drawing.startY,
      }])
    }
    setDrawing(null)
  }, [drawing, tool])

  const handleDone = useCallback(() => {
    const el = canvasRef.current
    if (!el) return
    const doneCanvas = document.createElement('canvas')
    doneCanvas.width = el.width
    doneCanvas.height = el.height
    const doneCtx = doneCanvas.getContext('2d')
    if (!doneCtx) {
      console.error('[ScreenshotEditor] Failed to get 2d context for output canvas')
      onCancel()
      return
    }
    doneCtx.drawImage(el, 0, 0)
    const dataUrl = doneCanvas.toDataURL('image/jpeg', 0.85)
    const base64 = dataUrl.split(',')[1]
    if (!base64) {
      console.error('[ScreenshotEditor] toDataURL returned unexpected format:', dataUrl.slice(0, 50))
      onCancel()
      return
    }
    onDone(base64)
  }, [onDone, onCancel])

  return (
    <div className="fixed inset-0 z-[60] flex flex-col bg-black">
      <div className="flex items-center gap-2 px-4 py-3 bg-gray-900 border-b border-gray-700">
        {(['redact', 'highlight', 'arrow', 'text'] as Tool[]).map(t => (
          <button
            key={t}
            onClick={() => setTool(t)}
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
              tool === t
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
        <button
          onClick={() => setOps(o => o.slice(0, -1))}
          disabled={ops.length === 0}
          className="ml-2 px-3 py-1.5 text-xs rounded-lg bg-gray-800 text-gray-300 hover:bg-gray-700 disabled:opacity-40"
        >
          Undo
        </button>
        <div className="flex-1" />
        <button onClick={onCancel} className="px-4 py-1.5 text-sm text-gray-300 hover:bg-gray-700 rounded-lg">Cancel</button>
        <button onClick={handleDone} className="px-4 py-1.5 text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg">Use Screenshot</button>
      </div>
      <div className="flex-1 overflow-auto flex items-center justify-center p-4">
        <canvas
          ref={canvasRef}
          className="max-w-full max-h-full cursor-crosshair border border-gray-700"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        />
      </div>
      {textInput && (
        <input
          autoFocus
          className="fixed bg-transparent text-red-500 font-bold text-2xl border-b border-red-500 outline-none z-[70]"
          style={{ left: textInput.clientX, top: textInput.clientY }}
          onKeyDown={e => {
            if (e.key === 'Enter' && e.currentTarget.value) {
              setOps(prev => [...prev, { kind: 'text', x: textInput.x, y: textInput.y, text: e.currentTarget.value }])
              setTextInput(null)
            } else if (e.key === 'Escape') {
              setTextInput(null)
            }
          }}
          onBlur={e => {
            if (e.currentTarget.value) {
              setOps(prev => [...prev, { kind: 'text', x: textInput.x, y: textInput.y, text: e.currentTarget.value }])
            }
            setTextInput(null)
          }}
        />
      )}
    </div>
  )
}
