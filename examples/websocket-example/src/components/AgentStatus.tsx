import { useApp } from '../contexts/AppContext'

export default function AgentStatus() {
  const { state } = useApp()
  const { agentStatus, connection } = state

  if (connection.status !== 'connected') {
    return null
  }

  const statusConfig: Record<string, { color: string; text: string; show: boolean; pulse?: boolean }> = {
    idle: { color: 'text-slate-400', text: 'Ready', show: false },
    thinking: { color: 'text-yellow-400', text: 'Thinking...', show: true, pulse: true },
    working: { color: 'text-blue-400', text: 'Working...', show: true, pulse: true },
    responding: { color: 'text-green-400', text: 'Responding...', show: true, pulse: true },
    error: { color: 'text-red-400', text: 'Error', show: true },
  }

  const config = statusConfig[agentStatus]

  if (!config.show) {
    return null
  }

  return (
    <div className={`flex items-center gap-2 ${config.color}`}>
      {config.pulse && (
        <span className="relative flex h-2 w-2">
          <span className={`animate-ping absolute inline-flex h-full w-full rounded-full opacity-75 ${config.color.replace('text-', 'bg-')}`} />
          <span className={`relative inline-flex rounded-full h-2 w-2 ${config.color.replace('text-', 'bg-')}`} />
        </span>
      )}
      <span className="text-xs">{config.text}</span>
    </div>
  )
}
