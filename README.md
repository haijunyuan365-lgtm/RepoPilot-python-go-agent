# RepoPilot

RepoPilot is an AI software engineering agent platform.

RepoPilot 面向软件研发场景，计划让用户绑定 Git Repository 后通过自然语言发起分析、修复、测试与 Review 任务，并交付带验证证据、可审批、可提交的研发结果。

**当前已完成治理基线和 Phase 1.1–1.4，并实现 Phase 1.5 的精确文本检索工具等待验收；写入/测试工具、LLM Provider 与平台服务仍未实现。**

## Problem

生成一段代码并不能证明研发任务完成。真实研发还需要理解仓库、定位文件、修改代码、执行测试、读取失败输出继续修复，并审查 Diff、控制外部副作用和保留执行证据。

## Vision

长期闭环：Analyze → Search → Read → Modify → Test → Observe → Retry → Review → Evaluate → Approve → Final Result。审批在对应高风险动作前执行，不仅是最终展示步骤。

最终希望演示：用户创建 Coding Task，Agent 在真实仓库中修改代码、经历测试失败并修复、通过 Review / Eval，再请求 git push 的 Human Approval；用户批准后执行并完成任务。过程可持久化、实时展示、取消、超时、追踪、评测和审计。这些都是计划能力。

## Architecture Overview

- **Go Control Plane**：Task / Service Orchestration、平台状态、API、并发、事件、安全与执行环境。
- **Python Agent Runtime**：唯一主要 Agent Loop、LLM 推理、规划、工具选择、RAG、Memory、Review 与 Eval。
- **长期基础设施**：RabbitMQ 传递异步任务/事件；Tool Gateway 先 HTTP 后按需 gRPC；SSE 推送前端事件；PostgreSQL + pgvector 持久存储与检索；Redis 提供按需热状态；Docker Sandbox + Git Worktree 隔离执行；OpenTelemetry 追踪。

以上长期架构整体尚未实现；当前只有 Phase 1 的模型、Tool Registry 契约、使用测试替身验证的最小 Agent Loop，以及面向受控本地仓库的 `list_files` / `read_file` / `search_code`。详见 [architecture](docs/architecture.md) 和 [八项 ADR](docs/decisions.md)。

## Repository Structure

```text
RepoPilot/
├── AGENTS.md
├── README.md
├── .gitignore
├── docs/
│   ├── architecture.md
│   ├── roadmap.md
│   ├── migration.md
│   └── decisions.md
├── apps/web/README.md
├── services/control_plane/README.md
├── services/agent_runtime/
│   ├── app/agent/models.py
│   ├── app/agent/loop.py
│   ├── app/tools/registry.py
│   ├── app/tools/safe_read.py
│   ├── app/tools/search_code.py
│   ├── tests/test_models.py
│   ├── tests/test_tool_registry.py
│   ├── tests/test_agent_loop.py
│   ├── tests/test_safe_read_tools.py
│   ├── tests/test_search_code_tool.py
│   └── README.md
├── proto/.gitkeep
├── configs/.gitkeep
├── deploy/.gitkeep
├── evals/.gitkeep
├── scripts/.gitkeep
└── references/RepoPilot_full_design.md
```

`references/` 是原有长期设计参考，保持原样；不是当前开发范围清单。未来目标目录仅记录于 architecture，不提前建立实现文件。

## Development Roadmap

范围以 [docs/roadmap.md](docs/roadmap.md) 的 `Current Phase: Phase 1` 为准。

| Phase | 目标 | 状态 |
| --- | --- | --- |
| 0 | Baseline / Day 1 Bootstrap | 文档与最小骨架已完成 |
| 1 | Python Coding Agent MVP | In Progress；Steps 1.1–1.4 已完成，Step 1.5 已实现并等待验收，完整 MVP 仍为 NOT IMPLEMENTED |
| 2 | Go Control Plane MVP | Planned |
| 3 | RabbitMQ Task Queue | Planned |
| 4 | Task Event + SSE | Planned |
| 5 | Go Tool Gateway + Docker Sandbox | Planned |
| 6 | Code RAG + PostgreSQL / pgvector | Planned |
| 7 | Memory | Planned |
| 8 | Human Approval | Planned |
| 9 | Eval + Observability | Planned |
| 10 | Productization | Planned |

Redis 和 gRPC 的实施需满足 roadmap 中的条件并明确加入范围，不因长期技术选型自动引入。

## Current Status

- **Current Phase**：Phase 1 — Python Coding Agent MVP，正在开发。
- **Current Step**：Phase 1.5 — Search Code Tool，已实现并通过本地测试，等待用户验收；不会自动推进到 Step 1.6。
- **Implemented**：项目治理基线；Provider 无关的 Message、ToolCall、ToolResult、AgentState、AgentResult；工具调用与结果关联校验；Tool 定义及 Registry；同步 ChatModel 契约；透明 Agent Loop；Tool Call 顺序执行、Observation 回填、自然成功、显式失败和迭代耗尽语义；固定仓库根目录的路径边界；真实 `list_files` / `read_file` / `search_code`；安全路径、链接和常见凭据保护；确定性 JSON 搜索结果；文件、扫描、命中和输出上限；标准库单元测试。
- **Planned / NOT IMPLEMENTED**：`apply_patch`、`run_test`、完整 JSON Schema 参数语义校验、async/streaming、超时/取消、真实 LLM Provider、完整 Python MVP，以及 Go Control Plane、RabbitMQ、Redis、PostgreSQL、pgvector、Tool Gateway、SSE、Sandbox、Code RAG、Memory、Approval、系统化 Eval 和 OpenTelemetry。
- **Validation**：在 Python 3.10.9 使用 `python -B -m unittest discover -s tests -v` 运行 50 个模型、Registry、Loop、Safe Read 与 Search Code 测试并通过；Search Code 专项 10 个测试覆盖真实命中、无命中、结构化位置、范围限制、路径与链接安全、非文本文件及截断。链接逃逸测试使用真实 symlink，Windows 无创建权限时使用 Junction 等价夹具。当前 Loop 仍只通过 fake ChatModel 验证，没有真实 Provider、写工具、测试工具或服务启动入口。
- **Git**：项目已初始化独立 Git 历史，`main` 跟踪 `origin/main`；本节不代表当前工作区改动已提交或推送。

## Reference Projects

已只读检查同级 `12-hermes-agent-small` 和 `ai-agent-scaffold`，未复制代码或改动参考项目。

Hermes 提供 Loop、Registry、Memory、Workspace、Eval、Tracing 等思想，当前副本根许可证为 MIT；Go Scaffold 提供 Handler / Service、Ports、Config、SSE、MCP Router、Runner / Session 等工程模式，本地未发现许可文件。正式迁移前需核实具体版本、许可及 attribution，详见 [migration record](docs/migration.md)。

## Development Principles

开始任何开发前先读 [AGENTS.md](AGENTS.md)，再读 roadmap 和相关架构。每次只完成一个小型可验证闭环，检查既有代码、运行相关测试、Review Diff、同步文档并报告真实限制。

坚持 Go / Python 职责边界，Python 拥有主要 Runtime；禁止为未来需求堆基础设施、复制完整参考项目或用假数据声称完成。Sandbox 完成前仅在专门准备的受控测试 Repository 执行白名单测试命令；审批就绪前 HIGH 风险工具禁用。

当前 Step 1.5 等待用户验收。验收确认后，下一推荐 Step 是 Phase 1.6 Apply Patch Tool；本次未实现该 Step。
