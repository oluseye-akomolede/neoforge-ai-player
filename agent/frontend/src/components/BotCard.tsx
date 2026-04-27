import type { BotSnapshot } from '../types'

function healthColor(hp: number): string {
  if (hp > 14) return 'bg-mc-green'
  if (hp > 6) return 'bg-yellow-400'
  return 'bg-mc-red'
}

function dimLabel(dim: string): string {
  return dim.replace('minecraft:', '').split('_').join(' ')
}

export default function BotCard({
  bot,
  selected,
  onClick,
}: {
  bot: BotSnapshot
  selected: boolean
  onClick: () => void
}) {
  const s = bot?.status
  const plan = bot?.plan || { instruction: '', steps: [], step_idx: 0 }
  const planProgress = plan.steps.length
    ? `${plan.step_idx}/${plan.steps.length}`
    : 'idle'

  if (!s) {
    return (
      <button onClick={onClick} className="panel w-full text-left">
        <span className="font-bold text-mc-gold">{bot?.name ?? '?'}</span>
        <span className="text-xs text-mc-gray ml-2">loading...</span>
      </button>
    )
  }

  return (
    <button
      onClick={onClick}
      className={`panel w-full text-left transition-all ${
        selected ? 'ring-2 ring-mc-gold' : 'hover:border-mc-gold/50'
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className={`status-dot ${(s.alive ?? s.is_alive ?? true) ? healthColor(s.health ?? 0) : 'bg-mc-red'}`} />
          <span className="font-bold text-mc-gold">{bot.name}</span>
        </div>
        <span className="text-xs text-mc-gray">{bot.model || ''}</span>
      </div>

      <div className="grid grid-cols-3 gap-2 text-xs text-mc-gray">
        <div>
          HP: <span className="text-white">{Number(s.health ?? 0).toFixed(0)}</span>
        </div>
        <div>
          Food: <span className="text-white">{s.food ?? '?'}</span>
        </div>
        <div>
          XP: <span className="text-mc-green">{s.xp_level ?? 0}</span>
        </div>
      </div>

      <div className="text-xs text-mc-gray mt-1">
        {dimLabel(s.dimension || 'overworld')} &middot;{' '}
        {s.position
          ? `${Number(s.position.x ?? 0).toFixed(0)}, ${Number(s.position.y ?? 0).toFixed(0)}, ${Number(s.position.z ?? 0).toFixed(0)}`
          : '?'}
      </div>

      <div className="flex items-center justify-between mt-2 text-xs">
        <span className={bot.awaiting_taskboard ? 'text-yellow-400' : 'text-mc-aqua'}>
          {bot.awaiting_taskboard ? 'waiting for task' : `plan: ${planProgress}`}
        </span>
        <div className="flex gap-2">
          {plan.steps.length > 0 && (
            <span className="text-mc-purple">L1</span>
          )}
          {(bot.l3_retries ?? 0) > 0 && (
            <span className="text-mc-gold">L3:{bot.l3_retries}</span>
          )}
          {(bot.l4_escalations ?? 0) > 0 && (
            <span className="text-mc-purple">L4:{bot.l4_escalations}</span>
          )}
        </div>
      </div>

      {plan.instruction && (
        <div className="text-xs text-mc-gray mt-1 truncate" title={plan.instruction}>
          {plan.instruction}
        </div>
      )}
    </button>
  )
}
