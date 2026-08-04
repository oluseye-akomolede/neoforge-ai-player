import { useMemo, useState } from 'react'
import { useSendCommand, useBroadcast, useStopBot, useHoldings } from '../hooks'

export default function CommandBar({ selectedBot }: { selectedBot: string | null }) {
  const [input, setInput] = useState('')
  const sendCommand = useSendCommand()
  const broadcast = useBroadcast()
  const stopBot = useStopBot()
  const [holdings] = useHoldings(selectedBot)

  // Item chips: the bot's actual holdings, so commands about storing or
  // using items name things the bot really has instead of guesses.
  const chips = useMemo(() => holdings.slice(0, 10), [holdings])
  const mentionsItems = /\b(store|stow|stash|vault|withdraw|drop|craft|build|use|give)\b/i.test(input)

  const insertItem = (item: string) => {
    const short = item.replace('minecraft:', '')
    setInput((prev) => (prev.trim() ? `${prev.replace(/\s+$/, '')} ${short}` : short))
  }

  const handleSend = async () => {
    const msg = input.trim()
    if (!msg) return
    if (selectedBot) {
      await sendCommand(selectedBot, msg)
    } else {
      await broadcast(msg)
    }
    setInput('')
  }

  const handleStop = async () => {
    if (selectedBot) {
      await stopBot(selectedBot)
    }
  }

  return (
    <div className="panel space-y-2">
    <div className="flex gap-2 items-center">
      <span className="text-xs text-mc-gray whitespace-nowrap">
        {selectedBot ? (
          <>
            To: <span className="text-mc-gold">{selectedBot}</span>
          </>
        ) : (
          'Broadcast all'
        )}
      </span>
      <input
        value={input}
        onChange={(e) => setInput(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && handleSend()}
        placeholder="Type a command..."
        className="flex-1 bg-mc-dark border border-mc-accent rounded px-3 py-1.5 text-sm
                   focus:outline-none focus:border-mc-gold"
      />
      <button onClick={handleSend} className="btn-primary">
        Send
      </button>
      {selectedBot && (
        <button onClick={handleStop} className="btn-danger">
          Stop
        </button>
      )}
    </div>

    {selectedBot && chips.length > 0 && (mentionsItems || input.trim() === '') && (
      <div className="flex flex-wrap gap-1 items-center">
        <span className="text-[10px] text-mc-gray mr-1">
          {selectedBot} holds:
        </span>
        {chips.map((h) => (
          <button
            key={h.item}
            onClick={() => insertItem(h.item)}
            title={`${h.carried} carried · ${h.vault} vault — click to add to command`}
            className="text-[10px] px-1.5 py-0.5 rounded bg-mc-accent hover:bg-mc-gold
                       hover:text-mc-dark transition-colors text-mc-gray"
          >
            {(h.name || h.item).replace('minecraft:', '')}
            <span className="ml-1 text-white">{h.count}</span>
            {h.vault > 0 && <span className="ml-0.5 text-mc-purple">·v</span>}
          </button>
        ))}
      </div>
    )}
    </div>
  )
}
