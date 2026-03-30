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
  x?: number
  y?: number
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

// Design-system aligned colors
const TYPE_COLORS: Record<string, string> = {
  task: '#4F46E5',
  note: '#4F46E5',
  project: '#10B981',
  idea: '#F43F5E',
  goal: '#10B981',
  journal: '#4F46E5',
  person: '#14B8A6',
  place: '#14B8A6',
  event: '#F59E0B',
  concept: '#4F46E5',
  reference: '#94A3B8',
}

const LEGEND_ITEMS = [
  { label: 'Task', color: '#4F46E5' },
  { label: 'Project', color: '#10B981' },
  { label: 'Person', color: '#14B8A6' },
  { label: 'Place', color: '#14B8A6' },
  { label: 'Idea', color: '#F43F5E' },
  { label: 'Event', color: '#F59E0B' },
]

function nodeColor(type_hint: string | null): string {
  if (!type_hint) return '#94A3B8'
  return TYPE_COLORS[type_hint.toLowerCase()] ?? '#94A3B8'
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max - 1) + '…' : s
}

function typeLabel(type_hint: string | null): string {
  if (!type_hint) return 'THING'
  return type_hint.toUpperCase().replace('_', ' ')
}

function typeColorClass(type_hint: string | null): { bg: string; text: string } {
  switch (type_hint?.toLowerCase()) {
    case 'project':
    case 'goal':
      return { bg: 'bg-projects/15', text: 'text-projects' }
    case 'event':
      return { bg: 'bg-events/15', text: 'text-events' }
    case 'person':
    case 'place':
      return { bg: 'bg-people/15', text: 'text-people' }
    case 'idea':
      return { bg: 'bg-ideas/15', text: 'text-ideas' }
    default:
      return { bg: 'bg-primary/15', text: 'text-primary' }
  }
}

export default function GraphView() {
  const [graphData, setGraphData] = useState<GraphData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
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

  const handleNodeClick = useCallback((node: Record<string, unknown>) => {
    if (node.id && typeof node.id === 'string') {
      setSelectedNode(node as unknown as GraphNode)
    }
  }, [])

  const handleExplore = useCallback(() => {
    if (selectedNode) {
      useStore.getState().openThingDetail(selectedNode.id)
    }
  }, [selectedNode])

  // Connected entities for selected node
  const connectedEntities = selectedNode && graphData
    ? graphData.edges
        .filter(e => e.source === selectedNode.id || e.target === selectedNode.id)
        .map(e => {
          const otherId = e.source === selectedNode.id ? e.target : e.source
          const other = graphData.nodes.find(n => n.id === otherId)
          return other ? { id: other.id, title: other.title, type_hint: other.type_hint } : null
        })
        .filter(Boolean) as { id: string; title: string; type_hint: string | null }[]
    : []

  // Filter nodes by search
  const matchingNodeIds = searchQuery.trim()
    ? new Set(
        graphData?.nodes
          .filter(n => n.title.toLowerCase().includes(searchQuery.toLowerCase()))
          .map(n => n.id) ?? []
      )
    : null

  // Rounded rectangle node rendering
  const paintNode = useCallback((node: Record<string, unknown>, ctx: CanvasRenderingContext2D, globalScale: number) => {
    const id = node.id as string
    const title = (node.title as string) || id
    const type_hint = node.type_hint as string | null
    const icon = (node.icon as string | null) || typeIcon(type_hint, thingTypes)
    const x = (node.x as number) || 0
    const y = (node.y as number) || 0
    const size = 10
    const radius = 3
    const color = nodeColor(type_hint)
    const isSelected = selectedNode?.id === id
    const isDimmed = matchingNodeIds !== null && !matchingNodeIds.has(id)

    ctx.globalAlpha = isDimmed ? 0.15 : 1

    // Rounded square background
    const half = size
    ctx.beginPath()
    ctx.moveTo(x - half + radius, y - half)
    ctx.lineTo(x + half - radius, y - half)
    ctx.quadraticCurveTo(x + half, y - half, x + half, y - half + radius)
    ctx.lineTo(x + half, y + half - radius)
    ctx.quadraticCurveTo(x + half, y + half, x + half - radius, y + half)
    ctx.lineTo(x - half + radius, y + half)
    ctx.quadraticCurveTo(x - half, y + half, x - half, y + half - radius)
    ctx.lineTo(x - half, y - half + radius)
    ctx.quadraticCurveTo(x - half, y - half, x - half + radius, y - half)
    ctx.closePath()
    ctx.fillStyle = color
    ctx.fill()

    // Selection ring
    if (isSelected) {
      ctx.strokeStyle = '#ffffff'
      ctx.lineWidth = 2.5 / globalScale
      ctx.stroke()
    }

    // Icon inside
    const iconSize = size * 1.0
    ctx.font = `${iconSize}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillStyle = '#ffffff'
    ctx.fillText(icon, x, y)

    // Label below
    if (globalScale >= 0.5) {
      const label = truncate(title, 20)
      const fontSize = Math.max(3, 10 / globalScale)
      ctx.font = `${fontSize}px sans-serif`
      ctx.textAlign = 'center'
      ctx.textBaseline = 'top'
      ctx.fillStyle = '#E2E8F0'
      ctx.fillText(label, x, y + half + 3)
    }

    ctx.globalAlpha = 1
  }, [thingTypes, selectedNode, matchingNodeIds])

  // Hit area for click detection
  const paintNodeArea = useCallback((node: Record<string, unknown>, color: string, ctx: CanvasRenderingContext2D) => {
    const x = (node.x as number) || 0
    const y = (node.y as number) || 0
    const size = 12
    ctx.fillStyle = color
    ctx.fillRect(x - size, y - size, size * 2, size * 2)
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-on-surface-variant">
        Loading graph…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-ideas">
        {error}
      </div>
    )
  }

  if (!graphData || graphData.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-on-surface-variant">
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

  const popoverColors = selectedNode ? typeColorClass(selectedNode.type_hint) : null

  return (
    <div ref={containerRef} className="w-full h-full bg-canvas relative">
      {/* Search bar */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 w-72">
        <div className="glass rounded-xl px-4 py-2 flex items-center gap-2">
          <svg className="w-4 h-4 text-on-surface-variant shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            placeholder="Search knowledge…"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            className="bg-transparent text-on-surface text-body placeholder:text-on-surface-variant/50 outline-none w-full"
          />
        </div>
      </div>

      {/* Force graph */}
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
        linkColor={() => 'rgba(148, 163, 184, 0.3)'}
        linkWidth={1}
        linkLabel="relationship_type"
        onNodeClick={handleNodeClick}
        onBackgroundClick={() => setSelectedNode(null)}
        cooldownTicks={100}
        backgroundColor="#0b1326"
      />

      {/* Selected node popover */}
      {selectedNode && popoverColors && (
        <div className="absolute top-16 right-4 z-10 w-72 glass rounded-2xl p-5 space-y-3">
          <span className={`inline-block text-label px-2 py-0.5 rounded-full ${popoverColors.bg} ${popoverColors.text}`}>
            {typeLabel(selectedNode.type_hint)}
          </span>
          <h3 className="text-title text-on-surface">{selectedNode.title}</h3>

          {connectedEntities.length > 0 && (
            <div className="space-y-1.5">
              <span className="text-label text-on-surface-variant">Connected Entities</span>
              <ul className="space-y-1">
                {connectedEntities.slice(0, 5).map(e => (
                  <li key={e.id} className="text-body text-on-surface-variant flex items-center gap-1.5">
                    <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: nodeColor(e.type_hint) }} />
                    {truncate(e.title, 30)}
                  </li>
                ))}
                {connectedEntities.length > 5 && (
                  <li className="text-body text-on-surface-variant/50">
                    +{connectedEntities.length - 5} more
                  </li>
                )}
              </ul>
            </div>
          )}

          <div className="flex gap-2 pt-1">
            <button
              onClick={handleExplore}
              className="gradient-cta text-label px-4 py-1.5 rounded-lg"
            >
              Explore
            </button>
            <button
              onClick={() => {
                useStore.getState().openThingDetail(selectedNode.id)
                setSelectedNode(null)
              }}
              className="glass text-label text-on-surface px-4 py-1.5 rounded-lg hover:bg-surface-container-high/80"
            >
              Edit Note
            </button>
          </div>
        </div>
      )}

      {/* Legend bar */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10">
        <div className="glass rounded-xl px-5 py-2 flex items-center gap-5">
          {LEGEND_ITEMS.map(item => (
            <div key={item.label} className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: item.color }} />
              <span className="text-label text-on-surface-variant">{item.label}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
