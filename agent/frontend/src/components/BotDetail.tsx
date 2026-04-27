import type { BotSnapshot } from '../types'

function dimLabel(dim: string): string {
  return (dim || 'overworld').replace('minecraft:', '').split('_').join(' ')
}

export default function BotDetail({ bot }: { bot: BotSnapshot }) {
  const s = bot?.status
  if (!s) return null
  const isAlive = s.alive ?? s.is_alive ?? true
  const plan = bot.plan || { instruction: '', steps: [], step_idx: 0 }
  const inv = bot.inventory || []
  const ents = bot.entities || []

  return (
    <div className="space-y-4">
      {/* Status */}
      <div className="panel">
        <h3 className="text-mc-gold font-bold mb-2">Status</h3>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            Health:{' '}
            <span className="text-white">
              {Number(s.health ?? 0).toFixed(1)} / 20
            </span>
          </div>
          <div>
            Food: <span className="text-white">{s.food ?? '?'}</span>
          </div>
          <div>
            XP Level: <span className="text-mc-green">{s.xp_level ?? 0}</span>
          </div>
          <div>
            Alive: <span className={isAlive ? 'text-mc-green' : 'text-mc-red'}>{isAlive ? 'Yes' : 'No'}</span>
          </div>
          <div>
            Dimension: <span className="text-mc-aqua">{dimLabel(s.dimension)}</span>
          </div>
          <div>
            Position:{' '}
            <span className="text-white">
              {s.position
                ? `${Number(s.position.x ?? 0).toFixed(1)}, ${Number(s.position.y ?? 0).toFixed(1)}, ${Number(s.position.z ?? 0).toFixed(1)}`
                : 'unknown'}
            </span>
          </div>
          <div>
            Model: <span className="text-mc-gray">{bot.model || '?'}</span>
          </div>
          <div>
            Specs:{' '}
            <span className="text-mc-gray">{(bot.specializations || []).join(', ') || 'none'}</span>
          </div>
        </div>
      </div>

      {/* Current directive / activity */}
      {bot.current_task_id ? (
        <div className="panel">
          <h3 className="text-mc-gold font-bold mb-1">Active Directive</h3>
          <div className="text-xs text-mc-aqua">Task #{bot.current_task_id}</div>
        </div>
      ) : null}

      {/* Current Plan */}
      {plan.steps.length > 0 && (
        <div className="panel">
          <h3 className="text-mc-gold font-bold mb-2">Current Plan</h3>
          {plan.instruction && (
            <p className="text-sm text-mc-gray mb-2">{plan.instruction}</p>
          )}
          <div className="space-y-1">
            {plan.steps.map((step, i) => (
              <div
                key={i}
                className={`text-xs px-2 py-1 rounded ${
                  i < plan.step_idx
                    ? 'text-mc-green/60 line-through'
                    : i === plan.step_idx
                    ? 'bg-mc-accent text-white font-medium'
                    : 'text-mc-gray'
                }`}
              >
                {i + 1}. {step}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Inventory */}
      <div className="panel">
        <h3 className="text-mc-gold font-bold mb-2">
          Inventory ({inv.length} items)
        </h3>
        {inv.length === 0 ? (
          <p className="text-xs text-mc-gray">Empty</p>
        ) : (
          <div className="grid grid-cols-2 gap-1 max-h-48 overflow-y-auto">
            {inv.map((item, i) => (
              <div key={i} className="text-xs flex justify-between px-1">
                <span className="text-mc-gray truncate">
                  {(item.display_name || item.item || '').replace('minecraft:', '')}
                </span>
                <span className="text-white ml-1">{item.count}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Nearby Entities */}
      {ents.length > 0 && (
        <div className="panel">
          <h3 className="text-mc-gold font-bold mb-2">
            Nearby ({ents.length})
          </h3>
          <div className="space-y-1 max-h-32 overflow-y-auto">
            {ents.slice(0, 20).map((e, i) => (
              <div key={i} className="text-xs flex justify-between">
                <span className="text-mc-gray">
                  {e.name || e.type}
                </span>
                <span className="text-white">{Number(e.distance ?? 0).toFixed(1)}m</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
