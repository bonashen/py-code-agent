import { useApp } from '../contexts/AppContext'
import ConnectionStatus from './ConnectionStatus'
import AgentStatus from './AgentStatus'

export default function Header() {
  const { state, connect, disconnect, clearMessages, setSettingsOpen } = useApp()
  const { status, url } = state.connection
  const hasMessages = state.messages.length > 0

  return (
    <header className="h-14 bg-surface-secondary border-b border-border flex items-center justify-between px-4">
      <div className="flex items-center gap-3">
        <h1 className="text-lg font-semibold text-slate-100">Py-Code-Agent</h1>
        <ConnectionStatus />
        <AgentStatus />
      </div>
      
      <div className="flex items-center gap-2">
        <span className="text-xs text-slate-500 hidden md:inline">{url}</span>
        {hasMessages && (
          <button 
            onClick={clearMessages}
            className="p-2 hover:bg-surface-card rounded-lg transition-colors"
            title="Clear messages"
          >
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        )}
        {status === 'disconnected' ? (
          <button onClick={connect} className="btn-primary text-sm">
            Connect
          </button>
        ) : (
          <button onClick={disconnect} className="btn-secondary text-sm">
            Disconnect
          </button>
        )}
        <button 
          onClick={() => setSettingsOpen(true)}
          className="p-2 hover:bg-surface-card rounded-lg transition-colors"
          title="Settings"
        >
          <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </button>
      </div>
    </header>
  )
}
