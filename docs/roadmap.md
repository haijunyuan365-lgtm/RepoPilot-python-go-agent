Current Phase: Phase 1
Current Step: Phase 1.1 — Core Runtime Data Models
Step Status: Awaiting Acceptance

Only tasks belonging to Current Phase and Current Step should normally be implemented.

# RepoPilot Development Roadmap

本文件是后续 Vibe Coding 的功能范围控制器。当前状态：**Phase 0 的 Day 1 Bootstrap 已交付；Phase 1 正在开发；Step 1.1 已实现并完成本地验证，等待用户验收。完整 Python Coding Agent MVP 仍为 NOT IMPLEMENTED。**

Day 1 的授权仅包含文档与最小骨架。Current Phase 指向 Phase 1，不表示今天要开始写 Agent，也不表示 Phase 1 已通过验收。

## 范围与推进规则

- 日常开发同时受 Current Phase 和 Current Step 约束。默认只实现 Current Step，禁止因为同一 Phase 还包含其他能力就顺手继续。
- 每次任务只交付一个小型、可验证闭环。禁止因为未来目录或长期架构图中有某个模块就创建它。
- Step 推进前必须有验收命令、结果、限制及未完成项。Coding Agent 不自行推进 Current Step；用户明确确认后再更新。用户仅说“继续”时，只进入紧接着的一个 Step。
- 阶段推进前记录整阶段验收证据，并同步 README、architecture、decisions、migration 中受影响的内容；不得自行把未验收阶段标为完成。
- 明显跨阶段的需求先指出目标阶段；用户明确要求提前实现时，记录范围例外及依赖，再执行该有限范围。
- Accepted ADR 不构成提前安装依赖或部署基础设施的授权。
- 核心逻辑的单元测试从 Phase 1 开始；Phase 9 是完整 Eval / Observability 体系，不是开始测试的时间。
- Phase 1–4 只支持专门准备的受控测试 Repository；Phase 5 引入 Sandbox。Phase 8 审批完成前 HIGH 风险工具保持禁用。

## Phase 0 — Baseline 与项目约束

- **Status**：Completed（Day 1 文档与目录基线；不包含业务能力）。
- **Goal**：建立 RepoPilot 独立项目、清晰架构边界和长期开发协议。
- **Scope**：RepoPilot project bootstrap；完整设计阅读；两个 Reference project inspection；AGENTS、README、architecture、roadmap、migration、decisions；必要目录、README、.gitignore、.gitkeep。
- **Non Goals**：Agent 实现、参考项目重构或测试基线运行、大型依赖、复杂框架、数据库表、Proto、Docker Compose、CI Pipeline、GitHub App。
- **Acceptance Criteria**：六份核心文档完整且一致；只创建必要骨架；原始参考文件保留；只读检查参考源码及许可；README 不将 Planned 描述为 Implemented。
- **Dependencies**：Day 1 Prompt 和 `references/RepoPilot_full_design.md`；参考项目可访问时只读检查。

## Phase 1 — Python Coding Agent MVP

- **Status**：Current / In Progress；仅 Step 1.1 已实现，完整 MVP 仍为 NOT IMPLEMENTED。
- **Goal**：在一个小型、受控 Bug Repository 中验证真实的查找、读取、修改、测试、失败后修复闭环。
- **Scope**：Message Model、Tool Call Model、Tool Result Model；支撑循环的显式 AgentState / AgentResult；透明 Agent Loop、max_iterations、Tool Registry；仅 `list_files`、`read_file`、`search_code`、`apply_patch`、`run_test` 五个工具；simple local test repository 和 simple bug fixing loop。按闭环需要接入一个真实 LLM Provider，保持最小适配，不建设多厂商平台。
- **Non Goals**：Go 服务、RabbitMQ、Redis、PostgreSQL、pgvector、gRPC、Docker、Multi Agent、delegate_task、复杂 Memory、Code RAG、独立 Planner/Reviewer 服务、SSE、完整 Eval 平台、通用 run_command、git 操作工具和高风险外部动作。
- **Acceptance Criteria**：模型/工具结果有清晰关联和错误语义；Agent 在指定测试仓库找到并读取相关代码、应用真实补丁、执行真实测试；至少一个可复现失败 Observation 被反馈到循环并驱动后续修改，最终可信验证测试通过；迭代上限、未知工具、路径越界、命令白名单、超时和非零退出有相关测试。真实闭环保留命令、输出、退出码、Diff 和迭代记录；测试替身不能代替此验收。不得以删弱测试来通过。
- **Dependencies**：Phase 0；已检查内容的专用本地测试 Repository；明确的测试命令；在真实 LLM 验收时可用的 Provider 配置。Sandbox 未就绪时遵守 AGENTS 的过渡安全规则。

### Phase 1 执行阶梯

下面的 Step 是 Phase 1 的默认开发顺序。每次只推进一个 Step。后续实现发现依赖关系需要调整时，先更新本段并说明理由。

| Step | 交付内容 | 最小验收 | 状态 |
| --- | --- | --- | --- |
| **1.1 Core Runtime Data Models** | `Message`、`ToolCall`、`ToolResult`、`AgentState`、`AgentResult` 的最小字段、状态和关联语义 | 单元测试覆盖序列化/构造、tool_call 关联、成功/失败/迭代耗尽表达；无 Loop、无真实 Tool | **Current / Awaiting Acceptance** |
| 1.2 Tool Registry Contract | 最小 Tool 定义、注册、查找、重复注册和未知 Tool 行为 | 单元测试覆盖正常注册、重复、未知 Tool、参数契约边界 | Planned |
| 1.3 Minimal Agent Loop | 使用 fake ChatModel + fake Tool 验证一次或多次 Tool Call、Observation 回填、自然结束和 max_iterations | 单元测试真实跑 Loop；不接 Provider，不访问文件系统 | Planned |
| 1.4 Safe Read Tools | 仓库根目录安全边界、`list_files`、`read_file` | 正常路径、目录穿越、绝对路径、符号链接/等价逃逸边界测试 | Planned |
| 1.5 Search Code Tool | `search_code` 的最小精确文本检索和结构化结果 | 小型 fixture 仓库中验证命中、无命中、输出限制和路径信息 | Planned |
| 1.6 Apply Patch Tool | `apply_patch` 只修改受控 Repository，返回真实 Diff/错误 | 正常修改、冲突/无效 Patch、越界拒绝测试 | Planned |
| 1.7 Run Test Tool | 白名单测试命令、timeout、stdout/stderr、exit code | PASS、FAIL、timeout、非法命令均有真实测试 | Planned |
| 1.8 One Real LLM Provider | 只接一个真实 Provider 适配到已有核心模型和 Loop | Provider 契约测试 + 一次最小真实调用；Secret 不入日志 | Planned |
| 1.9 Controlled Bug-Fix E2E | 小型 Bug Repository，完成 Search → Read → Modify → Test Fail → Observation → Retry → Test Pass | 保留输入、迭代记录、Tool Result、Diff、测试命令与退出码；满足 Phase 1 Acceptance Criteria | Planned |

**当前 Step 锁仍为 Phase 1.1**。本 Step 已实现核心数据模型、关联校验、结果语义、字典序列化和 17 个标准库单元测试，并生成学习笔记；等待用户验收，不自动推进到 Phase 1.2。Tool Registry、Agent Loop、工具执行和 Provider 集成仍未实现。

## Phase 2 — Go Control Plane MVP

- **Goal**：用 HTTP 接收和查询项目、仓库、任务，建立平台状态边界。
- **Scope**：Project、Repository、Task、Task Status、HTTP API、SSE basic structure；清晰 Handler → Application → Domain / Infrastructure；按最小需要使用进程内存储。若任务包含联调，可用有限的本地调用或 HTTP 适配连接 Phase 1 Runtime，并明确同步限制。
- **Non Goals**：RabbitMQ、Redis、PostgreSQL、生产持久化、完整事件 Timeline、Docker、复杂鉴权/RBAC、复杂前端、重写 Go Agent Runtime。
- **Acceptance Criteria**：通过 HTTP 可创建/查询真实进程内实体，参数错误和非法状态转换有测试；不伪造 Agent 成功；SSE 连接、断开和资源清理可测试；若没有执行联调则任务保持真实的未执行状态。服务重启丢失内存数据的限制必须写明。
- **Dependencies**：Phase 1 已验收；Go 版本、HTTP 路由方式和最小配置在本阶段确认。Gin 是参考候选，不因 Day 1 阅读而自动引入。

## Phase 3 — RabbitMQ Task Queue

- **Goal**：将 Agent 长任务从 HTTP 生命周期解耦。
- **Scope**：RabbitMQ 投递/消费 `task.created`、`agent.started`、`agent.completed`、`agent.failed`；Python Task Worker；Go 接收状态；有界重试、ACK 和重复投递处理；保持受控测试仓库限制。
- **Non Goals**：Redis、完整事件流、Memory 队列、索引队列、Eval 队列、全面跨重启一致性、gRPC、生产分布式锁。
- **Acceptance Criteria**：HTTP 创建任务不等待 LLM 完成；Worker 独立消费并产生真实成功/失败事件；重复/失败投递不会在约定的单进程测试条件下重复运行同一任务；记录 ACK、重试边界及 Worker 失败结果。内存状态不具备跨重启幂等和恢复保障，不能因有消息队列就声称端到端可靠持久化。
- **Dependencies**：Phase 1–2；本阶段可用 RabbitMQ；消息标识和版本约定。持久任务状态与去重在 Phase 6 持久化接入时补齐。

## Phase 4 — Task Event + SSE

- **Goal**：呈现真实任务执行过程，建立结构化事件通路。
- **Scope**：`tool_started`、`tool_completed`、`test_started`、`test_failed`、`test_passed`、`review_started`、`review_completed` 事件契约；Python 产出 → MQ → Go Event Service → SSE；事件关联、排序约定、有限缓冲、订阅断开清理。
- **Non Goals**：复杂前端、Redis Stream、跨重启回放保证、独立 Multi Agent Reviewer、Token Stream 与任务事件混为一谈。
- **Acceptance Criteria**：真实 Tool/Test 动作对应事件和结果；失败与通过可区分；取消订阅无泄漏；事件契约包含 Review，Review 通路可用明确标注的测试 fixture 验证，但生产中只有真实 Review 执行才发送对应事件。此阶段不据此宣称 Reviewer 已交付；最小 Python Diff Review 在 Phase 9 的评测链路接入。
- **Dependencies**：Phase 2 SSE 基础和 Phase 3 消息流；确定事件关联字段。持久事件、重连回放在 Phase 6 接入，Redis 仍不是本阶段必选依赖。

## Phase 5 — Go Tool Gateway + Docker Sandbox

- **Goal**：把代码执行和工作副本生命周期交给 Go，隔离 Agent 执行环境。
- **Scope**：首先 HTTP Tool Gateway；迁移 `read_file`、`apply_patch`、`run_test`，新增受控 `run_command`、`git_diff`；`list_files` / `search_code` 的工作副本访问同样服从 Go 管理的边界；Git Worktree、Docker Sandbox、Timeout、CPU Limit、Memory Limit、进程/输出/路径/环境/网络限制。
- **Non Goals**：gRPC 自动切换、任意宿主命令、生产无限权限容器、HIGH 风险执行、Kubernetes、持久化业务平台。
- **Acceptance Criteria**：每个任务拥有隔离 Worktree；测试/修改通过 Go 策略校验后在 Sandbox 内执行；超时或取消能终止执行并清理资源；验证路径逃逸、资源超限、失败清理和并发任务互不覆盖。Python 不再保留生产宿主执行旁路；HIGH 风险请求明确拒绝。
- **Dependencies**：Phase 1 工具协议、Phase 2–4 状态/事件链；本阶段 Docker 可用；明确主机平台、挂载和容器权限模型。后续 gRPC 仅在 HTTP 契约稳定、ADR 005 复议并更新范围后推进。

## Phase 6 — Code RAG

- **Goal**：在中型仓库中检索相关代码，避免整仓库塞入上下文，并建立持久数据基础。
- **Scope**：Repository Scanner、Code Chunk、Embedding、PostgreSQL + pgvector、Vector Search、Keyword Search、基本 Fusion；仓库/commit/path/行号定位与索引版本；本阶段首次接入 PostgreSQL，同时为此前 Task / Run / Event 最小状态补齐持久化、持久去重与状态/消息一致性设计。
- **Non Goals**：独立向量数据库、Milvus、Elasticsearch、完整 Symbol / Call Graph、跨语言 AST 平台、Memory。Symbol Search 可后续增强，需要单独的小任务。
- **Acceptance Criteria**：真实查询返回有仓库版本和代码位置的相关片段；验证中英文关键词、精确标识符、索引更新/失效和跨仓库隔离；保存检索质量基线；任务/事件重启可恢复并验证重复事件处理；数据库提交和消息发布之间的失败窗口有明确方案及测试，不能只展示正常路径。
- **Dependencies**：Phase 5 安全仓库访问、Phase 3–4 消息/事件；PostgreSQL 与 pgvector 在本阶段引入；Embedding 选择、维度和索引策略需记录决定。数据库迁移和必要的 Outbox 等一致性机制只在此阶段按需求落实。

## Phase 7 — Memory

- **Goal**：积累可追溯且按用户/项目/任务隔离的研发经验。
- **Scope**：Semantic、Episodic、Procedural / Skills、Retrieval Gate、USER / PROJECT / TASK Scope、Async Consolidation；复用已有 RabbitMQ 与 PostgreSQL。Working Memory 沿用 Runtime 当前任务状态，不另建全局记忆中心。
- **Non Goals**：个人日历/笔记/消息、Telegram、Voice、无边界自动记忆、通用 Multi Agent。
- **Acceptance Criteria**：Gate 能决定检索与不检索；Memory 命中可追溯来源；Scope 交叉泄漏测试通过；任务完成不等待 Consolidation；重复消息不重复污染记忆；删除/修正和失败重试语义明确；Skills 不能提升工具权限。
- **Dependencies**：Phase 6 存储与检索、Phase 3 队列；参考迁移许可证确认；明确保留与删除策略。

## Phase 8 — Human Approval

- **Goal**：在执行 HIGH 风险动作前提供可审计的人工批准和拒绝。
- **Scope**：统一 Tool Risk Level、Approval Request、WAITING_APPROVAL、Approve、Reject、过期和取消；批准绑定具体 tool_call_id、参数和工作副本版本；接入 Gateway 与 SSE。
- **Non Goals**：复杂企业 RBAC、审批工作流引擎、自动替用户批准、修改后继续使用旧审批。
- **Acceptance Criteria**：HIGH 工具未批准绝不执行；拒绝/过期/取消无副作用；重复批准不重复执行；参数或 Diff 变化使旧审批失效；批准后从正确阶段恢复，真实执行成功才完成任务。权限拒绝不得自动降级为可审批放行。
- **Dependencies**：Phase 5 Gateway、Phase 6 持久状态/审计、Phase 4 事件；最小可信用户身份与任务权限边界。

## Phase 9 — Eval + Observability

- **Goal**：为研发闭环提供可复现质量证据和端到端追踪。
- **Scope**：Deterministic Eval、Coding Eval、LLM Judge、Release Gate、OpenTelemetry、Metrics；接入最小 Python Diff Review 支撑 Review → Eval 验收；关联 task_id / run_id / trace_id / tool_call_id；Prompt/模型/数据集版本记录。
- **Non Goals**：虚构成功率、依赖 Judge 替代真实测试、十几个 Reviewer Agent、完整商业 LLMOps 平台。
- **Acceptance Criteria**：同一基线可复跑；核心测试和安全检查失败阻断 Gate；必需评测缺失/跳过不算通过；通过真实 Tool/Test/Review 结果评价完成度；跨 Go、MQ、Python、Tool Gateway 串联 Trace，能定位失败、超时和取消；指标包含成功率、延迟、迭代、Token、成本且注明采样范围。
- **Dependencies**：Phase 1 测试基线，Phase 4 事件，Phase 5 安全执行，Phase 6 持久化，Phase 8 审批；Judge 配置和 Gate 阈值需用基线数据确定。

## Phase 10 — Productization

- **Goal**：交付可演示、可复现、可解释的项目。
- **Scope**：README polish、Docker Compose、Demo Repository、Demo Video、Benchmark、Resume Description；围绕已有 API / SSE 完成最小 Web 任务、Timeline、Diff、Approval 展示；验证最终 Demo。
- **Non Goals**：复杂前端、GitHub App、企业组织体系、Kubernetes、无依据性能数字或自动发布承诺。
- **Acceptance Criteria**：按真实说明可启动已实现组件；Demo 展示创建任务、读取/修改、测试失败修复、Review、Eval、push 审批、批准后完成；全流程持久化、实时展示、取消、超时、追踪、评测、审计可验证；Benchmark 附环境与样本，简历描述只写证据支持的能力。
- **Dependencies**：Phase 1–9 已验收；明确目标部署环境与演示仓库；若某可选基础设施未引入，Compose 和 README 如实省略。

## 条件性长期技术：不自动解锁

| 技术 / 能力 | 触发条件 | 范围安排 |
| --- | --- | --- |
| Redis | 多进程热状态、锁、限流或事件缓冲确有需求，且现有进程内/数据库方案不足 | 最早在 Phase 3 之后评估；先追加 ADR 并明确加入某阶段 Scope。当前未排入必做实现，不是 Phase 1 依赖 |
| gRPC | Phase 5 HTTP 工具边界稳定，并有类型契约、调用成本等证据 | 根据 ADR 005 更新 roadmap 后安排；不替代 RabbitMQ |
| Symbol Search | Phase 6 基础检索质量/定位能力不足 | Phase 6 后增强任务；不提前建 AST 平台 |
| Auth / Webhook / Rate Limit | 对外开放或真实仓库接入时需要相应安全与平台能力 | 具体范围在对应阶段启动前补充；本路线不授权现在实现完整体系 |
| Multi Agent / Browser / GitHub App | 单 Agent 闭环成熟后出现明确产品需求 | 当前路线外，先记录新范围和 ADR |

本路线主动将 PostgreSQL 首次接入安排在 Phase 6；Phase 2–5 的内存状态不能宣称具备持久化。若真实需求必须提前持久化，应走明确的范围变更，不得悄悄增加数据库。
