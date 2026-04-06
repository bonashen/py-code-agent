export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected'

export type MessageType = 'user' | 'assistant' | 'system' | 'file'

export interface Message {
  id: string
  type: MessageType
  content: string
  timestamp: number
  metadata?: Record<string, unknown> & {
    filename?: string
    fileType?: string
    filePath?: string
  }
}

export interface ConnectionState {
  status: ConnectionStatus
  url: string
  autoReconnect: boolean
  clientId?: string
  error?: string
}

export interface AuthState {
  isAuthenticated: boolean
  token?: string
  apiKey?: string
  error?: string
}

export type AgentStatus = 'idle' | 'thinking' | 'working' | 'responding' | 'error'

export interface AppState {
  connection: ConnectionState
  auth: AuthState
  agentStatus: AgentStatus
  messages: Message[]
}

export type AppAction =
  | { type: 'SET_CONNECTION_STATUS'; payload: ConnectionStatus }
  | { type: 'SET_CONNECTION_URL'; payload: string }
  | { type: 'SET_AUTO_RECONNECT'; payload: boolean }
  | { type: 'SET_CLIENT_ID'; payload: string }
  | { type: 'SET_CONNECTION_ERROR'; payload?: string }
  | { type: 'SET_AUTH'; payload: Partial<AuthState> }
  | { type: 'SET_AGENT_STATUS'; payload: AgentStatus }
  | { type: 'ADD_MESSAGE'; payload: Message }
  | { type: 'CLEAR_MESSAGES' }

export interface AuthMessage {
  type: 'auth'
  api_key: string
  user_id?: string
  session_id?: string
  message_id?: string
}

export interface ChatMessage {
  type: 'message'
  message: string
  user_id?: string
  session_id?: string
  message_id?: string
  metadata?: Record<string, unknown>
}

export interface AuthResponse {
  type: 'auth_response'
  success: boolean
  token?: string
  session_id?: string
  message_id?: string
  error?: string
}

export interface MessageResponse {
  type: 'message'
  message: string
  channel_id: string
  message_id: string
  metadata?: Record<string, unknown>
}

export interface StatusMessage {
  type: 'status'
  status: 'started' | 'progress' | 'done' | 'error'
  channel_id: string
  message_id?: string
  metadata?: Record<string, unknown>
}

export interface FileMessage {
  type: 'file'
  file: string
  filename: string
  channel_id: string
  message_id?: string
  metadata?: Record<string, unknown>
}

export interface ErrorMessage {
  type: 'error'
  message: string
}

export type ServerMessage = AuthResponse | MessageResponse | StatusMessage | FileMessage | ErrorMessage
