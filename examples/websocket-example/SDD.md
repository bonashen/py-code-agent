# WebSocket Example Frontend Application - SDD

## 1. 项目概述

### 项目名称
WebSocket Example Frontend

### 项目类型
Web 应用程序 (React + TypeScript)

### 核心功能
为 py-code-agent WebSocket Channel 服务构建交互式前端客户端，支持：
- 实时消息收发
- 客户端认证
- 消息历史查看
- 状态指示

### 目标用户
需要通过 WebSocket 与 py-code-agent 后端服务交互的开发者/用户

---

## 2. 技术栈

| 层级 | 技术选型 |
|------|----------|
| 框架 | React 18 + TypeScript |
| 构建工具 | Vite |
| 状态管理 | React Context + useReducer |
| 样式 | Tailwind CSS |
| WebSocket | Native WebSocket API |
| HTTP Client | Native fetch |

---

## 3. UI/UX 设计

### 3.1 布局结构

```
┌─────────────────────────────────────────────────────────┐
│  Header (标题栏)                                         │
│  ┌─────────────────────────────────────────────────────┐│
│  │ Py-Code-Agent  │ 连接状态 │ Agent状态 │ [设置] [断开] ││
│  └─────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────┤
│  MessagePanel (消息面板)                                 │
│  ┌─────────────────────────────────────────────────────┐│
│  │  用户消息 (右侧对齐，蓝色)                             ││
│  │  ┌─────────────────────────────────────────────┐   ││
│  │  │ 用户输入的内容...                      10:30 │   ││
│  │  └─────────────────────────────────────────────┘   ││
│  │                                                     ││
│  │  AI回复 (左侧对齐，灰色)                              ││
│  │  ┌─────────────────────────────────────────────┐   ││
│  │  │ AI回复的内容...                        10:31 │   ││
│  │  └─────────────────────────────────────────────┘   ││
│  └─────────────────────────────────────────────────────┘│
├─────────────────────────────────────────────────────────┤
│  MessageInput (输入框)                                   │
│  ┌─────────────────────────────────────────────────────┐│
│  │ [+] 输入消息...                        [发送按钮]   ││
│  └─────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────┘

[可选] AuthModal (认证弹窗) - 未认证时显示
[可选] SettingsModal (设置弹窗) - 点击设置按钮显示
```

### 3.2 页面区域

| 区域 | 描述 |
|------|------|
| Header | 应用标题、WebSocket 连接状态指示器、Agent 状态指示器、设置按钮、连接/断开按钮 |
| MessagePanel | 消息展示区域、消息输入框 |
| AuthModal | API Key 认证弹窗 (未认证时显示) |
| SettingsModal | WebSocket URL 配置弹窗 (点击设置按钮显示) |

### 3.3 响应式断点

- **Desktop** (≥1024px): 单栏布局，消息面板全宽
- **Tablet** (768px - 1023px): 单栏布局，紧凑间距
- **Mobile** (<768px): 单栏布局，简化头部

### 3.4 视觉设计

#### 配色方案 (深色主题)

| 用途 | 颜色 | Hex |
|------|------|-----|
| 背景 (主) | 深灰蓝 | `#0f172a` |
| 背景 (次) | 暗灰 | `#1e293b` |
| 背景 (卡片) | 中灰 | `#334155` |
| 主色调 | 蓝紫 | `#6366f1` |
| 成功 | 绿色 | `#22c55e` |
| 警告 | 橙色 | `#f59e0b` |
| 错误 | 红色 | `#ef4444` |
| 文本 (主) | 白色 | `#f8fafc` |
| 文本 (次) | 灰色 | `#94a3b8` |
| 边框 | 暗边框 | `#475569` |

#### 消息气泡样式

- **用户消息**: 右侧对齐，主色调背景 `#6366f1`
- **助手消息**: 左侧对齐，次要背景 `#334155`
- **系统消息**: 居中，警告色 `#f59e0b`

#### 字体

- 主字体: `Inter`, system-ui, sans-serif

#### 间距系统

- 基础单位: 4px
- 小: 8px
- 中: 16px
- 大: 24px
- 超大: 32px

#### 动画效果

- 消息出现: fadeIn + slideUp (200ms ease-out)
- 连接状态变化: pulse 动画
- 按钮悬停: scale(1.02) + brightness 变化

### 3.5 组件列表

| 组件名 | 描述 | 状态 |
|--------|------|------|
| Header | 应用头部 | static |
| ConnectionStatus | 连接状态指示器 | connected/disconnected/connecting |
| AgentStatus | Agent 状态指示器 | idle/thinking/working/responding/error |
| MessagePanel | 消息主面板 | - |
| MessageBubble | 单条消息气泡 | user/assistant/system/file |
| MessageInput | 消息输入框 | idle/sending/disabled |
| SettingsModal | 设置弹窗 | open/closed |
| AuthModal | 认证弹窗 | open/closed |

---

## 4. 功能规范

### 4.1 核心功能

#### F1: WebSocket 连接管理

- **连接**: 用户输入 WebSocket URL，点击连接
- **断开**: 点击断开按钮断开连接
- **自动重连**: 连接断开后自动尝试重连 (最多 10 次)
- **状态显示**: 实时显示连接状态 (connected/disconnected/connecting)

#### F2: 客户端认证

- **认证方式**: API Key 认证
- **认证流程**:
  1. 未认证状态下提示用户输入 API Key
  2. 发送 auth 消息到服务器
  3. 根据服务器响应显示认证结果
- **认证持久化**: API Key 存储在 localStorage

#### F3: 消息收发

- **发送消息**: 在输入框输入文字，按 Enter 或点击发送按钮
- **接收消息**: 实时接收服务器推送的消息
- **消息类型**:
  - text: 文本消息
  - status: 状态消息
  - file: 文件消息 (根据文件类型显示不同图标，点击下载保存到本地)

#### F4: 消息历史

- **本地存储**: 消息历史存储在内存中 (当前会话)
- **清除历史**: 提供清除消息按钮

### 4.2 用户交互流程

```
[打开应用]
    │
    ▼
[检查 localStorage 是否有 API Key]
    │
    ├─ 有 → 自动发起认证
    │       │
    │       ├─ 成功 → 进入主界面，显示连接状态
    │       └─ 失败 → 显示认证弹窗
    │
    └─ 无 → 显示认证弹窗
              │
              ▼
[用户输入 API Key + 连接地址]
              │
              ▼
[点击连接]
              │
              ▼
[发送 auth 消息]
              │
              ├─ 认证成功 → 进入主界面，显示连接状态
              └─ 认证失败 → 显示错误提示
              │
              ▼
[用户可以发送消息]
              │
              ▼
[接收并显示服务器响应]
```

---

## 5. 数据结构

### 5.1 WebSocket 消息格式 (客户端 → 服务器)

```typescript
// 认证消息
interface AuthMessage {
  type: 'auth';
  api_key: string;
  user_id?: string;
  session_id?: string;
  message_id?: string;
}

// 文本消息
interface ChatMessage {
  type: 'message';
  message: string;
  user_id?: string;
  session_id?: string;
  message_id?: string;
  metadata?: Record<string, unknown>;
}
```

### 5.2 WebSocket 消息格式 (服务器 → 客户端)

```typescript
// 认证响应
interface AuthResponse {
  type: 'auth_response';
  success: boolean;
  token?: string;
  session_id?: string;
  message_id?: string;
  error?: string;
}

// 消息响应
interface MessageResponse {
  type: 'message';
  message: string;
  channel_id: string;
  message_id: string;
  metadata?: Record<string, unknown>;
}

// 状态消息
interface StatusMessage {
  type: 'status';
  status: 'started' | 'progress' | 'done' | 'error';
  channel_id: string;
  message_id?: string;
  metadata?: Record<string, unknown>;
}

// 文件消息
interface FileMessage {
  type: 'file';
  file: string;  // Base64 编码
  filename: string;
  channel_id: string;
  message_id?: string;
  metadata?: Record<string, unknown>;
}

// 错误消息
interface ErrorMessage {
  type: 'error';
  message: string;
}

// 服务器消息联合类型
type ServerMessage = AuthResponse | MessageResponse | StatusMessage | FileMessage | ErrorMessage;
```

### 5.3 前端状态模型

```typescript
// 连接状态
type ConnectionStatus = 'disconnected' | 'connecting' | 'connected';

// 消息类型
type MessageType = 'user' | 'assistant' | 'system' | 'file';

// Agent 状态
type AgentStatus = 'idle' | 'thinking' | 'working' | 'responding' | 'error';

// 消息结构
interface Message {
  id: string;
  type: MessageType;
  content: string;
  timestamp: number;
  metadata?: Record<string, unknown> & {
    filename?: string;
    fileType?: string;
    filePath?: string;
  };
}

// 连接状态结构
interface ConnectionState {
  status: ConnectionStatus;
  url: string;
  autoReconnect: boolean;
  clientId?: string;
  error?: string;
}

// 认证状态结构
interface AuthState {
  isAuthenticated: boolean;
  token?: string;
  apiKey?: string;
  error?: string;
}

// 应用完整状态
interface AppState {
  connection: ConnectionState;
  auth: AuthState;
  agentStatus: AgentStatus;
  messages: Message[];
}
```

---

## 6. 组件层级

```
App
├── Header
│   ├── ConnectionStatus (连接状态指示器)
│   ├── AgentStatus (AI状态指示器)
│   └── [设置按钮] → SettingsModal
│
├── MessagePanel
│   ├── MessageBubble (消息气泡) × N
│   │   ├── user (右侧，蓝色)
│   │   ├── assistant (左侧，灰色)
│   │   └── file (文件消息)
│   └── MessageInput (输入框)
│
├── AuthModal (条件渲染: 未认证且已连接)
│   └── API Key 输入表单
│
└── SettingsModal (条件渲染: 点击设置)
    └── WebSocket URL 配置
```

---

## 7. API 参考

### 7.1 useWebSocket Hook

```typescript
interface UseWebSocketOptions {
  url: string;
  autoReconnect?: boolean;
  onOpen?: () => void;
  onClose?: () => void;
  onMessage?: (message: ServerMessage) => void;
  onError?: (error: Event) => void;
}

function useWebSocket(options: UseWebSocketOptions): {
  connect: () => void;
  disconnect: () => void;
  sendAuth: (apiKey: string, userId?: string, sessionId?: string) => void;
  sendMessage: (content: string, userId?: string, sessionId?: string) => void;
  isConnected: () => boolean;
}
```

---

## 8. 验收标准

### 8.1 连接功能
- [ ] 能够通过 WebSocket URL 成功连接服务器
- [ ] 断开按钮能够断开连接
- [ ] 连接状态正确显示 (connected/disconnected/connecting)
- [ ] 自动重连机制正常工作

### 8.2 认证功能
- [ ] 未认证时显示认证弹窗
- [ ] 能够输入 API Key 并发起认证
- [ ] 认证成功/失败有明确的提示
- [ ] API Key 能够保存到 localStorage

### 8.3 消息功能
- [ ] 能够发送文本消息
- [ ] 能够接收并显示服务器响应
- [ ] 用户消息和助手消息样式正确区分
- [ ] 文件消息能够正确显示和下载

### 8.4 状态指示
- [ ] Agent 状态 (idle/thinking/working/responding/error) 正确显示
- [ ] 连接状态指示器正确显示当前状态