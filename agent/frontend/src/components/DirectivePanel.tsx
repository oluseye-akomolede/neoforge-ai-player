import { useState, useEffect, useMemo } from 'react'
import type { DirectiveDef, BotSnapshot, InventorySlot, OnlinePlayer } from '../types'
import {
  useDirectives, useSendDirective, useSendCommand,
  useTransmuteItems, useEnchantments, useContainers, fetchContainerContents,
  useDimensions, usePlayers,
  type TransmuteItem, type EnchantmentItem, type ContainerInfo,
} from '../hooks'

type Tier = 'l1' | 'l3' | 'l4'

export default function DirectivePanel({
  selectedBot,
  botData,
  allBots,
}: {
  selectedBot: string | null
  botData: BotSnapshot | null
  allBots: BotSnapshot[]
}) {
  const directives = useDirectives()
  const sendDirective = useSendDirective()
  const sendCommand = useSendCommand()
  const transmuteItems = useTransmuteItems()
  const enchantmentItems = useEnchantments()
  const containers = useContainers()
  const serverDimensions = useDimensions()
  const onlinePlayers = usePlayers()

  const [tier, setTier] = useState<Tier>('l1')
  const [selected, setSelected] = useState<DirectiveDef | null>(null)
  const [params, setParams] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<string>('')
  const [nlInput, setNlInput] = useState('')
  const [containerContents, setContainerContents] = useState<InventorySlot[]>([])
  const [selectedContainer, setSelectedContainer] = useState<ContainerInfo | null>(null)
  const [transmuteSearch, setTransmuteSearch] = useState('')
  const [enchantSearch, setEnchantSearch] = useState('')
  const [coordBots, setCoordBots] = useState<Set<string>>(new Set())
  const [sendingCoord, setSendingCoord] = useState(false)

  const handleSelect = (d: DirectiveDef) => {
    setSelected(d)
    const defaults: Record<string, string> = {}
    d.params.forEach((p) => {
      if (p.default !== undefined) defaults[p.name] = String(p.default)
      if (p.fields) {
        p.fields.forEach((f) => {
          if (f.default !== undefined) defaults[`extra.${f.name}`] = String(f.default)
        })
      }
    })
    setParams(defaults)
    setStatus('')
    setContainerContents([])
    setSelectedContainer(null)
    setTransmuteSearch('')
  }

  const handleContainerSelect = async (c: ContainerInfo) => {
    setSelectedContainer(c)
    setParams((prev) => ({
      ...prev,
      x: String(c.x),
      y: String(c.y),
      z: String(c.z),
    }))
    try {
      const data = await fetchContainerContents(c.x, c.y, c.z)
      setContainerContents(data.items || [])
    } catch {
      setContainerContents([])
    }
  }

  const handleInventorySelect = (item: InventorySlot) => {
    setParams((prev) => ({ ...prev, target: item.item }))
  }

  const [sendingDirective, setSendingDirective] = useState(false)

  const handleSendDirective = async () => {
    if (!selected || !selectedBot || sendingDirective) return
    setSendingDirective(true)
    setStatus(`Sending ${selected.label}...`)
    const req: Record<string, unknown> = {
      bot: selectedBot,
      directive_type: selected.type,
    }
    selected.params.forEach((p) => {
      if (p.type === 'dict' && p.fields) {
        const extra: Record<string, string> = {}
        p.fields.forEach((f) => {
          const val = params[`extra.${f.name}`]
          if (val !== undefined && val !== '') extra[f.name] = val
        })
        if (Object.keys(extra).length > 0) req.extra = extra
        return
      }
      const val = params[p.name]
      if (val === undefined || val === '') return
      if (p.name === 'extra' && p.type === 'dimension') {
        req.extra = { dimension: val }
      } else if (p.type === 'int' || p.type === 'float') {
        req[p.name] = Number(val)
      } else {
        req[p.name] = val
      }
    })
    try {
      const res = await sendDirective(req)
      setStatus(res.ok ? `${selected.label} directive sent` : `Error: ${res.error || 'Unknown error'}`)
      if (res.ok) {
        const defaults: Record<string, string> = {}
        selected.params.forEach((p) => {
          if (p.default !== undefined) defaults[p.name] = String(p.default)
          if (p.fields) {
            p.fields.forEach((f) => {
              if (f.default !== undefined) defaults[`extra.${f.name}`] = String(f.default)
            })
          }
        })
        setParams(defaults)
        setContainerContents([])
        setSelectedContainer(null)
      }
    } catch (e) {
      setStatus(`Error: ${e}`)
    } finally {
      setSendingDirective(false)
    }
  }

  const [sending, setSending] = useState(false)

  const handleSendNL = async () => {
    if (!selectedBot || !nlInput.trim() || sending) return
    const prefix = tier === 'l4' ? '[L4] ' : ''
    setSending(true)
    setStatus('Sending to planner...')
    try {
      const res = await sendCommand(selectedBot, prefix + nlInput.trim())
      if (res.ok) {
        setStatus(`Sent to ${tier === 'l4' ? 'L4 (OpenAI)' : 'L3'} planner — check bot status for progress`)
        setNlInput('')
      } else {
        setStatus(`Error: ${res.error || 'Unknown error'}`)
      }
    } catch (e) {
      setStatus(`Error: ${e}`)
    } finally {
      setSending(false)
    }
  }

  const sortedTransmute = useMemo(
    () => [...transmuteItems].sort((a, b) => a.item_id.localeCompare(b.item_id)),
    [transmuteItems],
  )
  const filteredTransmute = useMemo(() => {
    if (!transmuteSearch.trim()) return sortedTransmute
    const q = transmuteSearch.toLowerCase().replace('minecraft:', '')
    return sortedTransmute.filter((i) => i.item_id.toLowerCase().includes(q))
  }, [sortedTransmute, transmuteSearch])

  const sortedEnchantments = useMemo(
    () => [...enchantmentItems].sort((a, b) => a.id.localeCompare(b.id)),
    [enchantmentItems],
  )
  const filteredEnchantments = useMemo(() => {
    if (!enchantSearch.trim()) return sortedEnchantments
    const q = enchantSearch.toLowerCase().replace('minecraft:', '')
    return sortedEnchantments.filter((e) => e.id.toLowerCase().includes(q))
  }, [sortedEnchantments, enchantSearch])

  const isContainerDirective = selected?.type === 'CONTAINER_STORE' || selected?.type === 'CONTAINER_WITHDRAW'
  const isConjureDirective = selected?.type === 'CHANNEL'
  const isEnchantDirective = selected?.type === 'ENCHANT'
  const needsInventoryPick = selected?.type === 'CONTAINER_STORE' || selected?.type === 'SEND_ITEM'

  const renderParamInput = (p: DirectiveDef['params'][0]) => {
    // Conjure item: use transmute registry dropdown + custom input
    if (isConjureDirective && p.name === 'target') {
      return (
        <div>
          <label className="text-xs text-mc-gray block mb-1">
            {p.label} <span className="text-mc-red">*</span>
          </label>
          <input
            type="text"
            value={transmuteSearch}
            onChange={(e) => setTransmuteSearch(e.target.value)}
            placeholder={`Search ${transmuteItems.length} known items...`}
            className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
          />
          <div className="mt-1 max-h-40 overflow-y-auto border border-mc-accent rounded">
            {filteredTransmute.length === 0 ? (
              <p className="text-[10px] text-mc-gray px-2 py-1">No matches</p>
            ) : (
              filteredTransmute.map((item) => (
                <button
                  key={item.item_id}
                  onClick={() => {
                    setParams((prev) => ({ ...prev, target: item.item_id }))
                    setTransmuteSearch('')
                  }}
                  className={`text-[10px] block w-full text-left px-2 py-0.5 hover:bg-mc-accent ${
                    params.target === item.item_id ? 'bg-mc-accent text-mc-gold' : 'text-mc-gray'
                  }`}
                >
                  {item.item_id.replace('minecraft:', '')}
                  <span className="text-mc-green ml-1">({item.xp_cost} XP)</span>
                </button>
              ))
            )}
          </div>
          {params.target && (
            <div className="mt-1 text-xs text-mc-aqua">
              Selected: {params.target.replace('minecraft:', '')}
            </div>
          )}
          <input
            type="text"
            value={params.target || ''}
            onChange={(e) => setParams((prev) => ({ ...prev, target: e.target.value }))}
            placeholder="or type custom item ID"
            className="w-full mt-1 bg-mc-dark border border-mc-accent rounded px-2 py-1 text-[10px] focus:outline-none focus:border-mc-gold text-mc-gray"
          />
        </div>
      )
    }

    // Enchant directive: item to enchant picker
    if (isEnchantDirective && p.name === 'target') {
      return (
        <div className="border border-mc-accent rounded p-2 space-y-2">
          <label className="text-xs text-mc-gold block font-medium">Item to Enchant</label>

          {/* Inventory picker */}
          {botData && (botData.inventory || []).length > 0 && (
            <div className="max-h-28 overflow-y-auto border border-mc-accent rounded">
              {(botData.inventory || []).filter((item) => {
                const id = item.item.toLowerCase()
                return !id.includes('air') && (
                  id.includes('sword') || id.includes('pickaxe') || id.includes('axe') ||
                  id.includes('shovel') || id.includes('hoe') || id.includes('bow') ||
                  id.includes('crossbow') || id.includes('trident') || id.includes('mace') ||
                  id.includes('helmet') || id.includes('chestplate') || id.includes('leggings') ||
                  id.includes('boots') || id.includes('shield') || id.includes('fishing_rod') ||
                  id.includes('shears') || id.includes('flint_and_steel') || id.includes('book') ||
                  !id.includes('_') || true
                )
              }).map((item, i) => (
                <button
                  key={i}
                  onClick={() => setParams((prev) => ({ ...prev, target: item.item }))}
                  className={`text-[10px] block w-full text-left px-2 py-0.5 hover:bg-mc-accent ${
                    params.target === item.item ? 'bg-mc-accent text-mc-gold' : 'text-mc-gray'
                  }`}
                >
                  [{item.slot}] {(item.display_name || item.item).replace('minecraft:', '')} x{item.count}
                </button>
              ))}
            </div>
          )}

          {/* Text input fallback */}
          <input
            type="text"
            value={params.target || ''}
            onChange={(e) => setParams((prev) => ({ ...prev, target: e.target.value }))}
            placeholder="Item name (e.g. diamond_sword) or slot number"
            className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
          />
          {params.target && (
            <p className="text-[10px] text-mc-aqua">
              Enchanting: {params.target.replace('minecraft:', '')}
            </p>
          )}
          {!params.target && (
            <p className="text-[10px] text-mc-gray">Leave empty to enchant any enchantable item</p>
          )}
        </div>
      )
    }

    // Enchant directive: searchable enchantment + level + inventory item picker
    if (isEnchantDirective && p.type === 'dict' && p.fields) {
      const selectedEnch = params['extra.enchantment'] || ''
      const selectedEnchEntry = enchantmentItems.find((e) => e.id === selectedEnch)
      return (
        <div className="border border-mc-accent rounded p-2 space-y-2">
          <label className="text-xs text-mc-gold block font-medium">Enchantment</label>

          {/* Searchable enchantment dropdown */}
          <div>
            <input
              type="text"
              value={enchantSearch}
              onChange={(e) => setEnchantSearch(e.target.value)}
              placeholder={`Search ${enchantmentItems.length} enchantments...`}
              className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
            />
            <div className="mt-1 max-h-40 overflow-y-auto border border-mc-accent rounded">
              {filteredEnchantments.length === 0 ? (
                <p className="text-[10px] text-mc-gray px-2 py-1">No matches</p>
              ) : (
                filteredEnchantments.map((ench) => (
                  <button
                    key={ench.id}
                    onClick={() => {
                      setParams((prev) => ({
                        ...prev,
                        'extra.enchantment': ench.id,
                        'extra.level': String(ench.max_level),
                      }))
                      setEnchantSearch('')
                    }}
                    className={`text-[10px] block w-full text-left px-2 py-0.5 hover:bg-mc-accent ${
                      selectedEnch === ench.id ? 'bg-mc-accent text-mc-gold' : 'text-mc-gray'
                    }`}
                  >
                    {ench.id.replace('minecraft:', '')}
                    <span className="text-mc-aqua ml-1">max {ench.max_level}</span>
                    <span className="text-mc-green ml-1">({ench.xp_cost_per_level} XP/lvl)</span>
                    {ench.source !== 'vanilla' && (
                      <span className="text-mc-purple ml-1">[{ench.source}]</span>
                    )}
                  </button>
                ))
              )}
            </div>
          </div>

          {/* Selected enchantment + level */}
          {selectedEnch && (
            <div className="flex gap-2 items-center">
              <span className="text-xs text-mc-aqua flex-1">
                {selectedEnch.replace('minecraft:', '')}
              </span>
              <label className="text-[10px] text-mc-gray">Level:</label>
              <input
                type="number"
                min="1"
                max={selectedEnchEntry?.max_level || 255}
                value={params['extra.level'] || ''}
                onChange={(e) => setParams((prev) => ({ ...prev, 'extra.level': e.target.value }))}
                className="w-16 bg-mc-dark border border-mc-accent rounded px-2 py-0.5 text-sm focus:outline-none focus:border-mc-gold"
              />
              <button
                onClick={() => {
                  setParams((prev) => {
                    const next = { ...prev }
                    delete next['extra.enchantment']
                    delete next['extra.level']
                    return next
                  })
                }}
                className="text-[10px] px-1 text-mc-red hover:underline"
              >Clear</button>
            </div>
          )}

          {/* Random tier fallback */}
          {!selectedEnch && (
            <div>
              <label className="text-[10px] text-mc-gray block mb-0.5">Random tier (no specific enchantment)</label>
              <select
                value={params['extra.option'] || '2'}
                onChange={(e) => setParams((prev) => ({ ...prev, 'extra.option': e.target.value }))}
                className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
              >
                <option value="0">Basic (1-8)</option>
                <option value="1">Mid (9-20)</option>
                <option value="2">Max (21-30)</option>
              </select>
            </div>
          )}

          {selectedEnchEntry && (
            <p className="text-[10px] text-mc-gray">
              Cost: {selectedEnchEntry.xp_cost_per_level * (parseInt(params['extra.level'] || '1') || 1)} XP levels
            </p>
          )}
        </div>
      )
    }

    // Dimension selector: use live server dimensions
    if (p.type === 'dimension') {
      const dims = serverDimensions.length > 0 ? serverDimensions : (p.options || [])
      return (
        <div>
          <label className="text-xs text-mc-gray block mb-1">{p.label}</label>
          <select
            value={params[p.name] || ''}
            onChange={(e) => setParams((prev) => ({ ...prev, [p.name]: e.target.value }))}
            className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
          >
            <option value="">-- current --</option>
            {dims.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </div>
      )
    }

    // "Use bot position" helper for coordinate fields
    if (p.use_bot_pos && botData) {
      const posKey = p.name === 'x' ? 'x' : p.name === 'y' ? 'y' : 'z'
      const posVal = botData.status?.position?.[posKey]
      return (
        <div>
          <label className="text-xs text-mc-gray block mb-1">
            {p.label}
            {p.required && <span className="text-mc-red ml-1">*</span>}
          </label>
          <div className="flex gap-1">
            <input
              type="number"
              step="0.1"
              value={params[p.name] || ''}
              onChange={(e) => setParams((prev) => ({ ...prev, [p.name]: e.target.value }))}
              placeholder={p.label}
              className="flex-1 bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
            />
            {posVal !== undefined && (
              <button
                onClick={() => setParams((prev) => ({ ...prev, [p.name]: String(Math.round(posVal)) }))}
                className="text-[10px] px-1.5 bg-mc-accent rounded hover:bg-blue-700 text-mc-aqua whitespace-nowrap"
                title={`Use bot's current ${posKey.toUpperCase()} (${Math.round(posVal)})`}
              >
                Bot: {Math.round(posVal)}
              </button>
            )}
          </div>
          {p.hint && <p className="text-[10px] text-mc-gray mt-0.5">{p.hint}</p>}
        </div>
      )
    }

    // Dict with nested fields — render each sub-field
    if (p.type === 'dict' && p.fields) {
      return (
        <div className="border border-mc-accent rounded p-2 space-y-2">
          <label className="text-xs text-mc-gold block font-medium">{p.label}</label>
          {p.fields.map((f) => {
            const key = `extra.${f.name}`
            if (f.options) {
              return (
                <div key={f.name}>
                  <label className="text-[10px] text-mc-gray block mb-0.5">{f.label}</label>
                  <select
                    value={params[key] || ''}
                    onChange={(e) => setParams((prev) => ({ ...prev, [key]: e.target.value }))}
                    className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
                  >
                    {f.options.map((opt, i) => (
                      <option key={opt} value={opt}>
                        {f.option_labels?.[i] || opt}
                      </option>
                    ))}
                  </select>
                  {f.hint && <p className="text-[10px] text-mc-gray mt-0.5">{f.hint}</p>}
                </div>
              )
            }
            return (
              <div key={f.name}>
                <label className="text-[10px] text-mc-gray block mb-0.5">{f.label}</label>
                <input
                  type="text"
                  value={params[key] || ''}
                  onChange={(e) => setParams((prev) => ({ ...prev, [key]: e.target.value }))}
                  placeholder={f.label}
                  className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
                />
                {f.hint && <p className="text-[10px] text-mc-gray mt-0.5">{f.hint}</p>}
              </div>
            )
          })}
        </div>
      )
    }

    // Standard dropdown
    if (p.options) {
      return (
        <div>
          <label className="text-xs text-mc-gray block mb-1">
            {p.label}
            {p.required && <span className="text-mc-red ml-1">*</span>}
          </label>
          <select
            value={params[p.name] || ''}
            onChange={(e) => setParams((prev) => ({ ...prev, [p.name]: e.target.value }))}
            className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
          >
            <option value="">-- select --</option>
            {p.options.map((opt, i) => (
              <option key={opt} value={opt}>{p.option_labels?.[i] || opt.replace('minecraft:', '')}</option>
            ))}
          </select>
          {p.hint && <p className="text-[10px] text-mc-gray mt-0.5">{p.hint}</p>}
        </div>
      )
    }

    // Standard input
    return (
      <div>
        <label className="text-xs text-mc-gray block mb-1">
          {p.label}
          {p.required && <span className="text-mc-red ml-1">*</span>}
        </label>
        <input
          type={p.type === 'int' || p.type === 'float' ? 'number' : 'text'}
          step={p.type === 'float' ? '0.1' : undefined}
          value={params[p.name] || ''}
          onChange={(e) => setParams((prev) => ({ ...prev, [p.name]: e.target.value }))}
          placeholder={p.hint || p.label}
          className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
        />
        {p.hint && <p className="text-[10px] text-mc-gray mt-0.5">{p.hint}</p>}
      </div>
    )
  }

  return (
    <div className="panel">
      {/* Tier selector */}
      <div className="flex gap-1 mb-3">
        {([
          { key: 'l1' as Tier, label: 'L1 Direct', color: 'bg-mc-aqua' },
          { key: 'l3' as Tier, label: 'L3 Plan (Ollama)', color: 'bg-mc-gold' },
          { key: 'l4' as Tier, label: 'L4 Escalate (OpenAI)', color: 'bg-mc-purple' },
        ]).map((t) => (
          <button
            key={t.key}
            onClick={() => { setTier(t.key); setStatus('') }}
            className={`text-xs px-2 py-1 rounded transition-colors ${
              tier === t.key
                ? `${t.color} text-black font-medium`
                : 'bg-mc-accent text-white hover:bg-blue-700'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {!selectedBot && (
        <p className="text-xs text-mc-gray">Select a bot first</p>
      )}

      {/* L3/L4: natural language input */}
      {selectedBot && tier !== 'l1' && (
        <div className="space-y-2">
          <p className="text-xs text-mc-gray">
            {tier === 'l3'
              ? 'Send instruction to Ollama planner (local LLM)'
              : 'Escalate to OpenAI for complex planning'}
          </p>
          <textarea
            value={nlInput}
            onChange={(e) => setNlInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendNL() }}}
            placeholder="Describe what the bot should do..."
            rows={3}
            className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1.5 text-sm focus:outline-none focus:border-mc-gold resize-none"
          />
          <button
            onClick={handleSendNL}
            disabled={sending || !nlInput.trim()}
            className={`btn-gold w-full ${sending ? 'opacity-60 cursor-wait' : ''}`}
          >
            {sending ? 'Sending...' : `Send to ${tier === 'l3' ? 'L3 Planner' : 'L4 (OpenAI)'}`}
          </button>
          {status && (
            <p className={`text-xs ${
              status.startsWith('Error') ? 'text-mc-red'
              : status.startsWith('Sending') ? 'text-mc-gold animate-pulse'
              : 'text-mc-green'
            }`}>
              {status}
            </p>
          )}
        </div>
      )}

      {/* L1: directive picker */}
      {selectedBot && tier === 'l1' && (
        <>
          <div className="flex flex-wrap gap-1 mb-3">
            {directives.map((d) => (
              <button
                key={d.type}
                onClick={() => handleSelect(d)}
                className={`text-xs px-2 py-1 rounded transition-colors ${
                  selected?.type === d.type
                    ? 'bg-mc-aqua text-black font-medium'
                    : 'bg-mc-accent text-white hover:bg-blue-700'
                }`}
              >
                {d.label}
              </button>
            ))}
          </div>

          {selected && (
            <div className="space-y-2">
              {/* Directive description */}
              {selected.description && (
                <p className="text-[11px] text-mc-gray leading-snug">{selected.description}</p>
              )}

              {/* Position shortcuts for directives with coordinate fields */}
              {selected.params.some((p) => p.use_bot_pos) && (
                <div className="flex flex-wrap gap-1">
                  {botData && (
                    <button
                      onClick={() => {
                        const pos = botData.status?.position
                        if (!pos) return
                        setParams((prev) => ({
                          ...prev,
                          x: String(Math.round(pos.x)),
                          y: String(Math.round(pos.y)),
                          z: String(Math.round(pos.z)),
                        }))
                      }}
                      className="text-[10px] px-2 py-1 bg-mc-accent rounded hover:bg-blue-700 text-mc-aqua"
                    >
                      {selectedBot}: {Math.round(botData.status?.position?.x ?? 0)}, {Math.round(botData.status?.position?.y ?? 0)}, {Math.round(botData.status?.position?.z ?? 0)}
                    </button>
                  )}
                  {onlinePlayers.map((p) => (
                    <button
                      key={p.name}
                      onClick={() =>
                        setParams((prev) => ({
                          ...prev,
                          x: String(Math.round(p.x)),
                          y: String(Math.round(p.y)),
                          z: String(Math.round(p.z)),
                        }))
                      }
                      className="text-[10px] px-2 py-1 bg-mc-accent rounded hover:bg-blue-700"
                      style={{ color: '#ff55ff' }}
                    >
                      {p.name}: {Math.round(p.x)}, {Math.round(p.y)}, {Math.round(p.z)}
                    </button>
                  ))}
                </div>
              )}

              {/* Container picker for container directives */}
              {isContainerDirective && (
                <div>
                  <label className="text-xs text-mc-gray block mb-1">Container</label>
                  <select
                    value={selectedContainer ? String(selectedContainer.id) : ''}
                    onChange={(e) => {
                      const c = containers.find((c) => String(c.id) === e.target.value)
                      if (c) handleContainerSelect(c)
                    }}
                    className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
                  >
                    <option value="">-- select container ({containers.length}) --</option>
                    {containers.map((c) => (
                      <option key={c.id} value={String(c.id)}>
                        #{c.id} at {c.x}, {c.y}, {c.z} ({c.dimension.replace('minecraft:', '')}) — {c.placed_by}
                      </option>
                    ))}
                  </select>
                  {containerContents.length > 0 && (
                    <div className="mt-1 max-h-24 overflow-y-auto border border-mc-accent rounded p-1">
                      <p className="text-[10px] text-mc-gray mb-1">Contents ({containerContents.length}):</p>
                      {containerContents.map((item, i) => (
                        <button
                          key={i}
                          onClick={() => {
                            if (selected.type === 'CONTAINER_WITHDRAW') {
                              setParams((prev) => ({ ...prev, target: item.item }))
                            }
                          }}
                          className={`text-[10px] block w-full text-left px-1 rounded hover:bg-mc-accent ${
                            params.target === item.item ? 'bg-mc-accent text-mc-gold' : 'text-mc-gray'
                          }`}
                        >
                          {(item.display_name || item.item).replace('minecraft:', '')} x{item.count}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Inventory picker for store/send directives */}
              {needsInventoryPick && botData && (botData.inventory || []).length > 0 && (
                <div>
                  <label className="text-xs text-mc-gray block mb-1">From inventory</label>
                  <div className="max-h-24 overflow-y-auto border border-mc-accent rounded p-1">
                    {(botData.inventory || []).map((item, i) => (
                      <button
                        key={i}
                        onClick={() => handleInventorySelect(item)}
                        className={`text-[10px] block w-full text-left px-1 rounded hover:bg-mc-accent ${
                          params.target === item.item ? 'bg-mc-accent text-mc-gold' : 'text-mc-gray'
                        }`}
                      >
                        [{item.slot}] {(item.display_name || item.item).replace('minecraft:', '')} x{item.count}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Render params (skip x/y/z for container directives since picker fills them) */}
              {selected.params
                .filter((p) => !(isContainerDirective && ['x', 'y', 'z'].includes(p.name)))
                .filter((p) => !(needsInventoryPick && p.name === 'target' && !isEnchantDirective))
                .filter((p) => !(selected.type === 'CONTAINER_WITHDRAW' && p.name === 'target'))
                .map((p) => (
                  <div key={p.name}>{renderParamInput(p)}</div>
                ))}

              <button
                onClick={handleSendDirective}
                disabled={sendingDirective}
                className={`btn-primary w-full mt-2 ${sendingDirective ? 'opacity-60 cursor-wait' : ''}`}
              >
                {sendingDirective ? 'Sending...' : `Execute ${selected.label}`}
              </button>

              {/* Coordinated search: send WIDE_SEARCH to multiple bots */}
              {selected.type === 'WIDE_SEARCH' && allBots.length > 1 && (
                <div className="border border-mc-accent rounded p-2 mt-2 space-y-1">
                  <label className="text-xs text-mc-gold block font-medium">Coordinated search</label>
                  <p className="text-[10px] text-mc-gray">Select bots to search in parallel. Each bot gets a unique grid slice.</p>
                  <div className="flex flex-wrap gap-1">
                    {allBots.map((b) => (
                      <label key={b.name} className="flex items-center gap-1 text-[10px] text-white cursor-pointer">
                        <input
                          type="checkbox"
                          checked={coordBots.has(b.name)}
                          onChange={(e) => {
                            setCoordBots((prev) => {
                              const next = new Set(prev)
                              e.target.checked ? next.add(b.name) : next.delete(b.name)
                              return next
                            })
                          }}
                          className="accent-mc-gold"
                        />
                        {b.name}
                      </label>
                    ))}
                    <button
                      onClick={() => setCoordBots(new Set(allBots.map((b) => b.name)))}
                      className="text-[9px] px-1 text-mc-aqua hover:underline"
                    >All</button>
                    <button
                      onClick={() => setCoordBots(new Set())}
                      className="text-[9px] px-1 text-mc-gray hover:underline"
                    >None</button>
                  </div>
                  <button
                    disabled={coordBots.size < 2 || sendingCoord}
                    onClick={async () => {
                      if (coordBots.size < 2) return
                      setSendingCoord(true)
                      setStatus(`Sending coordinated search to ${coordBots.size} bots...`)
                      const botNames = Array.from(coordBots)
                      const target = params.target
                      const x = Number(params.x), y = Number(params.y), z = Number(params.z)
                      const extra: Record<string, string> = {}
                      selected.params.find((p) => p.type === 'dict')?.fields?.forEach((f) => {
                        const val = params[`extra.${f.name}`]
                        if (val !== undefined && val !== '') extra[f.name] = val
                      })
                      try {
                        const results = await Promise.all(
                          botNames.map((bot, i) =>
                            sendDirective({
                              bot,
                              directive_type: 'WIDE_SEARCH',
                              target,
                              x, y, z,
                              extra: { ...extra, bot_index: String(i), bot_count: String(botNames.length) },
                            })
                          )
                        )
                        const ok = results.filter((r) => r.ok).length
                        setStatus(`Sent to ${ok}/${botNames.length} bots`)
                      } catch (e) {
                        setStatus(`Error: ${e}`)
                      } finally {
                        setSendingCoord(false)
                      }
                    }}
                    className={`w-full text-xs px-2 py-1.5 rounded font-medium transition-colors ${
                      coordBots.size < 2 || sendingCoord
                        ? 'bg-mc-accent text-mc-gray opacity-50'
                        : 'bg-mc-gold text-black hover:opacity-90'
                    }`}
                  >
                    {sendingCoord
                      ? 'Sending...'
                      : `Search with ${coordBots.size} bot${coordBots.size !== 1 ? 's' : ''}`}
                  </button>
                </div>
              )}

              {status && (
                <p className={`text-xs mt-1 ${
                  status.startsWith('Error') ? 'text-mc-red'
                  : status.startsWith('Sending') ? 'text-mc-gold animate-pulse'
                  : 'text-mc-green'
                }`}>
                  {status}
                </p>
              )}
            </div>
          )}
        </>
      )}
    </div>
  )
}
