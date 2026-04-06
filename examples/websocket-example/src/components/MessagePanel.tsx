import { useEffect, useRef } from 'react'
import { useApp } from '../contexts/AppContext'
import MessageBubble from './MessageBubble'
import MessageInput from './MessageInput'

export default function MessagePanel() {
  const { state } = useApp()
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const { messages } = state

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  return (
    <main className="flex-1 flex flex-col overflow-hidden bg-surface-primary">
      <div className="flex-1 overflow-y-auto p-4">
        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <div className="text-4xl mb-3">💬</div>
              <p className="text-slate-400">No messages yet</p>
              <p className="text-slate-500 text-sm mt-1">Send a message to start the conversation</p>
            </div>
          </div>
        ) : (
          <div className="space-y-1">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>
      <MessageInput />
    </main>
  )
}
