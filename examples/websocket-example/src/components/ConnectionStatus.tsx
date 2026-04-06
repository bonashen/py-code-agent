import { useApp } from '../contexts/AppContext'

export default function ConnectionStatus() {
  const { state } = useApp()
  const { status } = state.connection

  const statusConfig = {
    connected: { color: 'bg-green-500', text: 'Connected', pulse: false },
    connecting: { color: 'bg-yellow-500', text: 'Connecting...', pulse: true },
    disconnected: { color: 'bg-red-500', text: 'Disconnected', pulse: false },
  }

  const config = statusConfig[status]

  return (
    <div className="flex items-center gap-2">
      <div className={`w-2.5 h-2.5 rounded-full ${config.color} ${config.pulse ? 'animate-pulse-slow' : ''}`} />
      <span className="text-sm text-slate-400">{config.text}</span>
    </div>
  )
}
