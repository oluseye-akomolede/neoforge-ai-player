import { useEffect, useRef, useState, useCallback } from 'react'
import type { ServerState, DashEvent, DirectiveDef, Waypoint } from './types'

function wsUrl(path: string): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}${path}`
}

export function useServerState(): ServerState | null {
  const [state, setState] = useState<ServerState | null>(null)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let alive = true
    function connect() {
      const ws = new WebSocket(wsUrl('/ws'))
      wsRef.current = ws
      ws.onmessage = (e) => {
        if (alive) setState(JSON.parse(e.data))
      }
      ws.onclose = () => {
        if (alive) setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
    }
    connect()
    return () => {
      alive = false
      wsRef.current?.close()
    }
  }, [])

  return state
}

export function useEvents(): DashEvent[] {
  const [events, setEvents] = useState<DashEvent[]>([])
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    let alive = true
    function connect() {
      const ws = new WebSocket(wsUrl('/ws/events'))
      wsRef.current = ws
      ws.onmessage = (e) => {
        if (!alive) return
        const data = JSON.parse(e.data)
        if (data.events) {
          setEvents((prev) => [...prev, ...data.events].slice(-200))
        }
      }
      ws.onclose = () => {
        if (alive) setTimeout(connect, 2000)
      }
      ws.onerror = () => ws.close()
    }
    connect()
    return () => {
      alive = false
      wsRef.current?.close()
    }
  }, [])

  return events
}

export function useDirectives(): DirectiveDef[] {
  const [directives, setDirectives] = useState<DirectiveDef[]>([])
  useEffect(() => {
    fetch('/api/directives')
      .then((r) => r.json())
      .then((d) => setDirectives(d.directives || []))
      .catch(() => {})
  }, [])
  return directives
}

export function useSendCommand() {
  return useCallback(async (bot: string, message: string) => {
    const res = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bot, message }),
    })
    return res.json()
  }, [])
}

export function useSendDirective() {
  return useCallback(async (req: Record<string, unknown>) => {
    const res = await fetch('/api/directive', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    })
    return res.json()
  }, [])
}

export function useStopBot() {
  return useCallback(async (bot: string) => {
    const res = await fetch(`/api/bots/${bot}/stop`, { method: 'POST' })
    return res.json()
  }, [])
}

export function useBroadcast() {
  return useCallback(async (message: string) => {
    const res = await fetch('/api/broadcast', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })
    return res.json()
  }, [])
}

export interface TransmuteItem {
  item_id: string
  xp_cost: number
}

export function useTransmuteItems(): TransmuteItem[] {
  const [items, setItems] = useState<TransmuteItem[]>([])
  useEffect(() => {
    const poll = () =>
      fetch('/api/transmute')
        .then((r) => r.json())
        .then((d) => setItems(d.items || []))
        .catch(() => {})
    poll()
    const id = setInterval(poll, 30_000)
    return () => clearInterval(id)
  }, [])
  return items
}

export interface ContainerInfo {
  id: number
  x: number
  y: number
  z: number
  dimension: string
  placed_by: string
}

export function useContainers(): ContainerInfo[] {
  const [containers, setContainers] = useState<ContainerInfo[]>([])
  useEffect(() => {
    const poll = () =>
      fetch('/api/containers')
        .then((r) => r.json())
        .then((d) => setContainers(d.containers || []))
        .catch(() => {})
    poll()
    const id = setInterval(poll, 30_000)
    return () => clearInterval(id)
  }, [])
  return containers
}

export async function fetchContainerContents(x: number, y: number, z: number) {
  const res = await fetch(`/api/containers/${x}/${y}/${z}/contents`)
  return res.json()
}

export interface MemoryEntry {
  id: number
  content: string
  category: string
  metadata: Record<string, unknown> | null
  created_at: string
  last_accessed: string | null
  access_count: number
  decay_score: number
}

export async function fetchBotMemories(bot: string, category = 'all') {
  const res = await fetch(`/api/bots/${bot}/memories?category=${category}&limit=50`)
  return res.json()
}

export function useWaypoints(): [Waypoint[], () => void] {
  const [wps, setWps] = useState<Waypoint[]>([])
  const load = useCallback(() => {
    fetch('/api/waypoints')
      .then((r) => r.json())
      .then((d) => setWps(d.waypoints || []))
      .catch(() => {})
  }, [])
  useEffect(() => { load() }, [load])
  return [wps, load]
}

export async function createWaypoint(name: string, x: number, y: number, z: number, dimension: string) {
  const res = await fetch('/api/waypoints', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, x, y, z, dimension }),
  })
  return res.json()
}

export async function deleteWaypoint(name: string) {
  const res = await fetch('/api/waypoints', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  })
  return res.json()
}

export function useDimensions(): string[] {
  const [dims, setDims] = useState<string[]>([])
  useEffect(() => {
    fetch('/api/dimensions')
      .then((r) => r.json())
      .then((d) => setDims(d.dimensions || []))
      .catch(() => {})
  }, [])
  return dims
}

export async function sendGoto(bot: string, x: number, y: number, z: number) {
  const res = await fetch('/api/directive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bot, directive_type: 'GOTO', x, y, z }),
  })
  return res.json()
}

export async function sendTeleport(bot: string, x: number, y: number, z: number, dimension?: string) {
  const res = await fetch('/api/directive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      bot, directive_type: 'TELEPORT', x, y, z,
      ...(dimension ? { extra: { dimension } } : {}),
    }),
  })
  return res.json()
}
