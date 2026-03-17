import { useEffect, useRef, useState, useCallback } from 'react'
import ForceGraph2D from 'react-force-graph-2d'
import { apiFetch } from '../api'
import { useStore } from '../store'
import { typeIcon } from '../utils'

interface GraphNode {
  id: string
  title: string
  type_hint: string | null
  icon: string | null
}

interface GraphEdge {
  id: string
  source: string
  target: string
  relationship_type: string
}

interface GraphData {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

// Colors by type hint for visual differentiation
const TYPE_COLORS: Record<string, string> = {
  task: '#3b82f6',
  note: '#8b5cf6',
  project: '#f59e0b',
  idea: '#ec4899',
  goal: '#10b981',
  journal: '#6366f1',
  person: '#14b8a6',
  place: '#f97316',
  event: '#ef4444',
  concept: '#a855f7',
  reference: '#64748b',
}

function nodeColor(type_hint: string | null): string {
  if (!type_hint) return '#94a3b8'
  return TYPE_COLORS[type_hint.toLowerCase()] ?? '#94a3b8'
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s
}

export default function GraphView() {
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 })
  const thingTypes = useStore(s => s.thingTypes)

  // Fetch graph data
  useEffect(() => {
    let cancelled = false
    async function fetchGraph() {
      try {
        const res = await apiFetch('/api/things/graph')
        if (!res.ok) throw new Error(`Failed to fetch graph: ${res.status}`)
        const data: GraphData = await res.json()
        if (!cancelled) {
          setGraphData(data)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load graph')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchGraph()
    return () => { cancelled = true }
  }, [])

  // Track container size
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

  const handleNodeClick = useCallback((node: { id?: string | number }) => {
    if (node.id && typeof node.id === 'string') {
      useStore.getState().openThingDetail(node.id)
    }
  }, [])

  // Custom node rendering: circle + icon + truncated title
  const paintNode = useCallback((node: Record<string, unknown>, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const id = node.id as string
    const title = (node.title as string) || id
    const type_hint = node.type_hint as string | null
    const icon = (node.icon as string | null) || typeIcon(type_hint, thingTypes)
    const x = (node.x as number) || 0
    const y = (node.y as number) || 0
    const r = 6
    const color = nodeColor(type_hint)

    // Circle
    ctx.beginPath()
    ctx.arc(x, y, r, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
    ctx.strokeStyle = '#ffffff'
    ctx.lineWidth = 1.5 / globalScale
    ctx.stroke()

    // Icon inside circle
    const iconSize = r * 1.2
    ctx.font = `${iconSize}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(icon, x, y)

    // Label below
    if (globalScale >= 0.6) {
      const label = truncate(title, 24)
      const fontSize = Math.max(3, 10 / globalScale)
      ctx.font = `${fontSize}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle = '#e2e8f0'
      ctx.fillText(label, x, y + r + 2)
    }
  }, [thingTypes])

  // Hit area for click detection
  const paintNodeArea = useCallback((node: Record<string, unknown>, color: string, ctx: CanvasRenderingContext2D) => {
    const x = (node.x as number) || 0
    const y = (node.y as number) || 0
    const r = 8
    ctx.beginPath()
    ctx.arc(x, y, r, 0, 2 * Math.PI)
    ctx.fillStyle = color
    ctx.fill()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        Loading graph…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-red-400">
        {error}
      </div>
    )
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400">
        No things to display in graph view.
      </div>
    )
  }

  // Transform for react-force-graph: links use source/target
  const fgData = {
    nodes: graphData.nodes,
    links: graphData.edges.map(e => ({
      source: e.source,
      target: e.target,
      relationship_type: e.relationship_type,
      id: e.id,
    })),
  }

  return (
    <div ref={containerRef} className="w-full h-full bg-gray-900 relative">
      <ForceGraph2D
        graphData={fgData}
        width={dimensions.width}
        height={dimensions.height}
        nodeId="id"
        linkSource="source"
        linkTarget="target"
        nodeCanvasObject={paintNode}
        nodeCanvasObjectMode={() => 'replace'}
        nodePointerAreaPaint={paintNodeArea}
        linkColor={() => '#94a3b8'}
        linkWidth={1.5}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkLabel="relationship_type"
        onNodeClick={handleNodeClick}
        cooldownTicks={100}
        backgroundColor="#111827"
      />
    </div>
  )
}
