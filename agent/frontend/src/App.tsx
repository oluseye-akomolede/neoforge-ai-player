import { useState, Component } from 'react'
import type { ReactNode } from 'react'
import { useServerState, useEvents } from './hooks'
import BotCard from './components/BotCard'
import BotDetail from './components/BotDetail'
import CommandBar from './components/CommandBar'
import DirectivePanel from './components/DirectivePanel'
import EventLog from './components/EventLog'
import TaskBoard, { useTasks } from './components/TaskBoard'
import WorldMap from './components/WorldMap'
import DataBrowser from './components/DataBrowser'

class AppErrorBoundary extends Component<
  { children: ReactNode },
  { error: string | null }
> {
  state = { error: null as string | null }
  static getDerivedStateFromError(e: Error) { return { error: e.message } }
  componentDidCatch(e: Error) { console.error('[AppErrorBoundary]', e) }
  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-mc-dark text-white flex items-center justify-center">
          <div className="text-center p-6">
            <div className="text-mc-red text-lg mb-2">Something went wrong</div>
            <div className="text-mc-gray text-sm mb-4">{this.state.error}</div>
            <button
              onClick={() => this.setState({ error: null })}
              className="px-4 py-2 bg-mc-gold text-black rounded font-medium"
            >
              Retry
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

function AppInner() {
  const state = useServerState()
  const events = useEvents()
  const [selectedBot, setSelectedBot] = useState<string | null>(null)
  const [centerBot, setCenterBot] = useState<string | null>(null)

  const [tasks, refreshTasks] = useTasks()
  const bots = state ? Object.values(state.bots) : []
  const activeBotData = selectedBot && state?.bots[selectedBot] ? state.bots[selectedBot] : null

  const handleBotSelect = (name: string) => {
    const next = selectedBot === name ? null : name
    setSelectedBot(next)
    setCenterBot(next)
  }

  return (
    <div className="min-h-screen bg-mc-dark text-white">
      {/* Header */}
      <header className="border-b border-mc-accent px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-bold text-mc-gold">AI Bot C2</h1>
          <span className="text-xs text-mc-gray">
            {state ? `${bots.length} bots online` : 'Connecting...'}
          </span>
        </div>
        <span className={`status-dot ${state ? 'bg-mc-green' : 'bg-mc-red'}`} />
      </header>

      {!state ? (
        <div className="flex items-center justify-center h-96">
          <div className="text-center">
            <div className="text-mc-gold text-xl mb-2">Connecting to agent...</div>
            <div className="text-mc-gray text-sm">
              Make sure the agent is running with DASHBOARD_ENABLED=true
            </div>
          </div>
        </div>
      ) : (
        <div className="flex flex-col lg:flex-row gap-4 p-4">
          {/* Left: Bot list + Map */}
          <div className="lg:w-96 shrink-0 space-y-4">
            <WorldMap
              bots={bots}
              selectedBot={selectedBot}
              onSelect={handleBotSelect}
              onCenterBot={centerBot}
            />
            <div className="space-y-2">
              {bots.map((bot) => (
                <BotCard
                  key={bot.name}
                  bot={bot}
                  selected={bot.name === selectedBot}
                  onClick={() => handleBotSelect(bot.name)}
                />
              ))}
            </div>
          </div>

          {/* Center: Command + Detail + Events */}
          <div className="flex-1 space-y-4 min-w-0">
            <CommandBar selectedBot={selectedBot} />
            {activeBotData && <BotDetail bot={activeBotData} />}
            <EventLog events={events} />
          </div>

          {/* Right: Directives + Tasks + Data */}
          <div className="lg:w-80 shrink-0 space-y-4">
            <DirectivePanel selectedBot={selectedBot} botData={activeBotData} allBots={bots} />
            <TaskBoard tasks={tasks} onRefresh={refreshTasks} />
            <DataBrowser selectedBot={selectedBot} />
          </div>
        </div>
      )}
    </div>
  )
}

export default function App() {
  return (
    <AppErrorBoundary>
      <AppInner />
    </AppErrorBoundary>
  )
}
