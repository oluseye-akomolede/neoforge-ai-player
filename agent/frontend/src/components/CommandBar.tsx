import { useState } from 'react'
import { useSendCommand, useBroadcast, useStopBot } from '../hooks'

export default function CommandBar({ selectedBot }: { selectedBot: string | null }) {
  const [input, setInput] = useState('')
  const sendCommand = useSendCommand()
  const broadcast = useBroadcast()
  const stopBot = useStopBot()

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
    <div className="panel flex gap-2 items-center">
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
  )
}
