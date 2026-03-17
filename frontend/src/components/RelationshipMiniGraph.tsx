import { useEffect, useRef, useState, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { useStore } from '../store'
import type { UserProfileRelationship } from '../store'

interface MiniGraphNode {
  id: string
  title: string
  isCenter: boolean
}

interface MiniGraphLink {
  source: string
  target: string
  label: string
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '\u2026' : s
}

export function RelationshipMiniGraph({
  userThingId,
  userThingTitle,
  relationships,
}: {
  userThingId: string
  userThingTitle: string
  relationships: UserProfileRelationship[]
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 400, height: 250 })
  const closeSettings = useStore(s => s.closeSettings)
  const openThingDetail = useStore(s => s.openThingDetail)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const obs = new ResizeObserver(entries => {
      const entry = entries[0]
      if (entry) {
        setDimensions({
          width: entry.contentRect.width,
          height: entry.contentRect.height,
        })
      }
    })
    obs.observe(el)
    return () => obs.disconnect()
  }, [])

  // Build graph data from relationships
  const nodes: MiniGraphNode[] = [
    { id: userThingId, title: userThingTitle, isCenter: true },
  ]
  const seenIds = new Set([userThingId])
  const links: MiniGraphLink[] = []

  for (const rel of relationships) {
    if (!seenIds.has(rel.related_thing_id)) {
      nodes.push({
        id: rel.related_thing_id,
        title: rel.related_thing_title,
        isCenter: false,
      })
      seenIds.add(rel.related_thing_id)
    }
    const label = rel.relationship_type.replace(/[_-]/g, ' ')
    if (rel.direction === 'outgoing') {
      links.push({ source: userThingId, target: rel.related_thing_id, label })
    } else {
      links.push({ source: rel.related_thing_id, target: userThingId, label })
    }
  }

  const handleNodeClick = useCallback(
    (node: { id?: string | number; isCenter?: boolean }) => {
      if (node.id && typeof node.id === 'string' && !node.isCenter) {
        closeSettings()
        openThingDetail(node.id)
      }
    },
    [closeSettings, openThingDetail],
  )

  const paintNode = useCallback(
    (node: Record<string, unknown>, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const title = (node.title as string) || ''
      const isCenter = node.isCenter as boolean
      const x = (node.x as number) || 0
      const y = (node.y as number) || 0
      const r = isCenter ? 8 : 6
      const color = isCenter ? '#14b8a6' : '#94a3b8'

      // Circle
      ctx.beginPath()
      ctx.arc(x, y, r, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()
      ctx.strokeStyle = '#1f2937'
      ctx.lineWidth = 1.5 / globalScale
      ctx.stroke()

      // Label
      const label = truncate(title, 18)
      const fontSize = Math.max(3, isCenter ? 11 / globalScale : 9 / globalScale)
      ctx.font = `${isCenter ? 'bold ' : ''}${fontSize}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle = '#e2e8f0'
      ctx.fillText(label, x, y + r + 2)
    },
    [],
  )

  const paintNodeArea = useCallback(
    (node: Record<string, unknown>, color: string, ctx: CanvasRenderingContext2D) => {
      const x = (node.x as number) || 0
      const y = (node.y as number) || 0
      ctx.beginPath()
      ctx.arc(x, y, 10, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()
    },
    [],
  )

  if (relationships.length === 0) return null

  return (
    <div className="pt-3 border-t border-gray-100 dark:border-gray-800">
      <h4 className="text-xs font-medium text-gray-500 dark:text-gray-400 mb-2">
        Relationship Graph
      </h4>
      <div
        ref={containerRef}
        className="w-full rounded-lg overflow-hidden"
        style={{ height: 250, background: '#111827' }}
      >
        <ForceGraph2D
          graphData={{ nodes, links }}
          width={dimensions.width}
          height={dimensions.height}
          nodeId="id"
          linkSource="source"
          linkTarget="target"
          nodeCanvasObject={paintNode}
          nodeCanvasObjectMode={() => 'replace'}
          nodePointerAreaPaint={paintNodeArea}
          linkColor={() => '#475569'}
          linkWidth={1}
          linkDirectionalArrowLength={3}
          linkDirectionalArrowRelPos={1}
          linkLabel="label"
          onNodeClick={handleNodeClick}
          cooldownTicks={60}
          backgroundColor="#111827"
          d3VelocityDecay={0.4}
        />
      </div>
      <p className="text-[10px] text-gray-500 dark:text-gray-600 mt-1">
        Click a relationship to view details
      </p>
    </div>
  )
}
