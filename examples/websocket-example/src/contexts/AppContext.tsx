import { createContext, useContext, useReducer, useEffect, useCallback, useState } from 'react'
import type { AppState, AppAction, Message, AuthResponse, MessageResponse, StatusMessage, FileMessage, ErrorMessage } from '../types'
import { useLocalStorage } from '../hooks/useLocalStorage'
import { useWebSocket } from '../hooks/useWebSocket'
import { generateId } from '../utils/helpers'

const initialState: AppState = {
  connection: {
    status: 'disconnected',
    url: 'ws://localhost:8080/ws',
    autoReconnect: true,
  },
  auth: {
    isAuthenticated: false,
  },
  agentStatus: 'idle',
  messages: [],
}

function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_CONNECTION_STATUS':
      return { ...state, connection: { ...state.connection, status: action.payload, error: undefined } }
    case 'SET_CONNECTION_URL':
      return { ...state, connection: { ...state.connection, url: action.payload } }
    case 'SET_AUTO_RECONNECT':
      return { ...state, connection: { ...state.connection, autoReconnect: action.payload } }
    case 'SET_CLIENT_ID':
      return { ...state, connection: { ...state.connection, clientId: action.payload } }
    case 'SET_CONNECTION_ERROR':
      return { ...state, connection: { ...state.connection, error: action.payload } }
    case 'SET_AUTH':
      return { ...state, auth: { ...state.auth, ...action.payload } }
    case 'SET_AGENT_STATUS':
      return { ...state, agentStatus: action.payload }
    case 'ADD_MESSAGE':
      return { ...state, messages: [...state.messages, action.payload] }
    case 'CLEAR_MESSAGES':
      return { ...state, messages: [] }
    default:
      return state
  }
}

interface AppContextValue {
  state: AppState
  dispatch: React.Dispatch<AppAction>
  connect: () => void
  disconnect: () => void
  sendMessage: (content: string) => void
  clearMessages: () => void
  settingsOpen: boolean
  setSettingsOpen: (open: boolean) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [savedUrl, setSavedUrl] = useLocalStorage('ws-url', 'ws://localhost:8080/ws')
  const [savedApiKey] = useLocalStorage('ws-api-key', '')
  const [savedMessagesRaw, setSavedMessages] = useLocalStorage<Message[] | Record<string, Message[]>>('ws-messages', [])
  
  // Handle migration from old object format to array format
  const savedMessages = Array.isArray(savedMessagesRaw) 
    ? savedMessagesRaw 
    : Object.values(savedMessagesRaw || {}).flat()

  const [state, dispatch] = useReducer(appReducer, {
    ...initialState,
    connection: { ...initialState.connection, url: savedUrl },
    messages: savedMessages,
    auth: { isAuthenticated: false, apiKey: savedApiKey },
  })
  const [settingsOpen, setSettingsOpen] = useState(false)

  const handleMessage = useCallback((message: AuthResponse | MessageResponse | StatusMessage | FileMessage | ErrorMessage) => {
    if (message.type === 'auth_response') {
      dispatch({ 
        type: 'SET_AUTH', 
        payload: { 
          isAuthenticated: message.success, 
          token: message.token,
          error: message.error 
        } 
      })
    } else if (message.type === 'message') {
      const msg: Message = {
        id: message.message_id || generateId(),
        type: 'assistant',
        content: (message as MessageResponse).message || (message as any).content || '',
        timestamp: Date.now(),
        metadata: message.metadata,
      }
      dispatch({ type: 'ADD_MESSAGE', payload: msg })
      dispatch({ type: 'SET_AGENT_STATUS', payload: 'idle' })
    } else if (message.type === 'status') {
      const statusMap: Record<string, 'idle' | 'thinking' | 'working' | 'responding' | 'error'> = {
        started: 'thinking',
        processing: 'working',
        progress: 'working',
        thinking: 'thinking',
        done: 'idle',
        error: 'error',
      }
      const newStatus = statusMap[message.status] || 'idle'
      dispatch({ type: 'SET_AGENT_STATUS', payload: newStatus })
    } else if (message.type === 'file') {
      const msg: Message = {
        id: message.message_id || generateId(),
        type: 'file',
        content: message.file,
        timestamp: Date.now(),
        metadata: {
          filename: (message as any).filename || message.metadata?.filename as string || 'file',
          fileType: ((message as any).filename || message.metadata?.filename as string)?.split('.').pop(),
        },
      }
      dispatch({ type: 'ADD_MESSAGE', payload: msg })
    } else if (message.type === 'error') {
      const msg: Message = {
        id: generateId(),
        type: 'system',
        content: `Error: ${message.message}`,
        timestamp: Date.now(),
      }
      dispatch({ type: 'ADD_MESSAGE', payload: msg })
    }
  }, [])

  const { connect: wsConnect, disconnect: wsDisconnect, sendAuth, sendMessage: wsSendMessage } = useWebSocket({
    url: state.connection.url,
    autoReconnect: state.connection.autoReconnect,
    onOpen: () => dispatch({ type: 'SET_CONNECTION_STATUS', payload: 'connected' }),
    onClose: () => dispatch({ type: 'SET_CONNECTION_STATUS', payload: 'disconnected' }),
    onMessage: handleMessage,
    onError: () => dispatch({ type: 'SET_CONNECTION_ERROR', payload: 'Connection error' }),
  })

  useEffect(() => {
    setSavedUrl(state.connection.url)
  }, [state.connection.url, setSavedUrl])

  useEffect(() => {
    setSavedMessages(state.messages)
  }, [state.messages, setSavedMessages])

  const connect = useCallback(() => {
    dispatch({ type: 'SET_CONNECTION_STATUS', payload: 'connecting' })
    wsConnect()
    const apiKey = state.auth.apiKey
    if (apiKey) {
      setTimeout(() => sendAuth(apiKey), 500)
    }
  }, [wsConnect, sendAuth, state.auth.apiKey])

  const disconnect = useCallback(() => {
    wsDisconnect()
    dispatch({ type: 'SET_AUTH', payload: { isAuthenticated: false, token: undefined } })
  }, [wsDisconnect])

  const sendMessage = useCallback((content: string) => {
    const msg: Message = {
      id: generateId(),
      type: 'user',
      content,
      timestamp: Date.now(),
    }
    dispatch({ type: 'ADD_MESSAGE', payload: msg })
    wsSendMessage(content)
  }, [wsSendMessage])

  const clearMessages = useCallback(() => {
    dispatch({ type: 'CLEAR_MESSAGES' })
  }, [])

  return (
    <AppContext.Provider value={{ state, dispatch, connect, disconnect, sendMessage, clearMessages, settingsOpen, setSettingsOpen }}>
      {children}
    </AppContext.Provider>
  )
}

export function useApp() {
  const context = useContext(AppContext)
  if (!context) {
    throw new Error('useApp must be used within AppProvider')
  }
  return context
}
