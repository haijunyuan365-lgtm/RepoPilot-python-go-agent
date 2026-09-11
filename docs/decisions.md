# RepoPilot Architecture Decision Records

创建日期：2026-09-10。轻量 ADR 记录决定及理由，不代替 [roadmap](roadmap.md) 的 Current Phase 和 [architecture](architecture.md) 的架构说明。

Status **Accepted** 表示确认长期选择，**Proposed** 表示待验证；不表示已实现。Day 1 八项决定均接受其方向，但运行时和基础设施全部 NOT IMPLEMENTED。调整时保留历史，追加新 ADR / 替代关系，并同步范围。

## ADR 001 — Use a new repository instead of modifying Hermes in place

- **Status**：Accepted。
- **Context**：Hermes 属于 Personal Assistant 领域；RepoPilot 面向 Software Engineering Agent。原设计包含原地改造建议，Day 1 明确要求独立项目和只读参考。
- **Decision**：在独立 `RepoPilot/` 项目中建立新的代码与未来 Git 历史，不修改 Hermes 或 Go Scaffold，也不把它们整体复制进来。Day 1 创建文档与骨架，不创建提交或标签。
- **Reasons**：RepoPilot has a different product domain；避免 Personal Assistant legacy coupling；保持 clean Git history；允许 selective migration；提高 Vibe Coding architecture control。
- **Consequences**：需要逐个识别可复用思想、重设计和测试；重要参考或迁移记录在 migration.md；原项目仍独立保留。今天尚未初始化 Git，不能宣称已有版本基线提交。
- **Future Review Conditions**：出现必须保留来源历史的大块合法迁移时，评估保留来源提交/版权方式，但不自动改变独立产品边界。

## ADR 002 — Use Go + Python architecture

- **Status**：Accepted。
- **Context**：平台状态、并发、安全执行与 LLM 推理迭代有不同职责及变化节奏。
- **Decision**：Go manages platform orchestration, state, concurrency, service infrastructure, security and execution environments. Python manages LLM reasoning, Agent Loop, planning, RAG, memory, tool selection and evaluation. Go 管 Task / Service Orchestration，Python 管 LLM Orchestration。
- **Reasons**：平台基础设施与 AI 逻辑分工清晰；Python 支撑 Agent 快速迭代；Go 支撑任务服务和执行管理；架构可解释且可独立测试。
- **Consequences**：增加跨语言契约、错误、Trace、版本和部署成本；Phase 1 只建 Python，Phase 2 才开始 Go。不能因为双语言选择而一次搭建全部服务。
- **Future Review Conditions**：服务边界引入实际运维/性能问题，或职责需跨界时，先用实测数据复议并记录新 ADR。

## ADR 003 — Python owns the primary Agent Runtime

- **Status**：Accepted。
- **Context**：Hermes 和 Go Scaffold 都包含 Loop / Tool Reasoning，直接复用会造成双 Runtime、双状态和职责不清。
- **Decision**：Python 是主要 Agent Runtime 唯一所有者，包含 Loop、Planner、RAG、Memory、Tool Selection、Reviewer、Evaluator。Go 仅做平台任务编排与安全执行，不重建等价 LLM Runtime。
- **Reasons**：防止两套推理链竞争；减少调试和维护成本；保留透明、可测试的 Agent Loop。
- **Consequences**：Go Scaffold 的 Agent Factory、Workflow、Runner 只能提取工程思想，不直接迁移完整 LLM Runtime。Python Phase 1 的本地受控工具是执行过渡，不改变长期安全所有权。
- **Future Review Conditions**：出现独立且无法由现有 Python Runtime 支持的真实产品需求时，再讨论边界；性能猜测、框架兴趣或参考项目已有实现都不足以启动第二套 Runtime。

## ADR 004 — Use RabbitMQ for asynchronous Agent tasks

- **Status**：Accepted（长期选择，Phase 3 引入）。
- **Context**：Agent 任务可能持续较长时间，不适合依赖单次 HTTP 连接完成调度、运行和失败恢复。
- **Decision**：Go 投递异步任务到 RabbitMQ，Python Task Worker 消费，执行事件经 RabbitMQ 返回 Go。Phase 3 首先使用 task.created、agent.started、agent.completed、agent.failed。
- **Reasons**：将长任务与 HTTP 生命周期解耦，允许独立 Worker、有限重试、ACK 和事件传输；同步 Tool Call 继续使用 HTTP / 后续 gRPC。
- **Consequences**：必须处理重复投递、ACK 时点、任务领取、重试和失败观察。队列不保证业务 exactly-once。Phase 3 先受限单进程验证；Phase 6 持久状态接入时补齐持久去重、数据库/消息一致性及恢复。Day 1 不建 Exchange、Queue 或消费者。
- **Future Review Conditions**：队列吞吐、路由和运维实测无法满足需求时复议；不得因为技术偏好换成 Kafka 或另加任务框架。

## ADR 005 — Use HTTP first and gRPC later for Tool Gateway

- **Status**：Accepted（先后策略；gRPC 具体切换时点待验证）。
- **Context**：Python Agent 的工具调用需要同步返回结果，工具边界早期仍会演进。
- **Decision**：Phase 5 使用 HTTP 对接 Go Tool Gateway；接口稳定并有真实收益后再引入 gRPC。任务调度仍归 RabbitMQ，前端事件仍归 SSE。
- **Reasons**：MVP simplicity first；HTTP 便于早期调试；gRPC introduced when service boundary is stable，可用于稳定类型契约与跨语言客户端。
- **Consequences**：先约定结构化请求/结果、错误、超时、风险及关联标识。不能同时长期维护两套不同语义的执行接口。Day 1 不生成 Proto 或 stub，Phase 1 不需要 Tool Gateway 服务。
- **Future Review Conditions**：HTTP 契约稳定、有类型安全/性能/维护证据、具备契约回归和兼容迁移计划时，更新 ADR 与 roadmap 后切换；不以未来一定使用为由提前生成代码。

## ADR 006 — Use PostgreSQL + pgvector

- **Status**：Accepted（长期存储方向，Phase 6 首次接入）。
- **Context**：平台业务、Agent 历史、代码 Metadata、Memory 和 Embedding 需要持久化；早期维护多种存储会增加复杂度。
- **Decision**：PostgreSQL 保存持久业务与 Agent 数据，pgvector 保存 Embedding；早期统一存储并支持 Vector + Keyword 检索。Go / Python 仍按领域拥有写入规则，具体 schema / 数据库权限在 Phase 6 确认。
- **Reasons**：业务数据与 Vector 数据统一存储具有早期工程收益：减少部署与同步系统，便于 Metadata、版本、Scope 和检索结果关联。
- **Consequences**：需要验证向量查询、关键词切分、维度、索引更新、数据库负载与跨服务权限；不能假设天然解决中文检索。Phase 2–5 内存状态重启丢失，Phase 6 一并补齐 Task / Run / Event 持久化和一致性。Redis 只是未来条件性热状态组件，不是事实来源，未自动列入当前实现。
- **Future Review Conditions**：数据规模、检索延迟或运维需求超出统一存储能力时，根据基准评估拆分；若必须提前持久化，先明确修改 roadmap，而非隐性引入数据库。

## ADR 007 — Use Docker Sandbox + Git Worktree

- **Status**：Accepted（长期隔离选择；Phase 1–4 有限过渡，Phase 5 实现）。
- **Context**：Coding Agent 会修改并执行代码，直接运行宿主命令风险高；并行任务需要独立工作副本。
- **Decision**：长期由 Go Tool Gateway / Sandbox Manager 创建任务 Git Worktree，并通过受限 Docker Sandbox 执行工具；工作副本和执行权限都由 Go 管理。Phase 1–4 仅允许 Python 在专门准备、内容已检查的测试 Repository 内运行五个受控工具。
- **Reasons**：Git Worktree 隔离任务修改和并发工作副本，Docker 提供执行环境约束，Go 集中落实权限、超时和资源管理。
- **Consequences**：Worktree 不是安全沙箱；容器需限制挂载、网络、CPU、Memory、Process、环境和输出。过渡期要有路径/链接逃逸检查、固定测试命令参数列表、白名单、超时和输出上限，禁止任意 shell、凭据访问和未知外部仓库。Phase 5 移除生产 Python 宿主执行旁路；Phase 8 完成人工审批前 HIGH 操作一直禁用。
- **Future Review Conditions**：目标主机/容器模型不足以满足隔离、取消或清理需求时复议；对更强隔离的真实需求用威胁模型和测试支撑，不能提前引入 Kubernetes。

## ADR 008 — Use SSE for frontend Agent event streaming

- **Status**：Accepted（Phase 2 基础，Phase 4 执行事件）。
- **Context**：前端主要接收任务状态、Tool、Test、Review 和 Approval 事件，用户操作可以继续走 HTTP。
- **Decision**：Go Event Service 用 SSE 向前端推送结构化事件；模型文本增量若加入则独立分类。浏览器订阅断开不等于取消后台 Agent Task。
- **Reasons**：符合服务端单向推送模式，前端消费简单，能保持 HTTP 任务操作和事件展示边界清晰。
- **Consequences**：需定义事件标识、顺序、错误、缓冲和清理；Phase 4 先有限内存 Hub，Phase 6 持久事件再支持可靠回放；Redis Event Buffer 可选。不能直接搬用“HTTP 断开就中止整条任务”的旧聊天链路语义。
- **Future Review Conditions**：出现 SSE 无法满足的双向实时交互或实际连接瓶颈时，基于需求评估其他协议；不为潜在需求默认增加 WebSocket。

## ADR 模板

```text
ADR NNN — Title
Date:
Status: Proposed / Accepted
Context:
Decision:
Reasons:
Consequences:
Future Review Conditions:
Affected Phase / Documents:
Supersedes / Superseded by (if applicable):
```

新决定至少回答真实问题、当前阶段必要性、现有方案不足及验收方式。模板本身不代表待实现模块清单。
