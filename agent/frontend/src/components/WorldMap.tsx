import { useState, useMemo, useEffect, useRef, useCallback, Component } from 'react'
import type { BotSnapshot, Waypoint, OnlinePlayer } from '../types'
import type { ContainerInfo, MEInterface } from '../hooks'
import {
  useWaypoints, useContainers, createWaypoint, deleteWaypoint,
  sendGoto, sendTeleport, fetchContainerContents, usePlayers, useMEInterfaces,
} from '../hooks'

const MAP_SIZE = 400
const BLOCK_PX = 2
const MIN_ZOOM = 0.5
const MAX_ZOOM = 8

function dimLabel(dim: string): string {
  return (dim || '').replace('minecraft:', '').split('_').join(' ')
}

function dimColor(dim: string): string {
  if (dim.includes('nether')) return '#ff5555'
  if (dim.includes('end')) return '#aa00ff'
  if (dim.includes('overworld')) return '#55ffff'
  return '#55ff55'
}

function dimBg(dim: string): string {
  if (dim.includes('nether')) return '#1a0505'
  if (dim.includes('end')) return '#0a0512'
  return '#050f0f'
}

interface TerrainBlock { x: number; z: number; y: number; block: string }

const BLOCK_COLORS: Record<string, string> = {
  'minecraft:grass_block': '#5a8c32', 'minecraft:dirt': '#8b6914',
  'minecraft:stone': '#7a7a7a', 'minecraft:deepslate': '#4a4a4e',
  'minecraft:water': '#3355cc', 'minecraft:sand': '#d4c48c',
  'minecraft:gravel': '#8a8480', 'minecraft:oak_log': '#6b5230',
  'minecraft:birch_log': '#c8bfa0', 'minecraft:spruce_log': '#3d2a16',
  'minecraft:oak_leaves': '#3a7a20', 'minecraft:birch_leaves': '#5a9028',
  'minecraft:spruce_leaves': '#2a5018', 'minecraft:oak_planks': '#a0803a',
  'minecraft:cobblestone': '#6a6a6a', 'minecraft:iron_ore': '#8a7a6a',
  'minecraft:coal_ore': '#3a3a3a', 'minecraft:snow_block': '#e8e8f0',
  'minecraft:snow': '#e8e8f0', 'minecraft:ice': '#8ab8e0',
  'minecraft:clay': '#9898a8', 'minecraft:netherrack': '#6a2020',
  'minecraft:nether_bricks': '#3a1a1a', 'minecraft:soul_sand': '#4a3a2a',
  'minecraft:basalt': '#3a3a3a', 'minecraft:blackstone': '#2a2228',
  'minecraft:crimson_nylium': '#8a2030', 'minecraft:warped_nylium': '#207050',
  'minecraft:end_stone': '#d4d098', 'minecraft:obsidian': '#1a0a2a',
  'minecraft:lava': '#cc5500', 'minecraft:bedrock': '#333333',
  'minecraft:mycelium': '#7a6878', 'minecraft:podzol': '#6a5a24',
  'minecraft:red_sand': '#b8602a', 'minecraft:terracotta': '#985838',
  'minecraft:moss_block': '#4a7828', 'minecraft:mud': '#3a3028',
  'minecraft:packed_ice': '#7098c0', 'minecraft:blue_ice': '#5080c0',
}

function blockColor(block: string): string {
  if (BLOCK_COLORS[block]) return BLOCK_COLORS[block]
  if (block.includes('log') || block.includes('wood')) return '#6b5230'
  if (block.includes('leaves')) return '#3a7a20'
  if (block.includes('planks')) return '#a0803a'
  if (block.includes('stone') || block.includes('andesite') || block.includes('diorite') || block.includes('granite')) return '#7a7a7a'
  if (block.includes('ore')) return '#8a7a6a'
  if (block.includes('sand')) return '#d4c48c'
  if (block.includes('dirt') || block.includes('mud')) return '#8b6914'
  if (block.includes('grass')) return '#5a8c32'
  if (block.includes('water')) return '#3355cc'
  if (block.includes('lava')) return '#cc5500'
  if (block.includes('ice') || block.includes('snow')) return '#c0d0e8'
  if (block.includes('nether')) return '#6a2020'
  if (block.includes('end_')) return '#d4d098'
  return '#555555'
}

type MapMode = 'view' | 'move' | 'waypoint'
interface ContainerSlot { slot: number; item: string; count: number }

function asArray<T>(v: unknown): T[] {
  return Array.isArray(v) ? v : []
}

// Error boundary prevents blank screens from map crashes
class MapErrorBoundary extends Component<
  { children: React.ReactNode },
  { error: string | null }
> {
  state = { error: null as string | null }
  static getDerivedStateFromError(e: Error) { return { error: e.message } }
  render() {
    if (this.state.error) {
      return (
        <div className="panel p-3 text-center">
          <div className="text-mc-red text-sm mb-2">Map error</div>
          <div className="text-mc-gray text-xs mb-2">{this.state.error}</div>
          <button
            onClick={() => this.setState({ error: null })}
            className="text-xs px-2 py-1 bg-mc-accent rounded text-white"
          >
            Retry
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

function WorldMapInner({
  bots, selectedBot, onSelect, onCenterBot,
}: {
  bots: BotSnapshot[]
  selectedBot: string | null
  onSelect: (name: string) => void
  onCenterBot?: string | null
}) {
  const [terrain, setTerrain] = useState<TerrainBlock[]>([])
  const [terrainLoading, setTerrainLoading] = useState(false)

  const zoomRef = useRef(1)
  const [zoom, _setZoom] = useState(1)
  const setZoom = useCallback((fn: (z: number) => number) => {
    _setZoom((prev) => { const n = fn(prev); zoomRef.current = n; return n })
  }, [])

  const panRef = useRef({ x: 0, z: 0 })
  const [panOffset, _setPanOffset] = useState({ x: 0, z: 0 })
  const setPanOffset = useCallback((v: { x: number; z: number }) => {
    panRef.current = v
    _setPanOffset(v)
  }, [])

  const draggingRef = useRef(false)
  const dragStartRef = useRef({ x: 0, y: 0 })
  const dragPanStartRef = useRef({ x: 0, z: 0 })
  const lastTouchRef = useRef<{ x: number; y: number } | null>(null)
  const pinchDistRef = useRef<number | null>(null)

  const velocityRef = useRef({ x: 0, z: 0 })
  const lastDragTimeRef = useRef(0)
  const lastDragPtRef = useRef({ x: 0, y: 0 })
  const inertiaFrameRef = useRef(0)

  const startInertia = useCallback(() => {
    cancelAnimationFrame(inertiaFrameRef.current)
    const decay = 0.92
    const minV = 0.3
    const animate = () => {
      const v = velocityRef.current
      if (Math.abs(v.x) < minV && Math.abs(v.z) < minV) return
      setPanOffset({ x: panRef.current.x + v.x, z: panRef.current.z + v.z })
      velocityRef.current = { x: v.x * decay, z: v.z * decay }
      inertiaFrameRef.current = requestAnimationFrame(animate)
    }
    inertiaFrameRef.current = requestAnimationFrame(animate)
  }, [setPanOffset])

  useEffect(() => {
    return () => cancelAnimationFrame(inertiaFrameRef.current)
  }, [])

  const [mode, setMode] = useState<MapMode>('view')
  const [moveBot, setMoveBot] = useState<string | null>(null)
  const [followBot, setFollowBot] = useState<string | null>(null)
  const modeRef = useRef(mode)
  modeRef.current = mode
  const moveBotRef = useRef(moveBot)
  moveBotRef.current = moveBot

  const [tooltip, setTooltip] = useState<{
    type: 'bot' | 'waypoint' | 'container' | 'player'
    data: Record<string, unknown>
    screenX: number; screenY: number
  } | null>(null)

  const [wpName, setWpName] = useState('')
  const [wpPending, setWpPending] = useState<{ x: number; z: number } | null>(null)
  const [containerPanel, setContainerPanel] = useState<{
    container: ContainerInfo; contents: ContainerSlot[]; loading: boolean
  } | null>(null)
  const [storePickerOpen, setStorePickerOpen] = useState(false)

  const [rawWaypoints, refreshWaypoints] = useWaypoints()
  const rawContainers = useContainers()
  const onlinePlayers = usePlayers()
  const meData = useMEInterfaces()
  const waypoints = asArray<Waypoint>(rawWaypoints)
  const containers = asArray<ContainerInfo>(rawContainers)
  const meInterfaces = meData.interfaces

  const svgRef = useRef<SVGSVGElement>(null)
  const wrapperRef = useRef<HTMLDivElement>(null)

  const dimensions = useMemo(() => {
    const dims = new Set<string>()
    bots.forEach((b) => dims.add(b.status?.dimension || 'minecraft:overworld'))
    onlinePlayers.forEach((p) => dims.add(p.dimension || 'minecraft:overworld'))
    return Array.from(dims).sort()
  }, [bots, onlinePlayers])

  const [activeDim, setActiveDim] = useState<string | null>(null)
  const currentDim = activeDim || dimensions[0] || 'minecraft:overworld'
  const dimBots = bots.filter((b) => (b.status?.dimension || 'minecraft:overworld') === currentDim)
  const dimPlayers = onlinePlayers.filter((p) => (p.dimension || 'minecraft:overworld') === currentDim)
  const dimWaypoints = waypoints.filter((w) => (w.dimension || 'minecraft:overworld') === currentDim)
  const dimContainers = containers
    .filter((c) => (c.dimension || 'minecraft:overworld') === currentDim)
    .filter((c, i, arr) => arr.findIndex((o) => o.x === c.x && o.y === c.y && o.z === c.z) === i)
  const selectedBotData = selectedBot ? bots.find((b) => b.name === selectedBot) : null

  const baseCenterX = dimBots.length
    ? dimBots.reduce((s, b) => s + (b.status?.position?.x ?? 0), 0) / dimBots.length : 0
  const baseCenterZ = dimBots.length
    ? dimBots.reduce((s, b) => s + (b.status?.position?.z ?? 0), 0) / dimBots.length : 0
  const centerX = baseCenterX + panOffset.x
  const centerZ = baseCenterZ + panOffset.z

  const centerXRef = useRef(centerX)
  centerXRef.current = centerX
  const centerZRef = useRef(centerZ)
  centerZRef.current = centerZ

  useEffect(() => {
    setFollowBot(onCenterBot || null)
  }, [onCenterBot])

  useEffect(() => {
    if (!followBot) return
    const bot = bots.find((b) => b.name === followBot)
    if (!bot?.status?.position) return
    const dim = bot.status.dimension || 'minecraft:overworld'
    if (dim !== currentDim) setActiveDim(dim)
    setPanOffset({
      x: (bot.status.position.x ?? 0) - baseCenterX,
      z: (bot.status.position.z ?? 0) - baseCenterZ,
    })
  }, [followBot, bots])

  const stableCenterX = useRef(centerX)
  const stableCenterZ = useRef(centerZ)
  if (Math.abs(centerX - stableCenterX.current) > 15) stableCenterX.current = centerX
  if (Math.abs(centerZ - stableCenterZ.current) > 15) stableCenterZ.current = centerZ

  useEffect(() => {
    const abort = new AbortController()
    setTerrainLoading(true)
    const cx = Math.round(stableCenterX.current)
    const cz = Math.round(stableCenterZ.current)
    const radius = Math.round(MAP_SIZE / BLOCK_PX / 2 / Math.min(zoom, 2))
    fetch(`/api/terrain?dimension=${encodeURIComponent(currentDim)}&cx=${cx}&cz=${cz}&radius=${radius}`, { signal: abort.signal })
      .then((r) => r.json())
      .then((d) => { setTerrain(d.blocks?.length ? d.blocks : []) })
      .catch(() => {})
      .finally(() => setTerrainLoading(false))
    return () => abort.abort()
  }, [currentDim, Math.round(stableCenterX.current / 20), Math.round(stableCenterZ.current / 20)])

  // Render terrain to offscreen canvas to avoid SVG rect ghosting
  const terrainDataUrl = useMemo(() => {
    if (terrain.length === 0) return ''
    try {
      const canvas = document.createElement('canvas')
      canvas.width = MAP_SIZE
      canvas.height = MAP_SIZE
      const ctx = canvas.getContext('2d')
      if (!ctx) return ''
      const sz = Math.max(BLOCK_PX * zoom, 1)
      for (const b of terrain) {
        const sx = MAP_SIZE / 2 + (b.x - centerX) * BLOCK_PX * zoom
        const sy = MAP_SIZE / 2 + (b.z - centerZ) * BLOCK_PX * zoom
        if (sx < -sz || sx > MAP_SIZE + sz || sy < -sz || sy > MAP_SIZE + sz) continue
        ctx.fillStyle = blockColor(b.block)
        ctx.fillRect(sx, sy, sz, sz)
      }
      return canvas.toDataURL()
    } catch { return '' }
  }, [terrain, centerX, centerZ, zoom])

  const worldToScreen = useCallback((wx: number, wz: number) => ({
    x: MAP_SIZE / 2 + (wx - centerX) * BLOCK_PX * zoom,
    y: MAP_SIZE / 2 + (wz - centerZ) * BLOCK_PX * zoom,
  }), [centerX, centerZ, zoom])

  const screenToWorldRef = useRef((sx: number, sy: number) => ({
    x: centerX + (sx - MAP_SIZE / 2) / (BLOCK_PX * zoom),
    z: centerZ + (sy - MAP_SIZE / 2) / (BLOCK_PX * zoom),
  }))
  screenToWorldRef.current = (sx: number, sy: number) => ({
    x: centerXRef.current + (sx - MAP_SIZE / 2) / (BLOCK_PX * zoomRef.current),
    z: centerZRef.current + (sy - MAP_SIZE / 2) / (BLOCK_PX * zoomRef.current),
  })

  const getSvgCoords = useCallback((clientX: number, clientY: number) => {
    const svg = svgRef.current
    if (!svg) return { x: 0, y: 0 }
    const rect = svg.getBoundingClientRect()
    return {
      x: ((clientX - rect.left) / rect.width) * MAP_SIZE,
      y: ((clientY - rect.top) / rect.height) * MAP_SIZE,
    }
  }, [])

  // ── Native event listeners for wheel + touch ──
  useEffect(() => {
    const svg = svgRef.current
    if (!svg) return

    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      e.stopPropagation()
      const factor = e.deltaY < 0 ? 1.2 : 1 / 1.2
      setZoom((z) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z * factor)))
    }

    const onTouchStart = (e: TouchEvent) => {
      if (e.touches.length === 2) {
        e.preventDefault()
        const dx = e.touches[0].clientX - e.touches[1].clientX
        const dy = e.touches[0].clientY - e.touches[1].clientY
        pinchDistRef.current = Math.hypot(dx, dy)
        return
      }
      if (e.touches.length === 1) {
        cancelAnimationFrame(inertiaFrameRef.current)
        velocityRef.current = { x: 0, z: 0 }
        setFollowBot(null)
        const t = e.touches[0]
        const pt = getSvgCoords(t.clientX, t.clientY)
        draggingRef.current = true
        dragStartRef.current = pt
        dragPanStartRef.current = panRef.current
        lastTouchRef.current = pt
        lastDragPtRef.current = pt
        lastDragTimeRef.current = performance.now()
      }
    }

    const onTouchMove = (e: TouchEvent) => {
      if (e.touches.length === 2 && pinchDistRef.current !== null) {
        e.preventDefault()
        const dx = e.touches[0].clientX - e.touches[1].clientX
        const dy = e.touches[0].clientY - e.touches[1].clientY
        const dist = Math.hypot(dx, dy)
        const scale = dist / pinchDistRef.current
        pinchDistRef.current = dist
        setZoom((z) => Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, z * scale)))
        return
      }
      if (e.touches.length === 1 && draggingRef.current) {
        e.preventDefault()
        const t = e.touches[0]
        const pt = getSvgCoords(t.clientX, t.clientY)
        lastTouchRef.current = pt
        const z = zoomRef.current
        const dx = (pt.x - dragStartRef.current.x) / (BLOCK_PX * z)
        const dz = (pt.y - dragStartRef.current.y) / (BLOCK_PX * z)
        setPanOffset({ x: dragPanStartRef.current.x - dx, z: dragPanStartRef.current.z - dz })

        const now = performance.now()
        const dt = now - lastDragTimeRef.current
        if (dt > 0) {
          const vx = -(pt.x - lastDragPtRef.current.x) / (BLOCK_PX * z)
          const vz = -(pt.y - lastDragPtRef.current.y) / (BLOCK_PX * z)
          velocityRef.current = { x: vx, z: vz }
        }
        lastDragPtRef.current = pt
        lastDragTimeRef.current = now
      }
    }

    const onTouchEnd = (e: TouchEvent) => {
      pinchDistRef.current = null
      if (!draggingRef.current) return
      draggingRef.current = false
      const pt = lastTouchRef.current
      if (!pt) return
      const dist = Math.hypot(pt.x - dragStartRef.current.x, pt.y - dragStartRef.current.y)
      if (dist > 8) {
        if (performance.now() - lastDragTimeRef.current < 50) startInertia()
        return
      }
      handleMapTap(pt.x, pt.y, e)
    }

    svg.addEventListener('wheel', onWheel, { passive: false })
    svg.addEventListener('touchstart', onTouchStart, { passive: false })
    svg.addEventListener('touchmove', onTouchMove, { passive: false })
    svg.addEventListener('touchend', onTouchEnd)
    return () => {
      svg.removeEventListener('wheel', onWheel)
      svg.removeEventListener('touchstart', onTouchStart)
      svg.removeEventListener('touchmove', onTouchMove)
      svg.removeEventListener('touchend', onTouchEnd)
    }
  }, [getSvgCoords, setZoom, setPanOffset, startInertia])

  const handleMapTap = useCallback((sx: number, sy: number, _e?: Event) => {
    try {
      const world = screenToWorldRef.current(sx, sy)
      if (modeRef.current === 'move' && moveBotRef.current) {
        sendGoto(moveBotRef.current, Math.round(world.x), 64, Math.round(world.z))
        setMode('view')
        setMoveBot(null)
        setTooltip(null)
        return
      }
      if (modeRef.current === 'waypoint') {
        setWpPending({ x: Math.round(world.x), z: Math.round(world.z) })
      }
    } catch {
      // ignore tap errors
    }
  }, [])

  // ── Mouse handlers (desktop) ──
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return
    cancelAnimationFrame(inertiaFrameRef.current)
    velocityRef.current = { x: 0, z: 0 }
    setFollowBot(null)
    const pt = getSvgCoords(e.clientX, e.clientY)
    draggingRef.current = true
    dragStartRef.current = pt
    dragPanStartRef.current = panRef.current
    lastDragPtRef.current = pt
    lastDragTimeRef.current = performance.now()
  }, [getSvgCoords])

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!draggingRef.current) return
    const pt = getSvgCoords(e.clientX, e.clientY)
    const z = zoomRef.current
    const dx = (pt.x - dragStartRef.current.x) / (BLOCK_PX * z)
    const dz = (pt.y - dragStartRef.current.y) / (BLOCK_PX * z)
    setPanOffset({ x: dragPanStartRef.current.x - dx, z: dragPanStartRef.current.z - dz })

    const now = performance.now()
    const dt = now - lastDragTimeRef.current
    if (dt > 0) {
      const vx = -(pt.x - lastDragPtRef.current.x) / (BLOCK_PX * z)
      const vz = -(pt.y - lastDragPtRef.current.y) / (BLOCK_PX * z)
      velocityRef.current = { x: vx, z: vz }
    }
    lastDragPtRef.current = pt
    lastDragTimeRef.current = now
  }, [getSvgCoords, setPanOffset])

  const handleMouseUp = useCallback((e: React.MouseEvent) => {
    const was = draggingRef.current
    draggingRef.current = false
    if (!was) return
    const pt = getSvgCoords(e.clientX, e.clientY)
    const dist = Math.hypot(pt.x - dragStartRef.current.x, pt.y - dragStartRef.current.y)
    if (dist > 5) {
      if (performance.now() - lastDragTimeRef.current < 50) startInertia()
      return
    }
    handleMapTap(pt.x, pt.y)
  }, [getSvgCoords, handleMapTap, startInertia])

  // ── Marker click handlers ──
  const getWrapperOffset = useCallback((e: React.MouseEvent) => {
    const w = wrapperRef.current
    if (!w) return { x: 0, y: 0 }
    const r = w.getBoundingClientRect()
    return { x: e.clientX - r.left, y: e.clientY - r.top }
  }, [])

  const handleBotClick = useCallback((e: React.MouseEvent, bot: BotSnapshot) => {
    e.stopPropagation()
    draggingRef.current = false
    if (mode === 'move') { setMoveBot(bot.name); return }
    onSelect(bot.name)
    const off = getWrapperOffset(e)
    setTooltip({
      type: 'bot',
      data: {
        name: bot.name,
        health: bot.status?.health ?? 0,
        food: bot.status?.food ?? 0,
        xp: bot.status?.xp_level ?? 0,
        plan: bot.plan?.instruction || 'idle',
        alive: bot.status?.alive ?? bot.status?.is_alive ?? true,
      },
      screenX: off.x, screenY: off.y,
    })
  }, [mode, onSelect, getWrapperOffset])

  const handleWaypointClick = useCallback((e: React.MouseEvent, wp: Waypoint) => {
    e.stopPropagation()
    draggingRef.current = false
    const off = getWrapperOffset(e)
    setTooltip({
      type: 'waypoint',
      data: { name: wp.name, x: wp.x, y: wp.y, z: wp.z, set_by: wp.set_by || '' },
      screenX: off.x, screenY: off.y,
    })
  }, [getWrapperOffset])

  const handleContainerClick = useCallback((e: React.MouseEvent, c: ContainerInfo) => {
    e.stopPropagation()
    draggingRef.current = false
    const off = getWrapperOffset(e)
    setTooltip({
      type: 'container',
      data: { x: c.x, y: c.y, z: c.z, placed_by: c.placed_by || '' },
      screenX: off.x, screenY: off.y,
    })
    setContainerPanel({ container: c, contents: [], loading: true })
    fetchContainerContents(c.x, c.y, c.z).then((d) => {
      setContainerPanel((p) => p ? { ...p, contents: d.items || [], loading: false } : null)
    }).catch(() => {
      setContainerPanel((p) => p ? { ...p, loading: false } : null)
    })
  }, [getWrapperOffset])

  const saveWaypoint = useCallback(async () => {
    if (!wpPending || !wpName.trim()) return
    const bot = dimBots[0]
    const y = bot ? Math.round(bot.status?.position?.y ?? 64) : 64
    await createWaypoint(wpName.trim(), wpPending.x, y, wpPending.z, currentDim)
    setWpPending(null); setWpName(''); setMode('view')
    refreshWaypoints()
  }, [wpPending, wpName, dimBots, currentDim, refreshWaypoints])

  if (bots.length === 0) {
    return (
      <div className="panel flex items-center justify-center" style={{ height: 200 }}>
        <span className="text-mc-gray text-sm">No bots online</span>
      </div>
    )
  }

  const halfMap = MAP_SIZE / 2
  const inv = selectedBotData?.inventory || []

  return (
    <div ref={wrapperRef} className="panel p-3 relative">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-mc-gold font-bold text-sm">World Map</h3>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-mc-gray">
            {terrain.length > 0 ? `${terrain.length} blk` : terrainLoading ? 'scan...' : ''}
          </span>
          <span className="text-[10px] text-mc-gray">{zoom.toFixed(1)}x</span>
        </div>
      </div>

      {/* Dimension tabs */}
      <div className="flex gap-1 mb-2 flex-wrap">
        {dimensions.map((dim) => {
          const botCount = bots.filter((b) => (b.status?.dimension || 'minecraft:overworld') === dim).length
          const playerCount = onlinePlayers.filter((p) => (p.dimension || 'minecraft:overworld') === dim).length
          const count = botCount + playerCount
          return (
            <button
              key={dim}
              onClick={() => setActiveDim(dim)}
              className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
                currentDim === dim ? 'font-medium text-black' : 'text-white hover:opacity-80'
              }`}
              style={{ backgroundColor: currentDim === dim ? dimColor(dim) : '#0f3460' }}
            >
              {dimLabel(dim)} ({count})
            </button>
          )
        })}
      </div>

      {/* Mode toolbar */}
      <div className="flex gap-1 mb-2">
        {([['view', 'Pan'], ['move', 'Move Bot'], ['waypoint', 'Waypoint']] as [MapMode, string][]).map(([m, label]) => (
          <button
            key={m}
            onClick={() => { setMode(m); setMoveBot(null); setWpPending(null); setTooltip(null) }}
            className={`text-[10px] px-2 py-0.5 rounded transition-colors ${
              mode === m ? 'bg-mc-gold text-black font-medium' : 'bg-mc-accent text-mc-gray hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
        {selectedBot && !followBot && (
          <button
            onClick={() => setFollowBot(selectedBot)}
            className="text-[10px] px-2 py-0.5 rounded bg-mc-accent text-mc-aqua hover:text-white ml-auto"
          >
            Follow {selectedBot}
          </button>
        )}
        {followBot && (
          <span className="text-[10px] text-mc-aqua ml-auto">
            Following {followBot}
          </span>
        )}
        {!selectedBot && (
          <button
            onClick={() => { setZoom(() => 1); setPanOffset({ x: 0, z: 0 }) }}
            className="text-[10px] px-2 py-0.5 rounded bg-mc-accent text-mc-gray hover:text-white ml-auto"
          >
            Reset
          </button>
        )}
      </div>

      {mode === 'move' && (
        <div className="text-[10px] text-yellow-400 mb-1">
          {moveBot ? `Tap map to send ${moveBot} there` : 'Tap a bot, then tap destination'}
        </div>
      )}
      {mode === 'waypoint' && !wpPending && (
        <div className="text-[10px] text-mc-aqua mb-1">Tap map to place waypoint</div>
      )}

      {wpPending && (
        <div className="flex gap-1 mb-2">
          <input
            type="text" value={wpName}
            onChange={(e) => setWpName(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && saveWaypoint()}
            placeholder="Waypoint name..."
            className="flex-1 bg-mc-dark border border-mc-accent rounded px-2 py-0.5 text-xs text-white"
            autoFocus
          />
          <button onClick={saveWaypoint} className="text-[10px] px-2 py-0.5 rounded bg-mc-green text-black font-medium">Save</button>
          <button onClick={() => { setWpPending(null); setWpName('') }} className="text-[10px] px-2 py-0.5 rounded bg-mc-accent text-mc-gray">Cancel</button>
        </div>
      )}

      {/* Map container — SVG for terrain/grid, HTML overlay for markers */}
      <div className="relative" style={{ width: '100%', aspectRatio: '1' }}>
        <svg
          ref={svgRef}
          width={MAP_SIZE} height={MAP_SIZE}
          viewBox={`0 0 ${MAP_SIZE} ${MAP_SIZE}`}
          className="w-full h-full rounded border border-mc-accent select-none touch-none"
          style={{
            background: dimBg(currentDim),
            cursor: mode === 'move' ? 'crosshair' : mode === 'waypoint' ? 'cell' : 'grab',
          }}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => { if (draggingRef.current) { draggingRef.current = false; if (performance.now() - lastDragTimeRef.current < 50) startInertia() } }}
        >
          {/* Terrain (canvas-rendered) */}
          {terrainDataUrl && (
            <image href={terrainDataUrl} x={0} y={0} width={MAP_SIZE} height={MAP_SIZE} />
          )}

          {/* Grid */}
          {Array.from({ length: 7 }, (_, i) => {
            const pos = (i * MAP_SIZE) / 6
            return (
              <g key={i} opacity={0.1}>
                <line x1={pos} y1={0} x2={pos} y2={MAP_SIZE} stroke="#fff" strokeWidth={0.3} />
                <line x1={0} y1={pos} x2={MAP_SIZE} y2={pos} stroke="#fff" strokeWidth={0.3} />
              </g>
            )
          })}

          {/* Coords */}
          <text x={4} y={MAP_SIZE - 4} fill="#666" fontSize={7}>
            {Math.round(centerX - halfMap / (BLOCK_PX * zoom))}, {Math.round(centerZ - halfMap / (BLOCK_PX * zoom))}
          </text>
          <text x={MAP_SIZE - 4} y={12} textAnchor="end" fill="#666" fontSize={7}>
            {Math.round(centerX + halfMap / (BLOCK_PX * zoom))}, {Math.round(centerZ + halfMap / (BLOCK_PX * zoom))}
          </text>
        </svg>

        {/* HTML marker overlay — GPU-composited, no SVG ghosting */}
        <div className="absolute inset-0 overflow-hidden rounded pointer-events-none" style={{ zIndex: 1, willChange: 'transform' }}>
          {/* Containers */}
          {dimContainers.map((c) => {
            const s = worldToScreen(c.x, c.z)
            if (s.x < -10 || s.x > MAP_SIZE + 10 || s.y < -10 || s.y > MAP_SIZE + 10) return null
            return (
              <div
                key={`c-${c.x}-${c.y}-${c.z}`}
                className="absolute pointer-events-auto cursor-pointer"
                style={{ left: 0, top: 0, transform: `translate3d(${s.x - 6}px, ${s.y - 6}px, 0)` }}
                onClick={(e) => handleContainerClick(e, c)}
              >
                <div className="w-3 h-3 rounded-sm border border-yellow-600" style={{ background: '#8B4513' }}>
                  <div className="w-1.5 h-px bg-yellow-600 mx-auto mt-1" />
                </div>
              </div>
            )
          })}

          {/* ME Interfaces (AE2) */}
          {meInterfaces.map((me, idx) => {
            const s = worldToScreen(me.x, me.z)
            if (s.x < -10 || s.x > MAP_SIZE + 10 || s.y < -10 || s.y > MAP_SIZE + 10) return null
            return (
              <div
                key={`me-${idx}`}
                className="absolute pointer-events-auto cursor-pointer"
                style={{ left: 0, top: 0, transform: `translate3d(${s.x - 7}px, ${s.y - 7}px, 0)` }}
                onClick={(e) => {
                  e.stopPropagation()
                  draggingRef.current = false
                  const off = getWrapperOffset(e)
                  setTooltip({
                    type: 'container',
                    data: { x: me.x, y: me.y, z: me.z, placed_by: 'AE2 ME Interface' },
                    screenX: off.x, screenY: off.y,
                  })
                }}
              >
                <div className="w-3.5 h-3.5 rounded-sm border border-purple-400 flex items-center justify-center" style={{ background: '#2a0a3a' }}>
                  <span className="text-[7px] font-bold text-purple-300">ME</span>
                </div>
              </div>
            )
          })}

          {/* Waypoints */}
          {dimWaypoints.map((wp) => {
            const s = worldToScreen(wp.x, wp.z)
            if (s.x < -10 || s.x > MAP_SIZE + 10 || s.y < -10 || s.y > MAP_SIZE + 10) return null
            return (
              <div
                key={`wp-${wp.name}`}
                className="absolute pointer-events-auto cursor-pointer flex flex-col items-center"
                style={{ left: 0, top: 0, transform: `translate3d(${s.x}px, ${s.y}px, 0) translate(-50%, -100%)` }}
                onClick={(e) => handleWaypointClick(e, wp)}
              >
                <span className="text-[8px] font-bold text-cyan-300 whitespace-nowrap" style={{ textShadow: '0 0 2px #000, 0 0 2px #000' }}>{wp.name}</span>
                <div className="w-0 h-0 border-l-[5px] border-r-[5px] border-t-[8px] border-l-transparent border-r-transparent border-t-cyan-300 opacity-90" />
                <div className="w-1 h-1 rounded-full bg-cyan-300 -mt-0.5" />
              </div>
            )
          })}

          {/* Pending waypoint */}
          {wpPending ? (() => {
            const s = worldToScreen(wpPending.x, wpPending.z)
            return (
              <div
                className="absolute flex flex-col items-center animate-pulse"
                style={{ left: 0, top: 0, transform: `translate3d(${s.x}px, ${s.y}px, 0) translate(-50%, -100%)` }}
              >
                <div className="w-0 h-0 border-l-[5px] border-r-[5px] border-t-[8px] border-l-transparent border-r-transparent border-t-cyan-300 opacity-60" style={{ borderStyle: 'dashed' }} />
                <div className="w-1 h-1 rounded-full bg-cyan-300 -mt-0.5 opacity-60" />
              </div>
            )
          })() : null}

          {/* Bots — with label deconfliction */}
          {(() => {
            const OVERLAP_PX = 18
            const positions = dimBots.map((bot) => {
              const bx = bot.status?.position?.x ?? 0
              const bz = bot.status?.position?.z ?? 0
              const s = worldToScreen(bx, bz)
              return {
                bot,
                sx: Math.max(14, Math.min(MAP_SIZE - 14, s.x)),
                sy: Math.max(14, Math.min(MAP_SIZE - 14, s.y)),
                offsetY: 0,
              }
            })
            for (let i = 0; i < positions.length; i++) {
              for (let j = i + 1; j < positions.length; j++) {
                const a = positions[i], b = positions[j]
                if (Math.abs(a.sx - b.sx) < OVERLAP_PX && Math.abs(a.sy + a.offsetY - (b.sy + b.offsetY)) < OVERLAP_PX) {
                  b.offsetY += OVERLAP_PX
                }
              }
            }
            return positions.map(({ bot, sx, sy, offsetY }) => {
              const isSel = bot.name === selectedBot
              const isMov = mode === 'move' && moveBot === bot.name
              return (
                <div
                  key={bot.name}
                  className="absolute pointer-events-auto cursor-pointer flex flex-col items-center"
                  style={{ left: 0, top: 0, transform: `translate3d(${sx}px, ${sy + offsetY}px, 0) translate(-50%, -50%)` }}
                  onClick={(e) => handleBotClick(e, bot)}
                >
                  <span
                    className="text-[9px] font-bold whitespace-nowrap mb-0.5"
                    style={{
                      color: isMov ? '#55ff55' : isSel ? '#e4a018' : '#fff',
                      textShadow: '0 0 2px #000, 0 0 2px #000',
                    }}
                  >
                    {bot.name}
                  </span>
                  <div className="relative">
                    {isSel && (
                      <div
                        className="absolute inset-0 rounded-full animate-ping"
                        style={{ border: '1.5px solid #e4a018', opacity: 0.4, margin: '-4px' }}
                      />
                    )}
                    {isMov && (
                      <div
                        className="absolute inset-0 rounded-full animate-ping"
                        style={{ border: '1.5px solid #55ff55', opacity: 0.4, margin: '-6px' }}
                      />
                    )}
                    <div
                      className="w-2.5 h-2.5 rounded-full"
                      style={{
                        background: isMov ? '#55ff55' : '#fff',
                        border: `1.5px solid ${isSel ? '#e4a018' : isMov ? '#55ff55' : '#000'}`,
                      }}
                    />
                  </div>
                </div>
              )
            })
          })()}

          {/* Player markers */}
          {dimPlayers.map((p) => {
            const s = worldToScreen(p.x, p.z)
            const sx = Math.max(14, Math.min(MAP_SIZE - 14, s.x))
            const sy = Math.max(14, Math.min(MAP_SIZE - 14, s.y))
            return (
              <div
                key={`player-${p.name}`}
                className="absolute pointer-events-auto cursor-pointer flex flex-col items-center"
                style={{ left: 0, top: 0, transform: `translate3d(${sx}px, ${sy}px, 0) translate(-50%, -50%)` }}
                onClick={(e) => {
                  e.stopPropagation()
                  setTooltip({
                    type: 'player',
                    screenX: sx, screenY: sy,
                    data: { name: p.name, x: p.x, y: p.y, z: p.z, health: p.health, gamemode: p.gamemode },
                  })
                }}
              >
                <span
                  className="text-[9px] font-bold whitespace-nowrap mb-0.5"
                  style={{ color: '#ff55ff', textShadow: '0 0 2px #000, 0 0 2px #000' }}
                >
                  {p.name}
                </span>
                <div
                  className="w-2.5 h-2.5 rounded-sm"
                  style={{ background: '#ff55ff', border: '1.5px solid #aa00aa' }}
                />
              </div>
            )
          })}
        </div>
      </div>

      {/* Tooltip */}
      {tooltip && (
        <div
          className="absolute z-50 bg-mc-panel border border-mc-accent rounded p-2 text-xs shadow-lg"
          style={{ left: Math.min(tooltip.screenX, 180), top: Math.min(tooltip.screenY, 280), maxWidth: 220 }}
          onClick={(e) => e.stopPropagation()}
        >
          {tooltip.type === 'bot' && (
            <div>
              <div className="text-mc-gold font-bold mb-1">{String(tooltip.data.name)}</div>
              <div className="grid grid-cols-2 gap-x-2 text-mc-gray">
                <span>HP: <span className="text-white">{Number(tooltip.data.health || 0).toFixed(0)}</span></span>
                <span>Food: <span className="text-white">{String(tooltip.data.food ?? 0)}</span></span>
                <span>XP: <span className="text-mc-green">{String(tooltip.data.xp ?? 0)}</span></span>
                <span className={tooltip.data.alive ? 'text-mc-green' : 'text-mc-red'}>
                  {tooltip.data.alive ? 'Alive' : 'Dead'}
                </span>
              </div>
              <div className="text-mc-aqua mt-1 truncate">{String(tooltip.data.plan || 'idle')}</div>
              <div className="flex gap-1 mt-2">
                <button onClick={() => { setMode('move'); setMoveBot(String(tooltip.data.name)); setTooltip(null) }}
                  className="text-[9px] px-1.5 py-0.5 rounded bg-mc-green text-black">Move</button>
                <button onClick={() => setTooltip(null)}
                  className="text-[9px] px-1.5 py-0.5 rounded bg-mc-accent text-mc-gray">Close</button>
              </div>
            </div>
          )}
          {tooltip.type === 'waypoint' && (
            <div>
              <div className="text-mc-aqua font-bold mb-1">{String(tooltip.data.name)}</div>
              <div className="text-mc-gray">{String(tooltip.data.x)}, {String(tooltip.data.y)}, {String(tooltip.data.z)}</div>
              {String(tooltip.data.set_by || '') ? <div className="text-mc-gray text-[9px]">by {String(tooltip.data.set_by)}</div> : null}
              <div className="flex gap-1 mt-2 flex-wrap">
                {selectedBot ? (
                  <>
                    <button onClick={() => { sendGoto(selectedBot, Number(tooltip.data.x), Number(tooltip.data.y), Number(tooltip.data.z)); setTooltip(null) }}
                      className="text-[9px] px-1.5 py-0.5 rounded bg-mc-green text-black">Send {selectedBot}</button>
                    <button onClick={() => { sendTeleport(selectedBot, Number(tooltip.data.x), Number(tooltip.data.y), Number(tooltip.data.z), currentDim); setTooltip(null) }}
                      className="text-[9px] px-1.5 py-0.5 rounded bg-mc-purple text-white">TP {selectedBot}</button>
                  </>
                ) : null}
                <button onClick={() => { deleteWaypoint(String(tooltip.data.name)).then(() => refreshWaypoints()); setTooltip(null) }}
                  className="text-[9px] px-1.5 py-0.5 rounded bg-mc-red text-white">Delete</button>
                <button onClick={() => setTooltip(null)} className="text-[9px] px-1.5 py-0.5 rounded bg-mc-accent text-mc-gray">Close</button>
              </div>
            </div>
          )}
          {tooltip.type === 'player' && (
            <div>
              <div className="font-bold mb-1" style={{ color: '#ff55ff' }}>{String(tooltip.data.name)}</div>
              <div className="grid grid-cols-2 gap-x-2 text-mc-gray">
                <span>HP: <span className="text-white">{Number(tooltip.data.health || 0).toFixed(0)}</span></span>
                <span>Mode: <span className="text-white">{String(tooltip.data.gamemode)}</span></span>
              </div>
              <div className="text-mc-gray mt-0.5">
                {Math.round(Number(tooltip.data.x))}, {Math.round(Number(tooltip.data.y))}, {Math.round(Number(tooltip.data.z))}
              </div>
              <div className="flex gap-1 mt-2 flex-wrap">
                {selectedBot ? (
                  <>
                    <button onClick={() => { sendGoto(selectedBot, Number(tooltip.data.x), Number(tooltip.data.y), Number(tooltip.data.z)); setTooltip(null) }}
                      className="text-[9px] px-1.5 py-0.5 rounded bg-mc-green text-black">Send {selectedBot}</button>
                    <button onClick={() => { sendTeleport(selectedBot, Number(tooltip.data.x), Number(tooltip.data.y), Number(tooltip.data.z), currentDim); setTooltip(null) }}
                      className="text-[9px] px-1.5 py-0.5 rounded bg-mc-purple text-white">TP {selectedBot}</button>
                  </>
                ) : null}
                <button onClick={() => setTooltip(null)} className="text-[9px] px-1.5 py-0.5 rounded bg-mc-accent text-mc-gray">Close</button>
              </div>
            </div>
          )}
          {tooltip.type === 'container' && (
            <div>
              <div className="text-yellow-400 font-bold mb-1">Container</div>
              <div className="text-mc-gray">{String(tooltip.data.x)}, {String(tooltip.data.y)}, {String(tooltip.data.z)}</div>
              {String(tooltip.data.placed_by || '') ? <div className="text-mc-gray text-[9px]">by {String(tooltip.data.placed_by)}</div> : null}
              <div className="flex gap-1 mt-2">
                {selectedBot ? (
                  <button onClick={() => { sendGoto(selectedBot, Number(tooltip.data.x), Number(tooltip.data.y), Number(tooltip.data.z)); setTooltip(null) }}
                    className="text-[9px] px-1.5 py-0.5 rounded bg-mc-green text-black">Go to</button>
                ) : null}
                <button onClick={() => setTooltip(null)} className="text-[9px] px-1.5 py-0.5 rounded bg-mc-accent text-mc-gray">Close</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Container panel */}
      {containerPanel && (
        <div className="mt-2 bg-mc-dark border border-mc-accent rounded p-2 text-xs">
          <div className="flex items-center justify-between mb-1">
            <span className="text-yellow-400 font-bold">
              Container @ {containerPanel.container.x}, {containerPanel.container.y}, {containerPanel.container.z}
            </span>
            <button onClick={() => { setContainerPanel(null); setStorePickerOpen(false) }}
              className="text-mc-gray hover:text-white text-[10px]">Close</button>
          </div>
          {containerPanel.loading ? (
            <div className="text-mc-gray">Loading...</div>
          ) : containerPanel.contents.length === 0 ? (
            <div className="text-mc-gray">Empty or unreachable</div>
          ) : (
            <div className="grid grid-cols-2 gap-1 max-h-32 overflow-y-auto">
              {containerPanel.contents.map((slot, i) => (
                <div key={i} className="flex justify-between items-center bg-mc-panel rounded px-1 py-0.5">
                  <span className="text-white truncate">{(slot.item || '').replace('minecraft:', '')}</span>
                  <span className="text-mc-gray ml-1">x{slot.count}</span>
                  {selectedBot ? (
                    <button onClick={() => {
                      const c = containerPanel.container
                      fetch('/api/directive', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ bot: selectedBot, directive_type: 'CONTAINER_WITHDRAW', target: slot.item, x: c.x, y: c.y, z: c.z, count: slot.count }) })
                    }} className="text-[8px] px-1 py-0 rounded bg-mc-accent text-mc-aqua hover:text-white ml-1 shrink-0">Take</button>
                  ) : null}
                </div>
              ))}
            </div>
          )}
          {selectedBot && (
            <div className="mt-2">
              <div className="flex gap-1 mb-1 flex-wrap">
                <button onClick={() => sendGoto(selectedBot, containerPanel.container.x, containerPanel.container.y, containerPanel.container.z)}
                  className="text-[9px] px-2 py-0.5 rounded bg-mc-green text-black">Send {selectedBot}</button>
                <button onClick={() => {
                  const c = containerPanel.container
                  fetch('/api/directive', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bot: selectedBot, directive_type: 'STORE_ALL', x: c.x, y: c.y, z: c.z }) })
                }} className="text-[9px] px-2 py-0.5 rounded bg-purple-600 text-white">Store All</button>
                <button onClick={() => setStorePickerOpen(!storePickerOpen)}
                  className={`text-[9px] px-2 py-0.5 rounded ${storePickerOpen ? 'bg-mc-gold text-black' : 'bg-yellow-600 text-black'}`}>
                  {storePickerOpen ? 'Cancel' : 'Store items...'}</button>
              </div>
              {storePickerOpen && (
                <div className="bg-mc-panel rounded p-1 mt-1">
                  <div className="text-[9px] text-mc-gray mb-1">{selectedBot}&apos;s inventory — tap to store:</div>
                  {inv.length === 0 ? (
                    <div className="text-[9px] text-mc-gray">Empty inventory</div>
                  ) : (
                    <div className="grid grid-cols-2 gap-1 max-h-28 overflow-y-auto">
                      {inv.map((item, i) => (
                        <button key={i} onClick={() => {
                          const c = containerPanel.container
                          fetch('/api/directive', { method: 'POST', headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ bot: selectedBot, directive_type: 'CONTAINER_STORE', target: item.item, x: c.x, y: c.y, z: c.z, count: item.count }) })
                        }} className="flex justify-between items-center bg-mc-dark rounded px-1 py-0.5 text-[9px] hover:bg-mc-accent">
                          <span className="text-white truncate">{(item.display_name || item.item || '').replace('minecraft:', '')}</span>
                          <span className="text-mc-gray ml-1">x{item.count}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default function WorldMap(props: {
  bots: BotSnapshot[]
  selectedBot: string | null
  onSelect: (name: string) => void
  onCenterBot?: string | null
}) {
  return (
    <MapErrorBoundary>
      <WorldMapInner {...props} />
    </MapErrorBoundary>
  )
}
