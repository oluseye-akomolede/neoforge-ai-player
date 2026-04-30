import { useState } from 'react'
import type { BotSnapshot, InventorySlot } from '../types'

function dimLabel(dim: string): string {
  return (dim || 'overworld').replace('minecraft:', '').split('_').join(' ')
}

function romanNumeral(n: number): string {
  if (n <= 0 || n > 10) return String(n)
  const numerals = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X']
  return numerals[n]
}

function shortName(id: string): string {
  return (id || '').replace('minecraft:', '').replace(/_/g, ' ')
}

const ATTR_LABELS: Record<string, string> = {
  'generic.attack_damage': 'Attack Damage',
  'generic.attack_speed': 'Attack Speed',
  'generic.attack_knockback': 'Knockback',
  'generic.armor': 'Armor',
  'generic.armor_toughness': 'Armor Toughness',
  'generic.knockback_resistance': 'Knockback Resist',
  'player.block_break_speed': 'Break Speed',
  'player.mining_efficiency': 'Mining Efficiency',
  'player.block_interaction_range': 'Block Range',
  'player.entity_interaction_range': 'Entity Range',
}

function attrLabel(key: string): string {
  return ATTR_LABELS[key] || key.replace('generic.', '').replace('player.', '').replace(/_/g, ' ')
}

function formatAttrValue(amount: number, operation: string): string {
  if (operation === 'add_value') return amount >= 0 ? `+${amount}` : `${amount}`
  if (operation === 'add_multiplied_base' || operation === 'add_multiplied_total')
    return `${amount >= 0 ? '+' : ''}${Math.round(amount * 100)}%`
  return String(amount)
}

function ItemDetailPanel({ item, onClose }: { item: InventorySlot; onClose: () => void }) {
  const hasEnchants = item.enchantments && item.enchantments.length > 0
  const hasDurability = item.max_durability != null && item.max_durability > 0
  const durabilityPct = hasDurability
    ? Math.round(((item.durability ?? 0) / item.max_durability!) * 100)
    : null
  const durabilityColor = durabilityPct != null
    ? durabilityPct > 60 ? 'text-mc-green' : durabilityPct > 25 ? 'text-mc-gold' : 'text-mc-red'
    : ''

  return (
    <div className="border border-mc-gold rounded p-3 bg-mc-dark space-y-2">
      <div className="flex justify-between items-start">
        <div>
          <h4 className={`text-sm font-bold ${hasEnchants ? 'text-mc-aqua' : 'text-white'}`}>
            {item.display_name || shortName(item.item)}
          </h4>
          <p className="text-[10px] text-mc-gray">{item.item}</p>
        </div>
        <button onClick={onClose} className="text-mc-gray hover:text-white text-xs px-1">x</button>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
        <div>Slot: <span className="text-white">{item.slot}</span></div>
        <div>Count: <span className="text-white">{item.count}</span></div>
        {hasDurability && (
          <>
            <div>
              Durability: <span className={durabilityColor}>{item.durability}/{item.max_durability}</span>
            </div>
            <div>
              <span className={durabilityColor}>{durabilityPct}%</span>
            </div>
          </>
        )}
      </div>

      {hasDurability && (
        <div className="w-full bg-mc-accent rounded h-1.5">
          <div
            className={`h-1.5 rounded ${durabilityPct! > 60 ? 'bg-mc-green' : durabilityPct! > 25 ? 'bg-mc-gold' : 'bg-mc-red'}`}
            style={{ width: `${durabilityPct}%` }}
          />
        </div>
      )}

      {item.attributes && Object.keys(item.attributes).length > 0 && (
        <div>
          <h5 className="text-xs text-mc-green font-medium mb-1">Attributes</h5>
          <div className="space-y-0.5">
            {Object.entries(item.attributes).map(([key, attr]) => (
              <div key={key} className="text-xs flex justify-between">
                <span className="text-mc-gray">{attrLabel(key)}</span>
                <span className="text-mc-green">{formatAttrValue(attr.amount, attr.operation)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {hasEnchants && (
        <div>
          <h5 className="text-xs text-mc-purple font-medium mb-1">Enchantments</h5>
          <div className="space-y-0.5">
            {item.enchantments!.map((e, i) => (
              <div key={i} className="text-xs flex justify-between">
                <span className="text-mc-aqua">{shortName(e.id)}</span>
                <span className="text-mc-purple">{romanNumeral(e.level)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function BotDetail({ bot }: { bot: BotSnapshot }) {
  const [selectedItem, setSelectedItem] = useState<InventorySlot | null>(null)
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
            {inv.map((item, i) => {
              const hasEnchants = item.enchantments && item.enchantments.length > 0
              const isSelected = selectedItem?.slot === item.slot
              return (
                <button
                  key={i}
                  onClick={() => setSelectedItem(isSelected ? null : item)}
                  className={`text-xs flex justify-between px-1 py-0.5 rounded text-left transition-colors ${
                    isSelected
                      ? 'bg-mc-accent ring-1 ring-mc-gold'
                      : 'hover:bg-mc-accent/50'
                  }`}
                >
                  <span className={`truncate ${hasEnchants ? 'text-mc-aqua' : 'text-mc-gray'}`}>
                    {(item.display_name || item.item || '').replace('minecraft:', '')}
                  </span>
                  <span className="text-white ml-1 flex-shrink-0">{item.count}</span>
                </button>
              )
            })}
          </div>
        )}
        {selectedItem && (
          <div className="mt-2">
            <ItemDetailPanel item={selectedItem} onClose={() => setSelectedItem(null)} />
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
