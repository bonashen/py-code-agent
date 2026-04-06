import { useState, useEffect } from 'react'
import { useApp } from '../contexts/AppContext'
import { useLocalStorage } from '../hooks/useLocalStorage'

export default function AuthModal() {
  const { state, dispatch } = useApp()
  const [savedApiKey, setSavedApiKey] = useLocalStorage('ws-api-key', '')
  const [apiKey, setApiKey] = useState(savedApiKey)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    if (savedApiKey) {
      setApiKey(savedApiKey)
    }
  }, [savedApiKey])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!apiKey.trim()) return

    setIsLoading(true)
    setSavedApiKey(apiKey.trim())
    dispatch({ type: 'SET_AUTH', payload: { apiKey: apiKey.trim(), error: undefined } })
    setTimeout(() => setIsLoading(false), 500)
  }

  const handleSkipAuth = () => {
    dispatch({ type: 'SET_AUTH', payload: { isAuthenticated: true, apiKey: '', error: undefined } })
  }

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 animate-fade-in">
      <div className="bg-surface-secondary rounded-xl p-6 w-full max-w-md border border-border shadow-2xl animate-slide-up">
        <div className="text-center mb-6">
          <div className="w-12 h-12 bg-primary/20 rounded-full flex items-center justify-center mx-auto mb-3">
            <svg className="w-6 h-6 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-slate-100">Authentication Required</h2>
          <p className="text-slate-400 text-sm mt-1">Enter your API key to authenticate</p>
        </div>

        {state.auth.error && (
          <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded-lg">
            <p className="text-red-400 text-sm">{state.auth.error}</p>
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-300 mb-2">
              API Key
            </label>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder="Enter your API key..."
              className="input"
              autoFocus
            />
          </div>

          <div className="flex gap-3">
            <button
              type="button"
              onClick={() => dispatch({ type: 'SET_CONNECTION_STATUS', payload: 'disconnected' })}
              className="flex-1 btn-secondary"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!apiKey.trim() || isLoading}
              className="flex-1 btn-primary disabled:opacity-50"
            >
              {isLoading ? 'Authenticating...' : 'Authenticate'}
            </button>
          </div>

          <button
            type="button"
            onClick={handleSkipAuth}
            className="w-full mt-3 text-sm text-slate-400 hover:text-slate-300 transition-colors"
          >
            Connect without authentication
          </button>
        </form>
      </div>
    </div>
  )
}
