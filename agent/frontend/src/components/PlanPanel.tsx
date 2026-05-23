import { useCallback, useEffect, useState } from 'react'

interface PlanSummary {
  bot: string
  task: string
  status: string
  subtask_count: number
  current_subtask_id: number
  current_subtask_desc: string
  current_attempts: number
  complete_count: number
}

interface PlansResponse {
  plans: PlanSummary[]
}

interface FullSubtask {
  id: number
  description: string
  criteria: string
  status: string
  attempts: number
  replans: number
  error: string | null
  directives?: unknown[]
}

interface FullPlan {
  bot: string
  task: string
  status: string
  current_subtask_id: number
  created_at: string
  subtasks: FullSubtask[]
}

function statusBadge(s: string): string {
  switch (s) {
    case 'complete': return 'bg-green-900/40 border-green-600/40 text-mc-green'
    case 'executing': return 'bg-cyan-900/40 border-cyan-600/40 text-mc-aqua'
    case 'pending': return 'bg-yellow-900/40 border-yellow-600/40 text-yellow-400'
    case 'failed': return 'bg-red-900/40 border-red-600/40 text-mc-red'
    default: return 'bg-mc-accent border-mc-accent text-mc-gray'
  }
}

function subtaskIcon(status: string): { ch: string; cls: string } {
  switch (status) {
    case 'complete': return { ch: '✓', cls: 'text-mc-green' }
    case 'executing': return { ch: '⟳', cls: 'text-mc-aqua animate-pulse' }
    case 'failed': return { ch: '✗', cls: 'text-mc-red' }
    default: return { ch: '·', cls: 'text-mc-gray' }
  }
}

const POLL_INTERVAL_MS = 4000

export default function PlanPanel() {
  const [summaries, setSummaries] = useState<PlanSummary[]>([])
  const [details, setDetails] = useState<Record<string, FullPlan>>({})
  const [error, setError] = useState<string | null>(null)

  const fetchAll = useCallback(async () => {
    try {
      const r = await fetch('/api/plans')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data: PlansResponse = await r.json()
      const newSummaries = data.plans || []
      setSummaries(newSummaries)
      setError(null)

      // Fetch full details for every active plan in parallel
      const fetched: Record<string, FullPlan> = {}
      await Promise.all(
        newSummaries.map(async (s) => {
          try {
            const dr = await fetch(`/api/plans/${encodeURIComponent(s.bot)}`)
            if (dr.ok) {
              fetched[s.bot] = await dr.json()
            }
          } catch {
            /* skip — leave stale data */
          }
        })
      )
      setDetails(fetched)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'fetch failed')
    }
  }, [])

  useEffect(() => {
    fetchAll()
    const id = window.setInterval(fetchAll, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [fetchAll])

  return (
    <div className="bg-mc-accent/60 border border-mc-border/60 rounded p-3 space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-mc-aqua text-sm font-semibold">Active Plans</h3>
        <span className="text-xs text-mc-gray">{summaries.length} bot{summaries.length === 1 ? '' : 's'}</span>
      </div>
      {error && <div className="text-xs text-mc-red">⚠ {error}</div>}
      {summaries.length === 0 && !error && (
        <div className="text-xs text-mc-gray italic">No active plans. Tell a bot to do something.</div>
      )}

      {summaries.map((p) => {
        const pct = p.subtask_count > 0
          ? Math.round((p.complete_count / p.subtask_count) * 100)
          : 0
        const detail = details[p.bot]
        return (
          <div key={p.bot} className="bg-mc-bg/40 border border-mc-border/40 rounded p-2 space-y-1">
            {/* Header: bot name + status */}
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-mc-white text-sm">{p.bot}</span>
              <span className={`px-1.5 py-0.5 border rounded text-[10px] uppercase ${statusBadge(p.status)}`}>
                {p.status}
              </span>
            </div>

            {/* Task description */}
            <div className="text-xs text-mc-gray italic">"{p.task}"</div>

            {/* Progress bar */}
            <div className="flex items-center gap-2">
              <div className="flex-1 h-1.5 bg-mc-bg rounded overflow-hidden">
                <div
                  className="h-full bg-mc-aqua/70 transition-all"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-[10px] text-mc-gray font-mono">
                {p.complete_count}/{p.subtask_count}
              </span>
            </div>

            {/* Full subtask list (always visible) */}
            {detail && detail.subtasks.length > 0 && (
              <div className="mt-1 space-y-1 border-l border-mc-border/40 pl-2">
                {detail.subtasks.map((s) => {
                  const icon = subtaskIcon(s.status)
                  const isCurrent = s.id === detail.current_subtask_id && s.status !== 'complete'
                  return (
                    <div
                      key={s.id}
                      className={`text-[11px] ${isCurrent ? 'bg-cyan-950/40 -mx-1 px-1 py-0.5 rounded' : ''}`}
                    >
                      <div className="flex items-start gap-1.5">
                        <span className={`inline-block w-3 ${icon.cls} font-mono`}>{icon.ch}</span>
                        <div className="flex-1 min-w-0">
                          <div className="text-mc-white">
                            <span className="text-mc-gray font-mono">{s.id}.</span> {s.description}
                            {s.attempts > 0 && (
                              <span className="text-yellow-400 ml-1 text-[10px]">[try {s.attempts}/3]</span>
                            )}
                            {s.replans > 0 && (
                              <span className="text-orange-400 ml-1 text-[10px]">replan×{s.replans}</span>
                            )}
                          </div>
                          {s.criteria && (
                            <div className="text-[10px] text-mc-gray/70 italic pl-1">
                              criteria: {s.criteria}
                            </div>
                          )}
                          {s.error && (
                            <div className="text-[10px] text-mc-red pl-1" title={s.error}>
                              error: {s.error.slice(0, 100)}
                            </div>
                          )}
                          {Array.isArray(s.directives) && s.directives.length > 0 && (
                            <div className="text-[10px] text-mc-gray/60 pl-1 font-mono">
                              {s.directives.length} directive{s.directives.length === 1 ? '' : 's'}
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
  )
}
