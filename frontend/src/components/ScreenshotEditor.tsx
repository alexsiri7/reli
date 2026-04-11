/**
 * Full-screen canvas annotation editor for screenshots.
 *
 * Tools:
 *   Redact    — filled black rectangle (privacy scrubbing)
 *   Highlight — semi-transparent yellow rectangle
 *   Arrow     — red arrow pointing to a spot
 *   Text      — red text with white outline
 *
 * Undo support (Ctrl+Z / button).
 * Confirm exports the annotated canvas as JPEG; Cancel discards.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

type Tool = 'redact' | 'highlight' | 'arrow' | 'text'

interface Annotation {
  type: Tool
  x1: number
  y1: number
  x2: number
  y2: number
  text?: string
}

interface Props {
  canvas: HTMLCanvasElement
  onConfirm: (dataUrl: string) => void
  onCancel: () => void
}

const TOOL_LABELS: Record<Tool, string> = {
  redact: 'Redact',
  highlight: 'Highlight',
  arrow: 'Arrow',
  text: 'Text',
}

export function ScreenshotEditor({ canvas, onConfirm, onCancel }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const displayRef = useRef<HTMLCanvasElement>(null)
  const [tool, setTool] = useState<Tool>('arrow')
  const [annotations, setAnnotations] = useState<Annotation[]>([])
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState<{ x: number; y: number } | null>(null)
  const [pendingText, setPendingText] = useState<{ x: number; y: number } | null>(null)
  const [textInput, setTextInput] = useState('')
  const textInputRef = useRef<HTMLInputElement>(null)

  // Scale factor: display canvas fits in viewport while preserving aspect ratio
  const [scale, setScale] = useState(1)

  useEffect(() => {
    const update = () => {
      const vw = window.innerWidth - 32
      const vh = window.innerHeight - 128 // leave room for toolbar
      const scaleW = vw / canvas.width
      const scaleH = vh / canvas.height
      setScale(Math.min(scaleW, scaleH, 1))
    }
    update()
    window.addEventListener('resize', update)
    return () => window.removeEventListener('resize', update)
  }, [canvas])

  const redraw = useCallback(
    (extraAnnotation?: Annotation) => {
      const dc = displayRef.current
      if (!dc) return
      const ctx = dc.getContext('2d')
      if (!ctx) return

      dc.width = canvas.width
      dc.height = canvas.height
      ctx.drawImage(canvas, 0, 0)

      const all = extraAnnotation ? [...annotations, extraAnnotation] : annotations
      for (const ann of all) {
        drawAnnotation(ctx, ann)
      }
    },
    [canvas, annotations],
  )

  useEffect(() => {
    redraw()
  }, [redraw])

  function toCanvasCoords(e: React.MouseEvent<HTMLCanvasElement>) {
    const dc = displayRef.current!
    const rect = dc.getBoundingClientRect()
    return {
      x: ((e.clientX - rect.left) / scale),
      y: ((e.clientY - rect.top) / scale),
    }
  }

  function handleMouseDown(e: React.MouseEvent<HTMLCanvasElement>) {
    if (tool === 'text') {
      const pos = toCanvasCoords(e)
      setPendingText(pos)
      setTextInput('')
      setTimeout(() => textInputRef.current?.focus(), 0)
      return
    }
    setDragging(true)
    setDragStart(toCanvasCoords(e))
  }

  function handleMouseMove(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!dragging || !dragStart) return
    const pos = toCanvasCoords(e)
    redraw({ type: tool, x1: dragStart.x, y1: dragStart.y, x2: pos.x, y2: pos.y })
  }

  function handleMouseUp(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!dragging || !dragStart) return
    const pos = toCanvasCoords(e)
    const ann: Annotation = { type: tool, x1: dragStart.x, y1: dragStart.y, x2: pos.x, y2: pos.y }
    setAnnotations(prev => [...prev, ann])
    setDragging(false)
    setDragStart(null)
  }

  function commitText() {
    if (!pendingText || !textInput.trim()) {
      setPendingText(null)
      return
    }
    const ann: Annotation = {
      type: 'text',
      x1: pendingText.x,
      y1: pendingText.y,
      x2: pendingText.x,
      y2: pendingText.y,
      text: textInput.trim(),
    }
    setAnnotations(prev => [...prev, ann])
    setPendingText(null)
    setTextInput('')
  }

  function handleUndo() {
    setAnnotations(prev => prev.slice(0, -1))
  }

  function handleConfirm() {
    const dc = displayRef.current
    if (!dc) return
    onConfirm(dc.toDataURL('image/jpeg', 0.85))
  }

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') onCancel()
      if ((e.ctrlKey || e.metaKey) && e.key === 'z') {
        e.preventDefault()
        handleUndo()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  const displayW = Math.round(canvas.width * scale)
  const displayH = Math.round(canvas.height * scale)

  return (
    <div
      ref={containerRef}
      className="fixed inset-0 z-[60] flex flex-col items-center bg-black/90"
      data-screenshot-exclude="true"
    >
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-4 py-2 bg-gray-900 w-full border-b border-gray-700">
        <span className="text-xs text-gray-400 mr-2">Annotate:</span>
        {(Object.keys(TOOL_LABELS) as Tool[]).map(t => (
          <button
            key={t}
            onClick={() => setTool(t)}
            className={`px-3 py-1.5 text-xs rounded-md transition-colors ${
              tool === t
                ? 'bg-indigo-600 text-white'
                : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
            }`}
          >
            {TOOL_LABELS[t]}
          </button>
        ))}
        <div className="flex-1" />
        <button
          onClick={handleUndo}
          disabled={annotations.length === 0}
          className="px-3 py-1.5 text-xs rounded-md bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          Undo
        </button>
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-xs rounded-md bg-gray-700 text-gray-300 hover:bg-gray-600"
        >
          Cancel
        </button>
        <button
          onClick={handleConfirm}
          className="px-3 py-1.5 text-xs rounded-md bg-indigo-600 text-white hover:bg-indigo-700"
        >
          Use Screenshot
        </button>
      </div>

      {/* Canvas area */}
      <div className="flex-1 flex items-center justify-center overflow-auto p-4 relative">
        <div style={{ position: 'relative', width: displayW, height: displayH }}>
          <canvas
            ref={displayRef}
            style={{
              width: displayW,
              height: displayH,
              cursor: tool === 'text' ? 'text' : 'crosshair',
              display: 'block',
            }}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
          />
          {/* Text input overlay */}
          {pendingText && (
            <input
              ref={textInputRef}
              value={textInput}
              onChange={e => setTextInput(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter') commitText()
                if (e.key === 'Escape') setPendingText(null)
              }}
              onBlur={commitText}
              style={{
                position: 'absolute',
                left: pendingText.x * scale,
                top: pendingText.y * scale - 14,
                minWidth: 120,
                background: 'transparent',
                border: 'none',
                outline: '1px dashed rgba(255,0,0,0.7)',
                color: 'red',
                fontSize: 16,
                fontWeight: 'bold',
                padding: '1px 2px',
              }}
              placeholder="Type and press Enter"
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Drawing helpers
// ---------------------------------------------------------------------------

function drawAnnotation(ctx: CanvasRenderingContext2D, ann: Annotation) {
  const { type, x1, y1, x2, y2 } = ann
  ctx.save()

  if (type === 'redact') {
    ctx.fillStyle = '#000000'
    ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1))
  } else if (type === 'highlight') {
    ctx.fillStyle = 'rgba(255, 230, 0, 0.45)'
    ctx.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1))
  } else if (type === 'arrow') {
    drawArrow(ctx, x1, y1, x2, y2)
  } else if (type === 'text' && ann.text) {
    drawText(ctx, x1, y1, ann.text)
  }

  ctx.restore()
}

function drawArrow(
  ctx: CanvasRenderingContext2D,
  x1: number,
  y1: number,
  x2: number,
  y2: number,
) {
  const headLen = 18
  const angle = Math.atan2(y2 - y1, x2 - x1)

  ctx.strokeStyle = '#ff0000'
  ctx.fillStyle = '#ff0000'
  ctx.lineWidth = 3
  ctx.lineCap = 'round'

  // Shaft
  ctx.beginPath()
  ctx.moveTo(x1, y1)
  ctx.lineTo(x2, y2)
  ctx.stroke()

  // Arrowhead
  ctx.beginPath()
  ctx.moveTo(x2, y2)
  ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6))
  ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6))
  ctx.closePath()
  ctx.fill()
}

function drawText(ctx: CanvasRenderingContext2D, x: number, y: number, text: string) {
  ctx.font = 'bold 18px sans-serif'
  ctx.lineWidth = 3
  ctx.strokeStyle = '#ffffff'
  ctx.strokeText(text, x, y)
  ctx.fillStyle = '#ff0000'
  ctx.fillText(text, x, y)
}
