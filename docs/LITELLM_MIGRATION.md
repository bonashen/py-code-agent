# SDD 文档更新说明 - LiteLLM 集成

## 更新概要

已将 SDD 文档中的 LLM Provider 架构从自定义 Provider 实现更新为使用 **LiteLLM** 作为统一的 LLM 接入层。

## 主要变更

### 1. LLM Provider 架构

**旧架构**:
- 自定义 `BaseLLMProvider` 抽象基类
- 为每个 Provider (OpenAI、Anthropic 等) 编写独立实现
- 需要维护多个 Provider 的特定代码

**新架构**:
- 使用 **LiteLLM** 作为统一接入层
- 单一 `LiteLLMProvider` 类支持 100+ LLM
- 通过 LiteLLM 自动处理不同 Provider 的差异

### 2. 技术栈更新

```diff
| 组件 | 旧方案 | 新方案 |
|------|--------|--------|
| LLM 接入 | 自定义 Provider | **LiteLLM** |
| 支持 Provider 数量 | 3-5 个 | **100+** |
| Fallback 机制 | 需自行实现 | **内置支持** |
| 负载均衡 | 需自行实现 | **内置支持** |
| 成本追踪 | 需自行实现 | **内置支持** |
```

### 3. 代码示例

**旧方式 - 自定义 OpenAI Provider**:
```python
class OpenAIProvider(BaseLLMProvider):
    def __init__(self, config):
        import openai
        self.client = openai.AsyncOpenAI(...)
    
    async def complete(self, messages, ...):
        response = await self.client.chat.completions.create(...)
        # 手动解析响应
        ...
```

**新方式 - LiteLLM Provider**:
```python
class LiteLLMProvider:
    def __init__(self, config):
        self.model = config.get("model", "gpt-4")
        # LiteLLM 自动处理不同 Provider
    
    async def complete(self, messages, ...):
        response = await litellm.acompletion(
            model=self.model,
            messages=messages,
            ...
        )
        # 统一格式的响应
        ...
```

### 4. 依赖更新

**requirements.txt 关键依赖**:
```
# Core - LLM
litellm>=1.0.0  # Unified LLM API for 100+ providers
```

**pyproject.toml 依赖**:
```toml
dependencies = [
    "litellm>=1.0.0",
    ...
]
```

### 5. 支持的 Provider 列表

通过 LiteLLM，Pi Code Agent 现在原生支持：

| Provider | 示例模型 | 环境变量 |
|----------|---------|---------|
| OpenAI | gpt-4, gpt-4-turbo | `OPENAI_API_KEY` |
| Anthropic | claude-3-opus, claude-3-sonnet | `ANTHROPIC_API_KEY` |
| Azure OpenAI | azure/gpt-4 | `AZURE_API_KEY`, `AZURE_API_BASE` |
| Cohere | command-r | `COHERE_API_KEY` |
| Ollama | ollama/llama2 | 本地运行 |
| Mistral | mistral/medium | `MISTRAL_API_KEY` |
| Groq | groq/llama2-70b | `GROQ_API_KEY` |
| Bedrock | bedrock/claude-3 | AWS 凭证 |
| ... | ... | ... |

完整列表: https://docs.litellm.ai/docs/providers

## 优势总结

### 对开发者
- ✅ 减少 Provider 适配代码 80%+
- ✅ 自动获得新 Provider 支持
- ✅ 统一的错误处理和重试机制
- ✅ 内置的成本追踪和日志

### 对用户
- ✅ 支持 100+ LLM，自由选择
- ✅ 自动 Fallback，提高可用性
- ✅ 负载均衡，优化性能
- ✅ 成本透明，便于管理

### 对项目
- ✅ 降低维护成本
- ✅ 更快支持新模型
- ✅ 更好的生态兼容性
- ✅ 专注核心功能开发

## 后续计划

1. **Phase 1**: 完成 LiteLLM Provider 核心实现
2. **Phase 2**: 添加更多 LiteLLM 高级功能 (Router、Proxy)
3. **Phase 3**: 实现自定义 LiteLLM Callback 用于日志和监控
4. **Phase 4**: 与 LiteLLM Enterprise 功能集成 (SSO、审计)

## 参考链接

- [LiteLLM 文档](https://docs.litellm.ai/)
- [LiteLLM GitHub](https://github.com/BerriAI/litellm)
- [支持的 Providers](https://docs.litellm.ai/docs/providers)
- [LiteLLM Router](https://docs.litellm.ai/docs/routing)
- [LiteLLM Proxy](https://docs.litellm.ai/docs/simple_proxy)

---

**更新日期**: 2025-01-19  
**版本**: 1.1.0  
**作者**: AI Assistant
