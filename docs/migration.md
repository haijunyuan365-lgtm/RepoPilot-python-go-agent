# RepoPilot Migration Record

## 1. 原则与当前状态

遵循 **Read → Understand → Identify reusable idea → Redesign for RepoPilot → Migrate minimal required code → Add tests**。

Day 1 仅完成设计阅读、参考源码检查、候选映射和重设计约束，当时没有复制、迁移或运行参考项目代码，也没有修改参考项目。后续 Phase 1 的实际采用记录在 M-001 及之后条目中；当前仍没有复制参考源码。`Candidate` 不表示代码已移入 RepoPilot，`Pattern adopted` 只表示通用思想已被独立重设计，`Not migrating` 也不表示删除参考项目文件。

范围由 [roadmap](roadmap.md) 决定，跨语言职责由 [architecture](architecture.md) 和 ADR 002 / 003 约束。目标路径是未来位置，不要求今天创建模块或接口。以后每迁移一个重要模块，都追加实际迁移记录、版本和测试证据，不覆盖候选阶段历史。

## 2. Day 1 Inspection — 2026-09-10

| Source | 本地检查基线 | 已检查内容 | License considerations |
| --- | --- | --- | --- |
| Hermes：`../12-hermes-agent-small/`（相对 RepoPilot 根目录） | 可读取源码；此副本未见 `.git`，无法确认 commit；`waku/loop/agent.py` SHA-256：`C744964BFBBB2D0471EC22F9A3632C8AD943EAF4654DC1D08AA0E9B0E64F9FBA` | 目录；Loop / Registry；Retrieval Gate / Consolidation；Semantic / Episodic / Procedural；Workspace / delegate_task；Coding Eval / Tracing / Judge / Release Gate | 根 `LICENSE` 为 MIT，版权行为 `Copyright (c) 2026 Sean Chen (ShenSeanChen)`。未来复制代码需按许可保留版权与许可文本，并核查文件中的其他上游来源 |
| Go Agent Scaffold：`../ai-agent-scaffold/`（相对 RepoPilot 根目录） | HEAD：`92d374127a1a58389d446536a9c519596aa906d1`；工作树已有修改及未跟踪文件，所读内容不等同于该 commit | Gin Handler / Chat Service / Ports；Config Loader；SSE；Agent Factory；Runner / Session；MCP Router；Sequential / FanOut Workflow | 在本地文件列表中未发现 LICENSE / COPYING / NOTICE。复制代码前需确认所有权、许可及依赖来源；当前仅记录工程思想，不推定许可 |

上述检查是静态阅读，不是参考项目功能/安全审计，也没有运行其测试或修改基线标签。正式迁移时必须重新记录精确来源版本或源文件 hash，检查当前差异，不能拿有修改的工作树当稳定发布版本。

长期设计参考：`references/RepoPilot_full_design.md`，共 4,644 行，已完整阅读；SHA-256：`83125B7F6F2D6DD847D331F046DCAE3EED187A76F2EBC76916F4EB29B388A572`。该文件保持原样。Day 1 Prompt 将“原地改造 Hermes”改为独立项目，并收窄 Phase 1；执行规则以当前治理文档为准。

## 3. Hermes — 候选迁移映射

以下每行的 Source 相对于 Hermes 根目录，Target 相对于 RepoPilot 根目录。**What was reused** 在本阶段都只是已识别的思想；**What was redesigned** 是 RepoPilot 需要的调整，尚未实现。H-01 至 H-09 的许可基线均为上表 MIT 检查；涉及派生来源需单独追溯。

| ID / Source | Target（未来） | What was reused / Potential reuse | What was redesigned / Why | Phase / Status |
| --- | --- | --- | --- | --- |
| H-01 `waku/loop/agent.py` | `services/agent_runtime/app/agent/loop.py` | Agent Loop、max_iterations、Tool Calling、Observation 回填的通用思想 | Step 1.3 已用显式 AgentState / AgentResult、Provider 无关 ChatModel Protocol 和结构化 ToolResult 独立实现；区分自然成功、模型/协议失败、迭代耗尽和可反馈的工具失败。未复制 Anthropic 类型、streaming、observer 或字符串耗尽回复 | Step 1.3 Pattern adopted；streaming / events / Provider 均 Planned |
| H-02 `waku/tools/registry.py` | `services/agent_runtime/app/tools/registry.py` | Tool Schema、Registry concept、稳定注册顺序 | Step 1.2 已实现结构化结果方向的 handler 契约、Schema 传输边界及重复/未知工具显式错误；未复制“异常转字符串”和静默覆盖行为。风险/超时/审批/幂等/Trace 及 Phase 5 Go 执行仍为 Planned | Step 1.2 Pattern adopted；Gateway Phase 5 Planned |
| H-03 `waku/memory/retrieval_gate.py` | `services/agent_runtime/app/memory/retrieval_gate.py`（future RepoPilot retrieval gate） | 先判定是否检索及检索 Query，减少无关上下文 | 改为研发 Code / Memory 决策，增加 Scope、预算、错误回退评测；原实现 fail-open 不能绕过授权边界 | Phase 7；Candidate |
| H-04 `waku/memory/consolidation.py` | `services/agent_runtime/app/memory/consolidation.py`（future async memory consolidation） | 按积累量提炼 facts / episodes，失败保留输入待重试 | 从同步 SQLite chat log 改为 RabbitMQ 后台处理、PostgreSQL、来源与 Scope、去重和恢复；主任务不等待蒸馏 | Phase 7；Candidate |
| H-05 `waku/memory/semantic/store.py`、`waku/memory/episodic/store.py`、`waku/memory/procedural/loader.py` | `services/agent_runtime/app/memory/`、`services/agent_runtime/app/skills/` | Semantic / Episodic / Procedural 分工、日期与相关性、按需加载 Skill | 研发事实与任务记录替代私人信息；USER / PROJECT / TASK 隔离；不继承 ASCII-only 提词作为中文方案，不把 Skill 当权限来源 | Phase 7；Candidate |
| H-06 `waku/ops/coding_eval.py` | `evals/coding/`；运行时复用逻辑按需放 `services/agent_runtime/app/eval/` | 真实 verify 命令、退出码和测试输出判断修改成果 | 用 RepoPilot 自己的 Runtime、受控仓库与 Sandbox，移除 pi 依赖和任意 shell；缺少 verify / 零测试不得成功；保留固定基线及不可随意弱化的验收断言 | Phase 9 系统化；Phase 1 只独立做最小测试闭环；Candidate |
| H-07 `waku/ops/tracing.py` | `services/agent_runtime/app/observability/`，Go 对应平台埋点 | Observer 解耦、UTF-8 JSONL、可选 OpenTelemetry、usage 记录 | 加 task_id / run_id / trace_id / tool_call_id，跨服务传播、脱敏和输出边界；不将不可观测的失败静默当成功 | Phase 9；早期只按需最小日志；Candidate |
| H-08 `waku/ops/judge.py`、`waku/ops/release_gate.py` | `services/agent_runtime/app/eval/`、`evals/judge/`、未来 evaluation release gate | Rubric、版本化质量评分、确定性检查和 Gate 报告 | Coding / 安全证据优先；Judge 看到实际结果而不只工具名；必需检查缺失/跳过不得开放 Gate；阈值由基线验证 | Phase 9；Candidate |
| H-09 `waku/tools/workspace.py` | `services/control_plane/internal/sandbox/` | Workspace、created_files、logs、manifest / artifact 可追溯思想 | 生命周期、资源、Git Worktree、清理归 Go；不继承自动挑入口执行和无限宿主访问；跨语言重设计而非 Python 文件搬运 | Phase 5；Candidate |
| H-10 `waku/tools/experimental.py` 的 `delegate_task` | 无当前迁移目标 | 已阅读外部 coding agent 调用、timeout、transcript 的思路 | RepoPilot 自己实现主要 Coding Loop；不依赖外部 pi 代替核心能力，不复制直接宿主执行，不为此引入 Multi Agent | 当前路线不迁移；Not migrating |

### 已发现且必须重设计的具体行为

- Loop 直接修改 messages，使用 Provider 特定的内容块；达到 max_iterations 以文本回复结束。RepoPilot 需要明确的非成功结果，避免自然语言掩盖状态。
- Registry 捕获执行异常并返回字符串，但没有完整风险策略；它的文件说明提到 `launch-agentic-rag`，未来复制时必须追溯该上游 attribution，根 MIT 不能代替来源核实。
- Retrieval Gate 出错时默认检索；RepoPilot 只能在已验证 Scope 内回退，不能跨项目读取。
- Semantic FTS 和 Skills 匹配使用 ASCII 正则；中文召回需重新验证。Consolidation 当前是同步写 SQLite，不能直接搬入异步长任务主链。
- Coding Eval 的一个路径在没有 verify 时返回成功，且使用 `shell=True`；这些行为不符合 RepoPilot 的完成与执行规则，不迁移。Workspace / delegate_task 在宿主运行子进程，也不构成 Docker Sandbox。
- Release Gate 在缺少 Key 时可以跳过 Judge；RepoPilot 必须区分可选检查与本次发布必需检查。Judge 使用工具名称作为动作证据也不足以证明成功，要传入真实结果。

### 不迁移的领域功能

Calendar、Personal Notes、Personal Messages、Telegram、Voice、Personal Assistant specific tools 均不属于 RepoPilot。对应 `waku/tools/calendar.py`、`notes.py`、`messages.py`、个人 Apple 工具以及 `waku/gateway/telegram.py`、`voice.py` 不进入目标项目。

不删除参考项目中的这些文件；如果未来个别迁移片段带入这些耦合，应在 RepoPilot 片段中移除并记录。`browse_web`、`schedule_task`、个人 Dashboard 和实验空工具也不列入当前路线；不把 skeleton 搬来充成功能。

## 4. Go Agent Scaffold — 候选工程模式

**Go Agent Runtime will not become RepoPilot primary Agent Runtime.**

**Its engineering patterns may be reused in Go Control Plane.**

以下 Source 相对于 Scaffold 根目录。所有条目今天仅参考思想，License considerations 均为“未发现本地许可文件；实际复制前确认来源与许可”。Target 是未来边界，不提前创建目录或接口。

| ID / Source | Target（未来） | What was reused / Potential reuse | What was redesigned / Why | Phase / Status |
| --- | --- | --- | --- | --- |
| G-01 `internal/trigger/http/agent_handler.go`；`internal/domain/agent/service/chat/service.go` | `services/control_plane/internal/api/`、`application/` | Gin HTTP、Handler / Service、输入校验、Context 传播 | Chat / Agent ID 语义改为 Project / Repository / Task；Handler 不推理，Application 协调状态；不整体复制响应码和聊天 API | Phase 2；Candidate |
| G-02 `internal/domain/agent/ports/ports.go` | `services/control_plane/internal/domain/` 及所需 Application 接口 | Ports、依赖倒置、小接口 | 从 ModelProvider / AgentFactory 重设计为实际需要的任务存储、事件发布或执行能力；不预建接口大全，不把内存实现混同永久存储 | Phase 2 起按需；Candidate |
| G-03 `internal/trigger/http/agent_handler.go` 的 chatStream | `services/control_plane/internal/event/` 与 API SSE | SSE 写入/Flush、Context 取消、channel 关闭清理 | 从模型文本改为结构化 Task Event；SSE 断开仅释放订阅，长期后台任务取消走 Task Service，不能照搬请求断开语义 | Phase 2 / 4；Candidate |
| G-04 `internal/app/config/loader.go`、`application.go` | Control Plane 配置适配，具体位置 Phase 2 确认 | Config Loader、环境变量、默认值与校验 | 改为最小平台配置，去掉 Agent 装配表；缺失必需配置应报错；不带入所有 YAML / MySQL / Redis 依赖 | Phase 2；Candidate |
| G-05 `internal/infrastructure/ai/mcp_sse_client.go` 的 MCPToolRouter；`internal/infrastructure/ai/tools.go` | `services/control_plane/internal/tool/` | MCP Router、tools/list、工具名到 client 路由、显式不可调用错误 | 置于 Go Tool Gateway 权限与审计边界内，校验参数与授权；不是当前 Phase 5 的必选 MCP 集成 | Gateway Phase 5 可参考路由思想；MCP 需未来单独范围；Candidate |
| G-06 `internal/domain/agent/service/armory/factory/factory.go`；`internal/infrastructure/adk/adapter.go` 的 Runner | Go Application 装配与任务执行协调 | Agent Factory 的依赖装配、Runner 生命周期、取消/超时 | 只保留必要装配和生命周期思路；不搬运 LLM Agent Factory、Provider、完整 Runtime 或复杂责任链 | Phase 2–3 按需；Pattern only |
| G-07 `internal/domain/agent/ports/ports.go` 的 SessionStore；`internal/infrastructure/adk/adapter.go` 的 CreateSession | Go Task / Run / 会话管理，未来持久化适配 | Session 标识和存储抽象 | 以 Task / Run 为执行中心；区分进程内状态和持久事实，长期 PostgreSQL、可选 Redis；不直接继承个人聊天 Session Key | Phase 2 基础、Phase 6 持久化；Candidate |
| G-08 `internal/infrastructure/adk/adapter.go` 的 runSequential / runFanOut；`internal/domain/agent/service/armory/workflow/` | Python Runtime 内未来 Review 流程，Go 仅平台编排 | Workflow 顺序、显式输入/输出和终止思想 | 不迁移 Go LLM Workflow；已读 runFanOut 使用顺序 for 循环，不作为真实并发基线；不复制 Draw.io 领域与修复框架 | Python Review 在 Phase 9；无 Go Runtime 迁移；Pattern only |

本次没有运行 Scaffold 的既有测试，没有修复其未提交修改。参考实现能说明模式，不等于验证了适合 RepoPilot 的行为。

## 5. Actual Migration Record — M-001 / 2026-09-11

- **Module**：Phase 1.1 Core Runtime Data Models。
- **Source**：Hermes `waku/loop/agent.py`，本地源文件 SHA-256 为 `C744964BFBBB2D0471EC22F9A3632C8AD943EAF4654DC1D08AA0E9B0E64F9FBA`；长期设计第 14、21、61 节。
- **Target**：`services/agent_runtime/app/agent/models.py` 和 `tests/test_models.py`。
- **Current Phase / Authorized scope**：Phase 1 / Step 1.1，仅数据模型和单元测试。
- **What was reused**：max_iterations 是显式循环预算、Tool Call 需要稳定 ID、工具结果应作为下一轮 Observation、循环必须有清楚终态的设计思想。
- **What was redesigned**：没有复制 Hermes 源码。原 `LoopResult(reply, tool_calls, iterations)` 被拆分为 Provider 无关的 Message / ToolCall / ToolResult / AgentState / AgentResult；迭代耗尽不再伪装成普通 reply；AgentState 同时校验 call ID、工具名、唯一性和一次完成语义；工具参数限制为 JSON-compatible 数据。
- **Why**：Step 1.2 Registry、Step 1.3 Loop 和后续 Provider Adapter 需要先共享一个稳定、可测试的内部协议，同时不能继承 Anthropic SDK 内容块或字符串错误约定。
- **License considerations**：Hermes 根许可证为 MIT，但本 Step 只采用通用设计思想，没有复制代码行或依赖；RepoPilot 当前未选择发布许可证。Step 1.3 同样只采用通用 Loop 思想并独立重设计，没有触发具体源码复制的 attribution 要求；详见 M-003。
- **Design decisions**：符合 ADR 002 / 003；没有新增 ADR 或外部依赖。
- **Tests**：`python -B -m unittest discover -s tests -v`，17 tests，PASS（在 `services/agent_runtime/` 执行）。
- **Evidence**：核心实现、测试和 `docs/learning/phase-01/step-1.1-core-runtime-data-models.md`。
- **Status**：Pattern adopted / Step 1.1 completed；RepoPilot 最小 Loop 已在 Step 1.3 独立实现，Hermes Loop 源码本身仍未迁移。
- **Remaining limitations / Follow-up**：Steps 1.2–1.3 已补充 Registry 与最小 Loop；仍无真实 Provider、真实仓库工具、安全执行、网络协议或持久化。

## 6. Actual Migration Record — M-002 / 2026-09-11

- **Module**：Phase 1.2 Tool Registry Contract。
- **Source**：Hermes `waku/tools/registry.py`，本地源文件 SHA-256 为 `1D060B0BCD710FBF04C97C1E41DE877734A43C77A677BA40FFB546BC3470C9AD`；长期设计第 13、62 节。
- **Target**：`services/agent_runtime/app/tools/registry.py`、`app/tools/__init__.py` 和 `tests/test_tool_registry.py`。
- **Current Phase / Authorized scope**：Phase 1 / Step 1.2，仅 Tool 定义、Registry 行为、契约边界和单元测试。
- **What was reused**：Tool 将 name、description、input_schema 和 handler 聚合，Registry 按名称保存并向模型暴露 Schema 的通用设计思想。
- **What was redesigned**：没有复制 Hermes 源码。重复名称从静默覆盖改为 `DuplicateToolError`；未知名称从错误字符串改为 `UnknownToolError`；input_schema 必须是可防御复制的 JSON-compatible 顶层 object；handler 的类型方向为 `ToolCall -> ToolResult`，而不是关键业务错误与正常字符串混合。
- **Why**：Step 1.3 的 Loop 需要稳定、确定性的工具发现边界，同时未知/重复注册必须与真实工具失败区分，Schema 也不能被 Provider Adapter 或调用方意外修改。
- **License considerations**：Hermes 根许可证为 MIT，且其 Registry 注释声明模式改编自 `launch-agentic-rag`；本 Step 只采用通用 Registry 思想，没有复制代码行或依赖，因此未引入第三方代码或 attribution 文件。若未来复制具体实现，必须继续追溯该上游来源。
- **Design decisions**：符合 ADR 002 / 003 / 007；没有新增 ADR、外部依赖或执行基础设施。
- **Tests**：`python -B -m unittest discover -s tests -v`，23 tests，PASS（在 `services/agent_runtime/` 执行），其中 6 个为 Step 1.2 Registry 测试。
- **Evidence**：核心实现、边界测试和 `docs/learning/phase-01/step-1.2-tool-registry-contract.md`。
- **Status**：Pattern adopted / Step 1.2 completed。
- **Remaining limitations / Follow-up**：无完整 JSON Schema 参数语义校验、真实工具、Provider、风险/超时/审批策略或 Go Tool Gateway；Step 1.3 已增加最小 handler 执行包装。

## 7. Actual Migration Record — M-003 / 2026-09-11

- **Module**：Phase 1.3 Minimal Agent Loop。
- **Source**：Hermes `waku/loop/agent.py`，本次重新只读核对的本地源文件 SHA-256 为 `C744964BFBBB2D0471EC22F9A3632C8AD943EAF4654DC1D08AA0E9B0E64F9FBA`。
- **Target**：`services/agent_runtime/app/agent/loop.py`、`app/agent/__init__.py`、`app/tools/registry.py` 和 `tests/test_agent_loop.py`。
- **Current Phase / Authorized scope**：Phase 1 / Step 1.3，仅使用 fake ChatModel + fake Tool 验证同步最小循环，不访问文件系统、不接真实 Provider。
- **What was reused**：Reason → Tool Call → Observation → 下一轮，以及自然结束和 max_iterations 防止无限循环的通用设计思想。
- **What was redesigned**：没有复制 Hermes 源码。Loop 只依赖内部 `Message` 与 `ChatModel` Protocol，不导入 Anthropic；使用已有 `AgentState` 维护关联和迭代、`AgentResult` 区分三种终态；通过 `ToolRegistry` 顺序执行多个调用；Registry 对模型类型改用仅类型检查时导入以保持公共包可独立加载；未知工具、handler 异常和非法返回形成带原 `tool_call_id` / `tool_name` 的失败 Observation，而不是混成普通字符串；本 Step 不提前加入 streaming、observer、Provider 参数或真实工具。
- **Why**：Step 1.3 需要验证最小推理—行动—观察控制流，并为后续安全读工具与 Provider Adapter 提供稳定边界；显式状态和结构化结果使失败可测试且不会被自然语言掩盖。
- **License considerations**：Hermes 根许可证为 MIT；本 Step 仅采用通用循环思想，没有复制源代码行、Anthropic SDK 绑定或依赖，因此未加入第三方代码声明。参考项目保持只读且 hash 与 Day 1 记录一致。
- **Design decisions**：符合 ADR 002 / 003 / 007；没有新增 ADR、外部依赖、跨语言边界或执行基础设施。
- **Tests**：`python -B -m unittest tests.test_agent_loop -v`，8 tests，PASS；`python -B -m unittest discover -s tests -v`，31 tests，PASS（均在 `services/agent_runtime/` 执行）。覆盖单/多 Tool Call、Observation 回填、失败 ToolResult、未知 Tool、handler 异常/非法返回、自然结束、模型协议失败、未解析初始状态和 max_iterations。
- **Evidence**：核心实现、测试、Diff Review 和 `docs/learning/phase-01/step-1.3-minimal-agent-loop.md`。
- **Status**：Pattern adopted / Step 1.3 implemented and locally verified；等待用户验收。
- **Remaining limitations / Follow-up**：无真实 Provider、async/streaming、事件 observer、重试、超时、取消、恢复执行、Schema 语义校验或真实仓库工具。

## 8. 迁移状态与完成标准

- **Candidate / Pattern only**：已识别思想，尚未复制或实现。
- **Planned**：已明确进入 Current Phase 的下一项有限迁移，仍未完成。
- **In Progress**：正在最小迁移，需明确未实现和未验证范围。
- **Migrated**：范围内的真实行为、许可处理和相关测试均有证据；不能仅因文件存在就标记。
- **Not migrating**：当前不进入 RepoPilot，不表示删除来源。

实际迁移时检查 Source commit/hash、dirty diff、License、上游声明及依赖。保留需要的版权/许可到合适的源文件声明或 attribution 文件，并记录路径；今天未复制代码，因此不添加虚构的第三方代码归属或擅自选择 RepoPilot 开源许可证。

## 9. 每个实际迁移追加使用的模板

```text
Migration ID / Date:
Module:
Source: project + path + commit / source hash + dirty state
Target: RepoPilot path
Current Phase / Authorized scope:
What was reused: ideas / exact code portions / data / tests
What was redesigned: behavior, domain, state, security, ownership
Why: real need and why minimal reuse is appropriate
License considerations: source license, upstream attribution,
  copyright/notice retained at, dependency checks, unresolved items
Design decisions: related ADRs
Tests: exact commands, results, tested failures and boundaries
Evidence: diff / commit / report / artifact locations
Status: Candidate / Planned / In Progress / Migrated / Not migrating
Remaining limitations / Follow-up:
```

只引用思想也应如实记录，不能把参考原实现的测试结果当作 RepoPilot 的测试结果。未来更新必须维持 Python 主 Runtime、Go 安全执行和阶段边界。
