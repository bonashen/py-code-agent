import { useRef, useCallback, useEffect } from 'react'
import type { AuthMessage, ChatMessage, ServerMessage } from '../types'
import { generateId } from '../utils/helpers'

interface UseWebSocketOptions {
  url: string
  autoReconnect?: boolean
  onOpen?: () => void
  onClose?: () => void
  onMessage?: (message: ServerMessage) => void
  onError?: (error: Event) => void
}

export function useWebSocket({ url, autoReconnect = true, onOpen, onClose, onMessage, onError }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttempts = useRef(0)
  const maxReconnectAttempts = 10
  const reconnectDelay = 2000

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    try {
      wsRef.current = new WebSocket(url)

      wsRef.current.onopen = () => {
        reconnectAttempts.current = 0
        onOpen?.()
      }

      wsRef.current.onclose = () => {
        onClose?.()
        if (autoReconnect && reconnectAttempts.current < maxReconnectAttempts) {
          reconnectAttempts.current++
          setTimeout(() => connect(), reconnectDelay * reconnectAttempts.current)
        }
      }

      wsRef.current.onerror = (error) => {
        onError?.(error)
      }

      wsRef.current.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as ServerMessage
          onMessage?.(data)
        } catch (error) {
          console.error('Failed to parse message:', error)
        }
      }
    } catch (error) {
      console.error('WebSocket connection error:', error)
    }
  }, [url, onOpen, onClose, onMessage, onError])

  const disconnect = useCallback(() => {
    reconnectAttempts.current = maxReconnectAttempts + 1
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const sendAuth = useCallback((apiKey: string, userId?: string, sessionId?: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message: AuthMessage = {
        type: 'auth',
        api_key: apiKey,
        user_id: userId,
        session_id: sessionId,
        message_id: generateId(),
      }
      wsRef.current.send(JSON.stringify(message))
    }
  }, [])

  const sendMessage = useCallback((content: string, userId?: string, sessionId?: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      const message: ChatMessage = {
        type: 'message',
        message: content,
        user_id: userId,
        session_id: sessionId,
        message_id: generateId(),
      }
      wsRef.current.send(JSON.stringify(message))
    }
  }, [])

  const isConnected = useCallback(() => {
    return wsRef.current?.readyState === WebSocket.OPEN
  }, [])

  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return {
    connect,
    disconnect,
    sendAuth,
    sendMessage,
    isConnected,
  }
}
