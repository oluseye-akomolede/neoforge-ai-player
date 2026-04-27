import { useRef, useEffect } from 'react'
import type { DashEvent } from '../types'

function eventColor(type: string): string {
  switch (type) {
    case 'l1_directive': return 'text-mc-aqua'
    case 'directive_sent': return 'text-yellow-400'
    case 'directive_started': return 'text-mc-aqua'
    case 'directive_done': return 'text-mc-green'
    case 'directive_lost': return 'text-mc-red'
    case 'orchestrate': return 'text-mc-gold'
    case 'delegated': return 'text-yellow-400'
    case 'plan_created': return 'text-mc-aqua'
    case 'plan_complete': return 'text-mc-green'
    case 'step_done': return 'text-blue-400'
    case 'l2_retry': return 'text-yellow-400'
    case 'l4_escalation': return 'text-mc-purple'
    case 'task_claimed': return 'text-mc-gold'
    case 'container_found': return 'text-yellow-600'
    case 'bot_stopped': return 'text-mc-red'
    case 'waypoint_set': return 'text-mc-aqua'
    case 'waypoint_deleted': return 'text-mc-gray'
    default: return 'text-mc-gray'
  }
}

function eventText(ev: DashEvent): string {
  switch (ev.type) {
    case 'l1_directive':
      return `L1 ${String(ev.directive || '')}: ${String(ev.step || '')}`
    case 'directive_sent':
      return `Directive ${String(ev.directive || '')}${ev.target ? ` -> ${String(ev.target)}` : ''} (via dashboard)`
    case 'directive_started': {
      const retry = Number(ev.retry || 0)
      const prefix = retry > 0 ? `[retry ${retry}] ` : ''
      return `${prefix}${String(ev.directive || '')} ${String(ev.target || '')}${ev.count ? ` x${ev.count}` : ''}`
    }
    case 'directive_done': {
      if (ev.status === 'completed') {
        const c = ev.counters as Record<string, unknown> | undefined
        const details = c ? Object.entries(c).map(([k, v]) => `${k}=${v}`).join(', ') : ''
        return `Completed${details ? `: ${details}` : ''}`
      }
      return `${String(ev.status || 'failed').toUpperCase()}: ${String(ev.reason || '')}`
    }
    case 'directive_lost':
      return `Directive lost (${String(ev.reason || 'server restart')})`
    case 'orchestrate':
      return `Orchestrating: ${String(ev.message || '')}`
    case 'delegated': {
      const steps = Array.isArray(ev.steps) ? ev.steps as string[] : []
      return `Delegated to ${String(ev.to || '?')}: ${steps.map(s => String(s).substring(0, 40)).join(', ') || '?'}`
    }
    case 'plan_created': {
      const steps = Array.isArray(ev.steps) ? ev.steps as string[] : []
      return `Plan (${steps.length} steps): ${steps.map((s, i) => `${i+1}. ${String(s).substring(0, 40)}`).join(' → ')}`
    }
    case 'plan_complete':
      return `Plan complete (${String(ev.steps || '?')} steps)`
    case 'step_done':
      return `Step done [${String(ev.progress || '')}]: "${String(ev.completed || '')}" → next: "${String(ev.next || '')}"`
    case 'l2_retry':
      return `L2 retry #${String(ev.retry || '?')}: ${String(ev.reason || '')}`
    case 'l4_escalation':
      return 'L4 escalation'
    case 'task_claimed':
      return `Claimed task #${String(ev.task_id || '?')}: ${String(ev.description || '')}`
    case 'container_found':
      return `Found ${String(ev.block || 'chest').replace('minecraft:', '')} at ${ev.x}, ${ev.y}, ${ev.z}`
    case 'bot_stopped':
      return 'Stopped (via dashboard)'
    case 'waypoint_set':
      return `Waypoint "${String(ev.name || '')}" set at ${String(ev.x || 0)}, ${String(ev.y || 0)}, ${String(ev.z || 0)}`
    case 'waypoint_deleted':
      return `Waypoint "${String(ev.name || '')}" deleted`
    default:
      return `${ev.type}: ${JSON.stringify(ev)}`
  }
}

function formatTime(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString()
}

export default function EventLog({ events }: { events: DashEvent[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)

  return (
    <div className="panel">
      <h3 className="text-mc-gold font-bold mb-2">Event Log ({events.length})</h3>
      <div ref={scrollRef} className="max-h-64 overflow-y-auto space-y-0.5">
        {events.length === 0 && (
          <p className="text-xs text-mc-gray">No events yet — directives and bot activity will appear here</p>
        )}
        {events.map((ev, i) => (
          <div key={i} className="text-xs flex gap-2">
            <span className="text-mc-gray/60 shrink-0">{formatTime(ev.ts)}</span>
            {ev.bot ? <span className="text-mc-gold shrink-0">[{String(ev.bot)}]</span> : null}
            <span className={eventColor(ev.type)}>
              {eventText(ev)}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
