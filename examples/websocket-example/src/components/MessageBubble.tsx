import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Message } from '../types'
import { formatTimestamp, getFileIcon, decodeBase64ToBlob, downloadFile } from '../utils/helpers'

interface MessageBubbleProps {
  message: Message
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.type === 'user'
  const isSystem = message.type === 'system'
  const isFile = message.type === 'file'

  if (isSystem) {
    return (
      <div className="flex justify-center my-2">
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-full px-4 py-1.5">
          <p className="text-xs text-yellow-500">{message.content}</p>
        </div>
      </div>
    )
  }

  if (isFile) {
    const filename = message.metadata?.filename as string || 'file'
    const icon = getFileIcon(filename)
    
    const handleDownload = () => {
      try {
        const blob = decodeBase64ToBlob(message.content, filename)
        downloadFile(blob, filename)
      } catch (error) {
        console.error('Failed to download file:', error)
      }
    }

    return (
      <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3 animate-fade-in`}>
        <div className={`
          max-w-[70%] rounded-2xl px-4 py-3
          ${isUser ? 'bg-primary text-white' : 'bg-surface-card text-slate-100'}
        `}>
          <div className="flex items-center gap-3">
            <span className="text-2xl">{icon}</span>
            <div className="flex-1 min-w-0">
              <p className="font-medium text-sm truncate">{filename}</p>
              <p className="text-xs opacity-60">Click to download</p>
            </div>
            <button
              onClick={handleDownload}
              className={`
                p-2 rounded-lg transition-colors
                ${isUser ? 'hover:bg-white/20' : 'hover:bg-primary/20'}
              `}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
            </button>
          </div>
          <p className="text-xs opacity-50 mt-2">{formatTimestamp(message.timestamp)}</p>
        </div>
      </div>
    )
  }

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-3 animate-fade-in`}>
      <div className={`
        max-w-[70%] rounded-2xl px-4 py-3
        ${isUser ? 'bg-primary text-white' : 'bg-surface-card text-slate-100'}
      `}>
        <div className="prose prose-invert prose-sm max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {message.content}
          </ReactMarkdown>
        </div>
        <p className={`text-xs mt-1.5 ${isUser ? 'text-white/50' : 'text-slate-500'}`}>
          {formatTimestamp(message.timestamp)}
        </p>
      </div>
    </div>
  )
}
