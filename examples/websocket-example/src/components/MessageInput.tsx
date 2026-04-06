import { useState, useRef, useEffect } from 'react'
import { useApp } from '../contexts/AppContext'

export default function MessageInput() {
  const { sendMessage, state } = useApp()
  const [input, setInput] = useState('')
  const [isSending, setIsSending] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const isDisabled = state.connection.status !== 'connected'

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 120)}px`
    }
  }, [input])

  const handleSubmit = async () => {
    if (!input.trim() || isDisabled || isSending) return

    setIsSending(true)
    try {
      sendMessage(input.trim())
      setInput('')
    } finally {
      setIsSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="border-t border-border p-4 bg-surface-secondary">
      <div className="flex items-end gap-3">
        <div className="flex-1 relative">
          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={isDisabled ? 'Connect and authenticate first...' : 'Type a message...'}
            disabled={isDisabled}
            rows={1}
            className="input resize-none pr-12 min-h-[44px] max-h-[120px]"
          />
        </div>
        <button
          onClick={handleSubmit}
          disabled={!input.trim() || isDisabled || isSending}
          className="btn-primary p-3 disabled:opacity-50"
        >
          {isSending ? (
            <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
            </svg>
          )}
        </button>
      </div>
      <p className="text-xs text-slate-500 mt-2">
        Press Enter to send, Shift+Enter for new line
      </p>
    </div>
  )
}
