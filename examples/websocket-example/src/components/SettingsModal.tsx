import { useState, useEffect } from 'react'
import { useApp } from '../contexts/AppContext'
import { useLocalStorage } from '../hooks/useLocalStorage'

export default function SettingsModal() {
  const { state, dispatch, settingsOpen, setSettingsOpen } = useApp()
  const [, setSavedUrl] = useLocalStorage('ws-url', 'ws://localhost:8080/ws')
  const [savedApiKey, setSavedApiKey] = useLocalStorage('ws-api-key', '')
  const [url, setUrl] = useState(state.connection.url)
  const [apiKey, setApiKey] = useState(savedApiKey)
  const [autoReconnect, setAutoReconnect] = useState(state.connection.autoReconnect)

  useEffect(() => {
    setUrl(state.connection.url)
  }, [state.connection.url])

  useEffect(() => {
    setAutoReconnect(state.connection.autoReconnect)
  }, [state.connection.autoReconnect])

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === ',' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setSettingsOpen(!settingsOpen)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [settingsOpen, setSettingsOpen])

  const handleSave = () => {
    dispatch({ type: 'SET_CONNECTION_URL', payload: url })
    dispatch({ type: 'SET_AUTO_RECONNECT', payload: autoReconnect })
    setSavedUrl(url)
    if (apiKey !== savedApiKey) {
      setSavedApiKey(apiKey)
      dispatch({ type: 'SET_AUTH', payload: { apiKey } })
    }
    setSettingsOpen(false)
  }

  if (!settingsOpen) return null

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 animate-fade-in" onClick={() => setSettingsOpen(false)}>
      <div className="bg-surface-secondary rounded-xl p-6 w-full max-w-md border border-border shadow-2xl animate-slide-up" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-slate-100">Settings</h2>
          <button onClick={() => setSettingsOpen(false)} className="p-1 hover:bg-surface-card rounded">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              WebSocket URL
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="ws://localhost:8080/ws"
              className="input"
            />
            <p className="text-xs text-slate-500 mt-1">The WebSocket server endpoint</p>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter your API key..."
              className="input"
            />
            <p className="text-xs text-slate-500 mt-1">Your authentication key</p>
          </div>

          <div className="flex items-center justify-between">
            <div>
              <label className="text-sm font-medium text-slate-300">
                Auto Reconnect
              </label>
              <p className="text-xs text-slate-500">Automatically reconnect on disconnect</p>
            </div>
            <button
              type="button"
              onClick={() => setAutoReconnect(!autoReconnect)}
              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                autoReconnect ? 'bg-primary' : 'bg-slate-600'
              }`}
            >
              <span
                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                  autoReconnect ? 'translate-x-6' : 'translate-x-1'
                }`}
              />
            </button>
          </div>
        </div>

        <div className="flex gap-3 mt-6">
          <button onClick={() => setSettingsOpen(false)} className="flex-1 btn-secondary">
            Cancel
          </button>
          <button onClick={handleSave} className="flex-1 btn-primary">
            Save
          </button>
        </div>

        <p className="text-xs text-slate-500 mt-4 text-center">
          Press Cmd+, to open settings
        </p>
      </div>
    </div>
  )
}
