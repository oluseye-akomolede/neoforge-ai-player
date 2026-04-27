import { useState, useEffect, useCallback } from 'react'
import { fetchBotMemories, fetchContainerContents, type MemoryEntry } from '../hooks'

type Tab = 'memories' | 'tasks' | 'transmute' | 'containers' | 'waypoints'

export default function DataBrowser({ selectedBot }: { selectedBot: string | null }) {
  const [tab, setTab] = useState<Tab>('memories')
  const [data, setData] = useState<unknown>(null)
  const [memoryStats, setMemoryStats] = useState<Record<string, number>>({})
  const [memoryCategory, setMemoryCategory] = useState('all')
  const [loading, setLoading] = useState(false)
  const [expandedContainer, setExpandedContainer] = useState<number | null>(null)
  const [containerContents, setContainerContents] = useState<Record<string, unknown>[]>([])
  const [containerLoading, setContainerLoading] = useState(false)

  const fetchTab = async (t: Tab) => {
    setLoading(true)
    try {
      if (t === 'memories') {
        if (!selectedBot) {
          setData([])
          setLoading(false)
          return
        }
        const res = await fetchBotMemories(selectedBot, memoryCategory)
        setData(res.memories || [])
        if (res.stats?.categories) setMemoryStats(res.stats.categories)
      } else {
        const res = await fetch(`/api/${t}`)
        const json = await res.json()
        setData(json.tasks || json.items || json.containers || json.waypoints || json)
      }
    } catch {
      setData(null)
    }
    setLoading(false)
  }

  useEffect(() => {
    fetchTab(tab)
  }, [tab, selectedBot, memoryCategory])

  const tabs: { key: Tab; label: string }[] = [
    { key: 'memories', label: 'Memories' },
    { key: 'tasks', label: 'Tasks' },
    { key: 'transmute', label: 'Transmute' },
    { key: 'containers', label: 'Containers' },
    { key: 'waypoints', label: 'Waypoints' },
  ]

  const deleteMemory = useCallback(async (id: number) => {
    if (!selectedBot) return
    try {
      await fetch(`/api/bots/${selectedBot}/memories/${id}`, { method: 'DELETE' })
      setData((prev: unknown) => {
        if (!Array.isArray(prev)) return prev
        return (prev as MemoryEntry[]).filter((m) => m.id !== id)
      })
    } catch { /* ignore */ }
  }, [selectedBot])

  const renderMemories = () => {
    if (!selectedBot) return <p className="text-xs text-mc-gray">Select a bot to view memories</p>
    const memories = (data as MemoryEntry[]) || []

    return (
      <div>
        {/* Category filter */}
        {Object.keys(memoryStats).length > 0 && (
          <div className="flex flex-wrap gap-1 mb-2">
            <button
              onClick={() => setMemoryCategory('all')}
              className={`text-[10px] px-1.5 py-0.5 rounded ${
                memoryCategory === 'all' ? 'bg-mc-gold text-black' : 'bg-mc-accent text-mc-gray'
              }`}
            >
              all ({Object.values(memoryStats).reduce((a, b) => a + b, 0)})
            </button>
            {Object.entries(memoryStats).map(([cat, count]) => (
              <button
                key={cat}
                onClick={() => setMemoryCategory(cat)}
                className={`text-[10px] px-1.5 py-0.5 rounded ${
                  memoryCategory === cat ? 'bg-mc-gold text-black' : 'bg-mc-accent text-mc-gray'
                }`}
              >
                {cat} ({count})
              </button>
            ))}
          </div>
        )}

        {memories.length === 0 ? (
          <p className="text-xs text-mc-gray">No memories</p>
        ) : (
          <div className="max-h-64 overflow-y-auto space-y-1">
            {[...memories]
              .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
              .map((m) => {
                const score = m.decay_score ?? 1
                const scorePct = Math.round(score * 100)
                const scoreColor = scorePct >= 90 ? 'text-mc-green' : scorePct >= 70 ? 'text-yellow-400' : scorePct >= 50 ? 'text-orange-400' : 'text-mc-red'
                return (
                  <div key={m.id} className="text-xs bg-mc-dark rounded px-2 py-1.5 group">
                    <div className="flex justify-between items-start mb-0.5">
                      <span className="text-mc-gold text-[10px]">{m.category}</span>
                      <div className="flex gap-2 items-center">
                        <span className={`text-[10px] ${scoreColor}`} title={`Decay score: ${scorePct}% · Accessed ${m.access_count ?? 0}x`}>
                          {scorePct}%
                        </span>
                        <span className="text-mc-gray text-[10px]">
                          {new Date(m.created_at).toLocaleDateString()}
                        </span>
                        <button
                          onClick={() => deleteMemory(m.id)}
                          className="text-[10px] text-mc-red/40 hover:text-mc-red opacity-0 group-hover:opacity-100 transition-opacity"
                          title="Delete memory"
                        >
                          ✕
                        </button>
                      </div>
                    </div>
                    <p className="text-mc-gray leading-tight">{m.content}</p>
                  </div>
                )
              })}
          </div>
        )}
      </div>
    )
  }

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const f = (obj: any, key: string): string => String(obj?.[key] ?? '')

  const renderGeneric = () => {
    if (loading) return <p className="text-xs text-mc-gray">Loading...</p>

    if (Array.isArray(data)) {
      if ((data as unknown[]).length === 0) return <p className="text-xs text-mc-gray">None</p>
      const sorted = [...(data as Record<string, unknown>[])].sort((a, b) => {
        const dateA = a.created_at ?? a.discovered_tick ?? a.id ?? 0
        const dateB = b.created_at ?? b.discovered_tick ?? b.id ?? 0
        if (typeof dateA === 'string' && typeof dateB === 'string') return dateB.localeCompare(dateA)
        return Number(dateB) - Number(dateA)
      })
      return (
        <div className="max-h-64 overflow-y-auto space-y-1">
          {sorted.map((item, i) => (
            <div key={i} className="text-xs bg-mc-dark rounded px-2 py-1">
              {tab === 'tasks' && typeof item === 'object' ? (
                <div>
                  <div className="flex justify-between">
                    <span className="text-mc-gold">#{f(item, 'id')}</span>
                    <span className={`text-[10px] ${
                      f(item, 'status') === 'pending' ? 'text-yellow-400' :
                      f(item, 'status') === 'in_progress' ? 'text-mc-aqua' :
                      'text-mc-green'
                    }`}>{f(item, 'status')}</span>
                  </div>
                  <p className="text-mc-gray truncate">{f(item, 'description')}</p>
                  {f(item, 'assigned_to') && (
                    <span className="text-[10px] text-mc-gray">assigned: {f(item, 'assigned_to')}</span>
                  )}
                </div>
              ) : tab === 'transmute' && typeof item === 'object' ? (
                <div className="flex justify-between">
                  <span className="text-mc-gray">{f(item, 'item_id').replace('minecraft:', '')}</span>
                  <span className="text-mc-green">{f(item, 'xp_cost')} XP</span>
                </div>
              ) : tab === 'containers' && typeof item === 'object' ? (
                <div>
                  <button
                    className="w-full flex justify-between items-center hover:bg-mc-accent rounded px-1 py-0.5 -mx-1"
                    onClick={async () => {
                      const id = Number(f(item, 'id'))
                      if (expandedContainer === id) {
                        setExpandedContainer(null)
                        setContainerContents([])
                        return
                      }
                      setExpandedContainer(id)
                      setContainerLoading(true)
                      setContainerContents([])
                      try {
                        const res = await fetchContainerContents(
                          Number(f(item, 'x')), Number(f(item, 'y')), Number(f(item, 'z'))
                        )
                        setContainerContents(res.items || [])
                      } catch {
                        setContainerContents([])
                      }
                      setContainerLoading(false)
                    }}
                  >
                    <span className="text-mc-gold">#{f(item, 'id')}</span>
                    <span className="text-mc-gray">
                      {f(item, 'x')}, {f(item, 'y')}, {f(item, 'z')}
                    </span>
                    <span className="text-[10px] text-mc-gray">{f(item, 'dimension').replace('minecraft:', '')}</span>
                    <span className="text-[10px] text-mc-gray">{expandedContainer === Number(f(item, 'id')) ? '▼' : '▶'}</span>
                  </button>
                  {expandedContainer === Number(f(item, 'id')) && (
                    <div className="mt-1 ml-2 border-l border-mc-accent pl-2">
                      {containerLoading ? (
                        <span className="text-[10px] text-mc-gold animate-pulse">Loading...</span>
                      ) : containerContents.length === 0 ? (
                        <span className="text-[10px] text-mc-gray">Empty or unreachable</span>
                      ) : (
                        <div className="space-y-0.5">
                          {containerContents.map((slot, si) => (
                            <div key={si} className="flex justify-between text-[10px]">
                              <span className="text-white truncate">
                                {String(slot.name || slot.item || '').replace('minecraft:', '')}
                              </span>
                              <span className="text-mc-gray ml-2 shrink-0">x{String(slot.count)}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ) : (
                <pre className="whitespace-pre-wrap text-mc-gray">
                  {JSON.stringify(item, null, 1)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )
    }

    if (typeof data === 'object' && data !== null) {
      const entries = Object.entries(data as Record<string, unknown>)
      if (entries.length === 0) return <p className="text-xs text-mc-gray">None</p>
      return (
        <div className="max-h-64 overflow-y-auto space-y-1">
          {entries.map(([key, val]) => (
            <div key={key} className="text-xs bg-mc-dark rounded px-2 py-1 flex justify-between">
              <span className="text-mc-gold">{key}</span>
              <span className="text-mc-gray">
                {typeof val === 'object' ? JSON.stringify(val) : String(val)}
              </span>
            </div>
          ))}
        </div>
      )
    }

    return <p className="text-xs text-mc-gray">No data</p>
  }

  return (
    <div className="panel">
      <div className="flex gap-1 mb-3 flex-wrap">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`text-xs px-2 py-1 rounded transition-colors ${
              tab === t.key
                ? 'bg-mc-gold text-black font-medium'
                : 'bg-mc-accent text-white hover:bg-blue-700'
            }`}
          >
            {t.label}
          </button>
        ))}
        <button
          onClick={() => fetchTab(tab)}
          className="text-xs px-2 py-1 rounded bg-mc-accent text-white hover:bg-blue-700 ml-auto"
        >
          Refresh
        </button>
      </div>
      {tab === 'memories' ? renderMemories() : renderGeneric()}
    </div>
  )
}
