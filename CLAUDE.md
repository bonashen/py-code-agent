# py-code-agent 开发规范

## Git Worktree 工作流

所有功能开发必须通过 **git worktree** 在独立分支工作区中进行，禁止直接在工作目录（`master`）上开发。

### 工作区结构

- **`.worktrees/`** — 项目本地目录，存放各功能分支的独立工作区
- **主工作目录 (`/`)** — 仅用于临时操作、紧急修复、CI 验证，禁止直接在其上开发新功能

### 分支命名

| 类型 | 命名格式 | 示例 |
|------|----------|------|
| 功能开发 | `feat/<short-description>` | `feat/skill-self-healing` |
| Bug 修复 | `fix/<short-description>` | `fix/docx-workflow` |
| 重构 | `refactor/<short-description>` | `refactor/plugin-system` |
| 实验 | `explore/<short-description>` | `explore/new-planning-llm` |

### 开发流程

1. **创建 worktree**：在 `.worktrees/` 下创建功能分支
   ```bash
   git worktree add .worktrees/feat/skill-self-healing -b feat/skill-self-healing
   cd .worktrees/feat/skill-self-healing
   ```

2. **开发 + 测试**：在 worktree 中实现功能，运行测试验证

3. **合并回 master**：
   - 通过 PR 合并（推荐）
   - 或直接合并：`git checkout master && git merge .worktrees/feat/name`

4. **清理 worktree**：
   ```bash
   git worktree remove .worktrees/feat/name
   git branch -d feat/name
   ```

### 特殊情况

- **紧急修复**：可直接在 master 上修改，但事后必须补充 PR
- **CI 验证**：在 master 上运行 `uv run pytest` 确认无回归后再推

## 代码规范

- Python 类型注解必须完整，禁止 `as any`
- 错误处理禁止空 catch：`except: {}`
- 测试覆盖率覆盖所有新增代码
- 所有插件工具必须注册 schema-aware 参数验证

## 架构原则

- **PlanPlugin** 是通用工具，不包含 skill-specific 逻辑
- **自愈机制** 属于 master agent 通用能力，skill-specific 部分放在对应 skill plugin
- **Plugin 通信** 通过 hook 接口，不直接依赖内部状态
