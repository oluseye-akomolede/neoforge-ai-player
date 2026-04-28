import { useState, useEffect, useCallback } from 'react'

interface Task {
  id: number
  description: string
  assigned_to: string | null
  created_by: string
  specialization: string | null
  status: string
  result: string | null
  created_at: string
  updated_at: string
}

function statusColor(status: string): string {
  switch (status) {
    case 'pending': return 'text-yellow-400'
    case 'assigned': return 'text-orange-400'
    case 'in_progress': return 'text-mc-aqua'
    case 'done': return 'text-mc-green'
    case 'failed': return 'text-mc-red'
    default: return 'text-mc-gray'
  }
}

function statusBadge(status: string): string {
  switch (status) {
    case 'pending': return 'bg-yellow-900/40 border-yellow-600/40'
    case 'assigned': return 'bg-orange-900/40 border-orange-600/40'
    case 'in_progress': return 'bg-cyan-900/40 border-cyan-600/40'
    case 'done': return 'bg-green-900/40 border-green-600/40'
    case 'failed': return 'bg-red-900/40 border-red-600/40'
    default: return 'bg-mc-accent border-mc-accent'
  }
}

function statusLabel(status: string): string {
  switch (status) {
    case 'in_progress': return 'running'
    case 'assigned': return 'claimed'
    default: return status
  }
}

function timeAgo(iso: string): string {
  const ts = new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()
  const diff = (Date.now() - ts) / 1000
  if (diff < 0) return 'now'
  if (diff < 60) return `${Math.floor(diff)}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

export function useTasks(): [Task[], () => void] {
  const [tasks, setTasks] = useState<Task[]>([])
  const refresh = useCallback(() => {
    fetch('/api/tasks')
      .then((r) => r.json())
      .then((d) => setTasks(d.tasks || []))
      .catch(() => {})
  }, [])
  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 5_000)
    return () => clearInterval(id)
  }, [refresh])
  return [tasks, refresh]
}

const DONE_STATUSES = new Set(['done', 'failed'])

export default function TaskBoard({ tasks, onRefresh }: { tasks: Task[]; onRefresh: () => void }) {
  const [showDone, setShowDone] = useState(false)

  const active = tasks.filter((t) => !DONE_STATUSES.has(t.status))
  const done = tasks.filter((t) => DONE_STATUSES.has(t.status))
  const visible = showDone ? tasks : active

  const handleDelete = async (id: number) => {
    try {
      await fetch(`/api/tasks/${id}`, { method: 'DELETE' })
      onRefresh()
    } catch {
      // ignore
    }
  }

  const handleReset = async () => {
    if (!confirm('Reset all bots? This clears all tasks and cancels directives.')) return
    try {
      await fetch('/api/reset', { method: 'POST' })
      onRefresh()
    } catch {
      // ignore
    }
  }

  return (
    <div className="panel">
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-mc-gold font-bold">
          Task Board ({active.length} active{done.length > 0 ? `, ${done.length} done` : ''})
        </h3>
        <div className="flex gap-2">
          {done.length > 0 && (
            <button
              onClick={() => setShowDone(!showDone)}
              className="text-xs text-mc-gray hover:text-white transition-colors"
            >
              {showDone ? 'Hide done' : 'Show done'}
            </button>
          )}
          <button
            onClick={handleReset}
            className="text-xs text-mc-red hover:text-red-300 transition-colors"
            title="Reset all bots"
          >
            Reset
          </button>
        </div>
      </div>

      <div className="max-h-48 overflow-y-auto space-y-1">
        {visible.length === 0 && (
          <p className="text-xs text-mc-gray">No active tasks — bots are idle</p>
        )}
        {visible.map((task) => (
          <div
            key={task.id}
            className={`text-xs border rounded px-2 py-1 group ${statusBadge(task.status)}`}
          >
            <div className="flex items-center justify-between gap-1">
              <span className="truncate flex-1">{task.description}</span>
              <span className={`shrink-0 font-mono ${statusColor(task.status)}`}>
                {statusLabel(task.status)}
              </span>
              <button
                onClick={() => handleDelete(task.id)}
                className="shrink-0 text-mc-gray/40 hover:text-mc-red opacity-0 group-hover:opacity-100 transition-opacity ml-1"
                title="Delete task"
              >
                x
              </button>
            </div>
            <div className="flex items-center gap-2 text-mc-gray/70 mt-0.5">
              {task.assigned_to && <span>{task.assigned_to}</span>}
              {task.specialization && <span className="text-mc-gray/50">[{task.specialization}]</span>}
              {task.result && <span className="truncate text-mc-gray/50">{task.result}</span>}
              <span className="ml-auto shrink-0">{timeAgo(task.updated_at)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
