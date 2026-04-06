# Channel 工作流说明文档

## 概述

Channel 是 py-code-agent 的消息通信层，负责接收用户请求并返回响应。目前支持 WebSocket 通道。

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                     CLI Layer                           │
│  python -m py_code_agent channel websocket --port 8080│
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                 WebSocketChannel                        │
│  - get_channel_prompt()    → LLM 系统提示词           │
│  - get_channel_tools()     → send_message, send_file  │
│  - receive()              → 接收客户端消息             │
│  - send_to_client()       → 发送消息/文件给客户端    │
│  - _session_manager       → 会话管理                  │
│  - _auth_manager          → 认证管理                   │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│              WebSocketTransport                         │
│  - aiohttp WebSocket 服务端                            │
│  - _websockets 字典管理连接                            │
│  - send() / broadcast() 发送消息                      │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                   SessionManager                        │
│  - create_session()       → 创建会话                  │
│  - add_message()          → 添加消息到会话            │
│  - get_history()          → 获取会话历史              │
│  - UserSession            → 会话数据结构              │
└─────────────────────────────────────────────────────────┘
```

## 核心组件

### SessionManager (`channels/core.py`)

```python
class UserSession:
    user_id: str           # 用户 ID
    session_id: str       # 会话 ID (唯一)
    messages: List[Dict]   # 消息历史
    created_at: float     # 创建时间
    metadata: Dict        # 额外元数据

class SessionManager:
    def create_session(user_id, session_id=None) -> UserSession
    def get_session(session_id) -> Optional[UserSession]
    def add_message(session_id, role, content)
    def get_history(session_id) -> List[Dict]
    def clear_session(session_id)
```

### AuthManager (`channels/core.py`)

```python
class AuthManager:
    def verify_api_key(key) -> bool          # 验证 API 密钥
    def generate_token(user_id) -> str       # 生成令牌
    def verify_token(token) -> Optional[Dict]  # 验证令牌
    def revoke_token(token)                  # 撤销令牌
```

## 消息格式

### 客户端发送消息

#### 认证消息
```json
{
  "type": "auth",
  "api_key": "your-api-key",
  "user_id": "user123",
  "session_id": "可选的会话ID"
}
```

#### 普通消息
```json
{
  "type": "message",
  "content": "用户请求内容",
  "message_id": "可选",
  "session_id": "可选"
}
```

### 服务端返回消息

#### 认证响应
```json
{
  "type": "auth_response",
  "success": true,
  "token": "xxx",
  "session_id": "ws_session_xxx"
}
```

#### 普通消息 (type: "message")
```json
{
  "type": "message",
  "message": "响应内容",
  "channel_id": "ws_xxx",
  "session_id": "ws_session_xxx",
  "metadata": {}
}
```

#### 状态消息 (type: "status")
```json
{
  "type": "status",
  "status": "processing|thinking|done",
  "channel_id": "ws_xxx",
  "session_id": "ws_session_xxx",
  "metadata": {}
}
```

#### 文件消息 (type: "file")
```json
{
  "type": "file",
  "file": "BASE64编码的文件内容",
  "channel_id": "ws_xxx",
  "session_id": "ws_session_xxx",
  "metadata": {
    "file_path": "/tmp/hello.txt",
    "filename": "hello.txt",
    "type": "file"
  }
}
```

## Session 管理流程

```
客户端连接
     │
     ▼
┌─────────────────────────┐
│  1. 发送 auth 消息     │
│  {type:"auth",         │
│   api_key:"xxx",       │
│   user_id:"user1",     │
│   session_id:"s1"}    │
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  2. AuthManager        │
│  验证 api_key           │
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  3. SessionManager     │
│  create_session()      │
│  - 如果 session_id 存在 │
│    则复用              │
│  - 否则生成新 ID       │
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  4. 返回 auth_response │
│  {success:true,        │
│   token:"xxx",         │
│   session_id:"s1"}    │
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  5. 发送业务消息       │
│  {type:"message",      │
│   content:"xxx",       │
│   session_id:"s1"}    │
└─────────────────────────┘
     │
     ▼
┌─────────────────────────┐
│  6. SessionManager     │
│  add_message()          │
│  记录到会话历史          │
└─────────────────────────┘
```

## Channel 工具

WebSocketChannel 提供两个 LLM 可调用的工具：

### send_message
发送文本消息给用户：
- 参数：`client_id`, `content`
- 使用场景：任务执行过程中发送进度更新

### send_file
发送文件内容给用户：
- 参数：`client_id`, `file_path`
- 使用场景：任务生成文件后发送给用户
- 返回：Base64 编码的文件内容

## Channel 提示词

通过 `get_channel_prompt()` 获取，自动注入到 LLM 上下文：

```
You are a WebSocket Channel assistant.
Keep users informed during task execution:
- Use send_message to send progress updates to users while working on tasks
- Use send_file to send file content to users when files are generated

Note: Always use the current client's client_id when sending messages or files.
```

## 启动命令

```bash
# 启动 WebSocket 通道服务器
python -m py_code_agent channel websocket --port 8080 --no-auth

# 指定 API 密钥（启用认证）
python -m py_code_agent channel websocket --port 8080 --api-key key1 --api-key key2

# 指定模型
python -m py_code_agent channel websocket --port 8080 --model gpt-4
```

## 工作流程

```
1. 客户端连接 WebSocket ws://host:port/ws
2. Transport 创建 client_id (ws_xxx) 并注册到 _websockets
3. 客户端发送 auth 消息进行认证
4. SessionManager 创建或复用 session
5. 客户端发送业务消息
6. SessionManager 记录消息到会话历史
7. Channel 将消息放入队列 receive()
8. CLI 调用 agent.run() 处理请求
9. LLM 可调用 send_message/send_file 工具
10. Channel.send_to_client() 根据 metadata.type 发送对应格式
11. Transport 发送消息到客户端 WebSocket
```

## 扩展新的 Channel

1. 在 `src/py_code_agent/channels/` 创建新的 Channel 类
2. 继承 `BaseChannel` 实现：
   - `channel_type` 属性
   - `connect()` / `disconnect()`
   - `receive()` 异步生成器
   - `send()` 发送响应
3. 在 CLI 中注册 channel 命令
4. 实现 `get_channel_prompt()` 和 `get_channel_tools()`（可选）
