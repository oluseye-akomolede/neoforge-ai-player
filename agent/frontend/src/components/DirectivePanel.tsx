import { useState, useEffect, useMemo } from 'react'
import type { DirectiveDef, BotSnapshot, InventorySlot } from '../types'
import {
  useDirectives, useSendDirective, useSendCommand,
  useTransmuteItems, useContainers, fetchContainerContents,
  useDimensions,
  type TransmuteItem, type ContainerInfo,
} from '../hooks'

type Tier = 'l1' | 'l3' | 'l4'

export default function DirectivePanel({
  selectedBot,
  botData,
}: {
  selectedBot: string | null
  botData: BotSnapshot | null
}) {
  const directives = useDirectives()
  const sendDirective = useSendDirective()
  const sendCommand = useSendCommand()
  const transmuteItems = useTransmuteItems()
  const containers = useContainers()
  const serverDimensions = useDimensions()

  const [tier, setTier] = useState<Tier>('l1')
  const [selected, setSelected] = useState<DirectiveDef | null>(null)
  const [params, setParams] = useState<Record<string, string>>({})
  const [status, setStatus] = useState<string>('')
  const [nlInput, setNlInput] = useState('')
  const [containerContents, setContainerContents] = useState<InventorySlot[]>([])
  const [selectedContainer, setSelectedContainer] = useState<ContainerInfo | null>(null)
  const [transmuteSearch, setTransmuteSearch] = useState('')

  const handleSelect = (d: DirectiveDef) => {
    setSelected(d)
    const defaults: Record<string, string> = {}
    d.params.forEach((p) => {
      if (p.default !== undefined) defaults[p.name] = String(p.default)
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

  const isContainerDirective = selected?.type === 'CONTAINER_STORE' || selected?.type === 'CONTAINER_WITHDRAW'
  const isConjureDirective = selected?.type === 'CHANNEL'
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
            {p.options.map((opt) => (
              <option key={opt} value={opt}>{opt.replace('minecraft:', '')}</option>
            ))}
          </select>
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
          placeholder={p.label}
          className="w-full bg-mc-dark border border-mc-accent rounded px-2 py-1 text-sm focus:outline-none focus:border-mc-gold"
        />
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
                .filter((p) => !(needsInventoryPick && p.name === 'target'))
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
