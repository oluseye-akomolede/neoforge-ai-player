import { useCallback, useEffect, useState } from 'react'

interface HiveStatus {
  roles_registered: number
  drones_active: number
  catalog_size: number
  pois_known: number
  messages_open: number
}

interface HivePlanSummary {
  domain: string
  conversation_id: string
  task: string
  status: string
  subtask_count: number
  current_subtask_id: number
  current_subtask_desc: string
  current_attempts: number
  complete_count: number
}

interface HivePlansResponse {
  plans: HivePlanSummary[]
}

interface HiveSubtask {
  id: number
  description: string
  criteria: string
  specialist_role: string
  status: string
  attempts: number
  replans: number
  held_since: string | null
  error: string | null
  orders_issued?: string[]
  drone_reports?: unknown[]
}

interface HiveFullPlan {
  domain: string
  conversation_id: string
  task: string
  status: string
  current_subtask_id: number
  subtasks: HiveSubtask[]
}

interface HiveDrone {
  id: string
  role: string
  state: string
  spawned_at: string
  last_seen: string
}

const POLL_INTERVAL_MS = 4000

function statusBadge(s: string): string {
  switch (s) {
    case 'complete': return 'bg-green-900/40 border-green-600/40 text-mc-green'
    case 'executing': return 'bg-cyan-900/40 border-cyan-600/40 text-mc-aqua'
    case 'pending':   return 'bg-yellow-900/40 border-yellow-600/40 text-yellow-400'
    case 'failed':    return 'bg-red-900/40 border-red-600/40 text-mc-red'
    default:          return 'bg-mc-accent border-mc-accent text-mc-gray'
  }
}

function subtaskIcon(status: string, held: boolean): { ch: string; cls: string } {
  if (held) return { ch: '⏸', cls: 'text-orange-400' }
  switch (status) {
    case 'complete': return { ch: '✓', cls: 'text-mc-green' }
    case 'executing': return { ch: '⟳', cls: 'text-mc-aqua animate-pulse' }
    case 'failed': return { ch: '✗', cls: 'text-mc-red' }
    default: return { ch: '·', cls: 'text-mc-gray' }
  }
}

function fmtHeldSince(iso: string): string {
  try {
    const then = new Date(iso).getTime()
    const now = Date.now()
    const sec = Math.max(0, Math.round((now - then) / 1000))
    if (sec < 60) return `${sec}s ago`
    if (sec < 3600) return `${Math.round(sec / 60)}m ago`
    return `${Math.round(sec / 3600)}h ago`
  } catch { return iso }
}

export default function HivePanel() {
  const [status, setStatus] = useState<HiveStatus | null>(null)
  const [plans, setPlans] = useState<HivePlanSummary[]>([])
  const [details, setDetails] = useState<Record<string, HiveFullPlan>>({})
  const [drones, setDrones] = useState<HiveDrone[]>([])
  const [error, setError] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    try {
      const sr = await fetch('/api/hive/status')
      if (sr.ok) setStatus(await sr.json())

      const pr = await fetch('/api/hive/plans')
      if (pr.ok) {
        const data: HivePlansResponse = await pr.json()
        const newPlans = data.plans || []
        setPlans(newPlans)
        // Fetch full details per plan in parallel for inline display
        const fetched: Record<string, HiveFullPlan> = {}
        await Promise.all(
          newPlans.map(async (p) => {
            try {
              const dr = await fetch(`/api/hive/plans/${encodeURIComponent(p.domain)}/${encodeURIComponent(p.conversation_id)}`)
              if (dr.ok) fetched[p.conversation_id] = await dr.json()
            } catch { /* skip */ }
          })
        )
        setDetails(fetched)
      }

      const dr = await fetch('/api/hive/drones')
      if (dr.ok) {
        const data = await dr.json()
        setDrones(data.drones || [])
      }
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'hive fetch failed')
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const id = window.setInterval(fetchAll, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [fetchAll])

  const heldCount = Object.values(details)
    .flatMap((p) => p.subtasks)
    .filter((s) => s.held_since).length

  return (
    <div className="bg-mc-accent/60 border border-mc-border/60 rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-mc-aqua text-sm font-semibold">🐝 Hive</h3>
        <span className="text-xs text-mc-gray">
          {status ? `${status.drones_active} drones` : '—'}
          {heldCount > 0 && <span className="text-orange-400 ml-2">{heldCount} held</span>}
        </span>
      </div>
      {error && <div className="text-xs text-mc-red">⚠ {error}</div>}

      {status && (
        <div className="grid grid-cols-2 gap-1 text-[10px]">
          <div className="text-mc-gray">Roles <span className="text-mc-white font-mono">{status.roles_registered}</span></div>
          <div className="text-mc-gray">Drones <span className="text-mc-white font-mono">{status.drones_active}</span></div>
          <div className="text-mc-gray">Catalog <span className="text-mc-white font-mono">{status.catalog_size}</span></div>
          <div className="text-mc-gray">POIs <span className="text-mc-white font-mono">{status.pois_known}</span></div>
          <div className="text-mc-gray col-span-2">Open msgs <span className="text-mc-white font-mono">{status.messages_open}</span></div>
        </div>
      )}

      {drones.length > 0 && (
        <div>
          <div className="text-[10px] text-mc-gray uppercase tracking-wide mt-2">Active drones</div>
          <div className="space-y-0.5">
            {drones.slice(0, 8).map((d) => (
              <div key={d.id} className="text-[10px] flex items-center justify-between gap-1 bg-mc-bg/30 px-1.5 py-0.5 rounded">
                <span className="text-mc-white truncate">{d.role}</span>
                <span className="text-mc-gray font-mono text-[9px]">{d.id.slice(0, 8)}</span>
              </div>
            ))}
            {drones.length > 8 && (
              <div className="text-[10px] text-mc-gray italic">+ {drones.length - 8} more</div>
            )}
          </div>
        </div>
      )}

      {plans.length > 0 && (
        <div>
          <div className="text-[10px] text-mc-gray uppercase tracking-wide mt-2">Lieutenant plans</div>
          <div className="space-y-2">
            {plans.map((p) => {
              const pct = p.subtask_count > 0
                ? Math.round((p.complete_count / p.subtask_count) * 100)
                : 0
              const detail = details[p.conversation_id]
              return (
                <div key={p.conversation_id} className="bg-mc-bg/40 border border-mc-border/40 rounded p-1.5 space-y-1">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-mc-aqua text-[11px] font-semibold truncate">{p.domain}</span>
                    <span className={`px-1 py-0.5 border rounded text-[9px] uppercase ${statusBadge(p.status)}`}>
                      {p.status}
                    </span>
                  </div>
                  <div className="text-[10px] text-mc-gray italic truncate" title={p.task}>"{p.task}"</div>
                  <div className="flex items-center gap-1">
                    <div className="flex-1 h-1 bg-mc-bg rounded overflow-hidden">
                      <div className="h-full bg-mc-aqua/70" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-[9px] text-mc-gray font-mono">{p.complete_count}/{p.subtask_count}</span>
                  </div>

                  {/* Full subtask list */}
                  {detail && detail.subtasks.length > 0 && (
                    <div className="border-l border-mc-border/40 pl-1.5 space-y-0.5 mt-1">
                      {detail.subtasks.map((s) => {
                        const isHeld = s.status === 'pending' && !!s.held_since
                        const icon = subtaskIcon(s.status, isHeld)
                        const isCurrent = s.id === detail.current_subtask_id && s.status !== 'complete'
                        return (
                          <div key={s.id} className={`text-[10px] ${isCurrent ? 'bg-cyan-950/40 -mx-0.5 px-0.5 py-0.5 rounded' : ''}`}>
                            <div className="flex items-start gap-1">
                              <span className={`inline-block w-3 ${icon.cls} font-mono`}>{icon.ch}</span>
                              <div className="flex-1 min-w-0">
                                <div className="text-mc-white">
                                  <span className="text-mc-gray font-mono">{s.id}.</span> {s.description}
                                  {isHeld && (
                                    <span className="ml-1 text-orange-400 text-[9px] uppercase">[held {fmtHeldSince(s.held_since!)}]</span>
                                  )}
                                  {s.attempts > 0 && (
                                    <span className="text-yellow-400 ml-1 text-[9px]">[{s.attempts}/3]</span>
                                  )}
                                  {s.replans > 0 && (
                                    <span className="text-orange-400 ml-1 text-[9px]">↻{s.replans}</span>
                                  )}
                                </div>
                                <div className="text-[9px] text-mc-gray pl-1">
                                  <span className="text-mc-aqua">{s.specialist_role}</span>
                                  {s.criteria && <span className="text-mc-gray/70 italic"> · {s.criteria}</span>}
                                </div>
                                {s.error && (
                                  <div className="text-[9px] text-mc-red pl-1" title={s.error}>
                                    {s.error.slice(0, 100)}
                                  </div>
                                )}
                              </div>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {!status && !error && (
        <div className="text-[10px] text-mc-gray italic">hive-service unreachable or not configured</div>
      )}
    </div>
  )
}
