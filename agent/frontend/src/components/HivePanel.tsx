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

interface HiveDrone {
  id: string
  role: string
  state: string
  spawned_at: string
  last_seen: string
}

const POLL_INTERVAL_MS = 5000

function statusBadge(s: string): string {
  switch (s) {
    case 'complete': return 'bg-green-900/40 border-green-600/40 text-mc-green'
    case 'executing': return 'bg-cyan-900/40 border-cyan-600/40 text-mc-aqua'
    case 'pending':   return 'bg-yellow-900/40 border-yellow-600/40 text-yellow-400'
    case 'failed':    return 'bg-red-900/40 border-red-600/40 text-mc-red'
    default:          return 'bg-mc-accent border-mc-accent text-mc-gray'
  }
}

export default function HivePanel() {
  const [status, setStatus] = useState<HiveStatus | null>(null)
  const [plans, setPlans] = useState<HivePlanSummary[]>([])
  const [drones, setDrones] = useState<HiveDrone[]>([])
  const [error, setError] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    try {
      // Status
      const sr = await fetch('/api/hive/status')
      if (sr.ok) {
        setStatus(await sr.json())
      } else if (sr.status !== 404) {
        // 404 just means the proxy hasn't been wired yet — silent
        throw new Error(`status HTTP ${sr.status}`)
      }
      // Plans
      const pr = await fetch('/api/hive/plans')
      if (pr.ok) {
        const data: HivePlansResponse = await pr.json()
        setPlans(data.plans || [])
      }
      // Drones
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

  return (
    <div className="bg-mc-accent/60 border border-mc-border/60 rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-mc-aqua text-sm font-semibold">🐝 Hive</h3>
        <span className="text-xs text-mc-gray">
          {status ? `${status.drones_active} drones` : '—'}
        </span>
      </div>
      {error && <div className="text-xs text-mc-red">⚠ {error}</div>}

      {/* Status counters */}
      {status && (
        <div className="grid grid-cols-2 gap-1 text-[10px]">
          <div className="text-mc-gray">Roles <span className="text-mc-white font-mono">{status.roles_registered}</span></div>
          <div className="text-mc-gray">Drones <span className="text-mc-white font-mono">{status.drones_active}</span></div>
          <div className="text-mc-gray">Catalog <span className="text-mc-white font-mono">{status.catalog_size}</span></div>
          <div className="text-mc-gray">POIs <span className="text-mc-white font-mono">{status.pois_known}</span></div>
          <div className="text-mc-gray col-span-2">Open msgs <span className="text-mc-white font-mono">{status.messages_open}</span></div>
        </div>
      )}

      {/* Active drones */}
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

      {/* Lieutenant plans */}
      {plans.length > 0 && (
        <div>
          <div className="text-[10px] text-mc-gray uppercase tracking-wide mt-2">Lieutenant plans</div>
          <div className="space-y-1">
            {plans.map((p) => {
              const pct = p.subtask_count > 0
                ? Math.round((p.complete_count / p.subtask_count) * 100)
                : 0
              return (
                <div key={p.conversation_id} className="bg-mc-bg/40 border border-mc-border/40 rounded p-1.5">
                  <div className="flex items-center justify-between gap-1">
                    <span className="text-mc-aqua text-[11px] font-semibold truncate">{p.domain}</span>
                    <span className={`px-1 py-0.5 border rounded text-[9px] uppercase ${statusBadge(p.status)}`}>
                      {p.status}
                    </span>
                  </div>
                  <div className="text-[10px] text-mc-gray italic truncate">"{p.task}"</div>
                  <div className="flex items-center gap-1 mt-0.5">
                    <div className="flex-1 h-1 bg-mc-bg rounded overflow-hidden">
                      <div className="h-full bg-mc-aqua/70" style={{ width: `${pct}%` }} />
                    </div>
                    <span className="text-[9px] text-mc-gray font-mono">{p.complete_count}/{p.subtask_count}</span>
                  </div>
                  <div className="text-[10px] text-mc-gray mt-0.5 truncate">
                    {p.current_subtask_id}. {p.current_subtask_desc}
                    {p.current_attempts > 0 && (
                      <span className="text-yellow-400"> [try {p.current_attempts + 1}]</span>
                    )}
                  </div>
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
