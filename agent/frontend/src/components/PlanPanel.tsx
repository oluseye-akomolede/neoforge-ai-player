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
}

interface FullPlan {
  bot: string
  task: string
  status: string
  current_subtask_id: number
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

const POLL_INTERVAL_MS = 5000

export default function PlanPanel() {
  const [summaries, setSummaries] = useState<PlanSummary[]>([])
  const [expanded, setExpanded] = useState<string | null>(null)
  const [detail, setDetail] = useState<FullPlan | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fetchList = useCallback(async () => {
    try {
      const r = await fetch('/api/plans')
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data: PlansResponse = await r.json()
      setSummaries(data.plans || [])
      setError(null)
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'fetch failed')
    }
  }, [])

  const fetchDetail = useCallback(async (bot: string) => {
    try {
      const r = await fetch(`/api/plans/${encodeURIComponent(bot)}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const data: FullPlan = await r.json()
      setDetail(data)
    } catch (e: unknown) {
      setDetail(null)
    }
  }, [])

  useEffect(() => {
    fetchList()
    const id = window.setInterval(fetchList, POLL_INTERVAL_MS)
    return () => window.clearInterval(id)
  }, [fetchList])

  useEffect(() => {
    if (expanded) {
      fetchDetail(expanded)
      const id = window.setInterval(() => fetchDetail(expanded), POLL_INTERVAL_MS)
      return () => window.clearInterval(id)
    }
    setDetail(null)
    return undefined
  }, [expanded, fetchDetail])

  return (
    <div className="bg-mc-accent/60 border border-mc-border/60 rounded p-3 space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-mc-aqua text-sm font-semibold">Active Plans</h3>
        <span className="text-xs text-mc-gray">{summaries.length} active</span>
      </div>
      {error && <div className="text-xs text-mc-red">{error}</div>}
      {summaries.length === 0 && !error && (
        <div className="text-xs text-mc-gray italic">No active plans.</div>
      )}
      <div className="space-y-1">
        {summaries.map((p) => {
          const isOpen = expanded === p.bot
          const pct = p.subtask_count > 0
            ? Math.round((p.complete_count / p.subtask_count) * 100)
            : 0
          return (
            <div key={p.bot} className="text-xs">
              <button
                onClick={() => setExpanded(isOpen ? null : p.bot)}
                className="w-full text-left bg-mc-bg/40 hover:bg-mc-bg/60 border border-mc-border/40 rounded px-2 py-1 transition"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-mc-white truncate">{p.bot}</span>
                  <span className={`px-1.5 py-0.5 border rounded text-[10px] ${statusBadge(p.status)}`}>
                    {p.status}
                  </span>
                </div>
                <div className="text-mc-gray truncate">{p.task}</div>
                <div className="flex items-center gap-2 mt-1">
                  <div className="flex-1 h-1 bg-mc-bg rounded overflow-hidden">
                    <div
                      className="h-full bg-mc-aqua/70"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-[10px] text-mc-gray">
                    {p.complete_count}/{p.subtask_count}
                  </span>
                </div>
                <div className="text-[10px] text-mc-gray mt-0.5">
                  step {p.current_subtask_id}: {p.current_subtask_desc.slice(0, 60)}
                  {p.current_attempts > 0 && (
                    <span className="text-yellow-400"> (try {p.current_attempts + 1})</span>
                  )}
                </div>
              </button>
              {isOpen && detail && detail.bot === p.bot && (
                <div className="mt-1 ml-2 space-y-1 border-l border-mc-border/40 pl-2">
                  {detail.subtasks.map((s) => (
                    <div key={s.id} className="text-[10px]">
                      <span className={`inline-block w-3 ${
                        s.status === 'complete' ? 'text-mc-green' :
                        s.status === 'executing' ? 'text-mc-aqua' :
                        s.status === 'failed' ? 'text-mc-red' :
                        'text-mc-gray'}`}>
                        {s.status === 'complete' ? '✓' :
                         s.status === 'executing' ? '⟳' :
                         s.status === 'failed' ? '✗' :
                         '·'}
                      </span>
                      <span className="text-mc-white">{s.id}. {s.description}</span>
                      {s.attempts > 0 && (
                        <span className="text-yellow-400 ml-1">[{s.attempts}/3]</span>
                      )}
                      {s.replans > 0 && (
                        <span className="text-orange-400 ml-1">replan×{s.replans}</span>
                      )}
                      {s.error && (
                        <div className="ml-4 text-mc-red truncate" title={s.error}>
                          {s.error.slice(0, 80)}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
