# RepoPilot — Coding Agent 开发规则

本文件是所有 Coding Agent 开始工作前必须阅读的项目级开发规则。适用于 RepoPilot 全目录；参考项目不属于可修改范围。明确的用户任务要求决定本次范围，但不能把长期设计、候选迁移或未来目录当作当前实现授权。

## 1. Project Mission

RepoPilot 是 **Software Engineering Agent Platform**。用户绑定 Git Repository 后，以自然语言提出研发任务，系统逐步完成 Analyze、Search、Read、Modify、Test、Observe、Retry、Review、Approve、Evaluate，交付可验证、可审查、可提交的研发结果。

目标是研发闭环，不是通用个人助手。能否真实修复代码、利用失败 Observation 继续修复、验证结果并控制副作用，比功能数量更重要。

## 2. 文档职责与优先关系

| 文档 | 负责什么 |
| --- | --- |
| `AGENTS.md` | 开发规则、质量底线、工作协议 |
| [docs/roadmap.md](docs/roadmap.md) | Current Phase、允许范围、阶段验收；当前范围唯一入口 |
| [docs/architecture.md](docs/architecture.md) | 当前确认的架构边界、长期目标及过渡安排 |
| [docs/decisions.md](docs/decisions.md) | ADR、决定的理由和复议条件 |
| [docs/migration.md](docs/migration.md) | 参考来源、重设计、许可证检查、迁移证据 |
| [README.md](README.md) | 项目入口及真实交付状态 |
| [长期设计参考](references/RepoPilot_full_design.md) | 背景与长期设计素材，不是开发任务单 |

长期参考与本次任务范围冲突时，以明确的任务范围和 roadmap 为准。文档互相矛盾时先修正文档，不能挑选最宽松的一份来扩展范围。ADR 的 Accepted 表示接受方向，不代表模块已经实现。

## 3. Architecture Boundary

```text
Go manages platform orchestration, state, concurrency,
service infrastructure, security and execution environments.

Python manages LLM reasoning, Agent Loop, planning,
RAG, memory, tool selection and evaluation.
```

**Go = Control Plane；Python = Agent Runtime。**

Go 长期负责 HTTP API、Authentication、Project Management、Repository Management、Task Lifecycle、Task State Machine、RabbitMQ Integration、Redis State、SSE Event Streaming、Tool Gateway、Sandbox Manager、Human Approval、Rate Limit、Idempotency、Distributed Lock、Webhook、Observability 的平台侧能力。

Python 长期负责 Agent Loop、Task Planner、Context Builder、Tool Calling、Code RAG、Memory、Skills、Reviewer、Evaluator、LLM Provider、Retrieval Gate、Memory Consolidation 和运行时埋点。

Go 负责 Task Orchestration 和 Service Orchestration；Python 负责 LLM Orchestration。主要 Agent Loop 统一位于 Python，禁止在 Go 重新维护完整 Agent Loop、Planner、Memory、RAG、LLM Tool Reasoning。Go 可以实现 Task Orchestrator、Tool Gateway、Sandbox、Approval；Python 可以选择和请求工具，但不能决定绕过执行策略。

职责跨界必须有真实理由，并在实现前记录 ADR。Phase 1–4 的 Python 本地测试工具是已记录的有限过渡方案，见 ADR 007；Phase 5 迁移执行职责到 Go，不能借此保留两套生产执行路径。

## 4. Current Phase Rule

每次开发前读取 `docs/roadmap.md`，识别 **Current Phase**。只能围绕当前阶段及本次请求开发，不能因为“以后可能需要”提前实现后续 Phase。

Day 1 只完成 Phase 0 基线文档和最小骨架；roadmap 的 `Current Phase: Phase 1` 指后续 Python MVP 的允许范围，不授权在 Bootstrap 任务里实现 MVP。

需求明显超出 Current Phase 时，先说明属于哪个 Future Phase。除非用户明确要求提前实现，否则不跨阶段开发；若用户明确授权，应先在 roadmap 记录例外范围、依赖和验收，涉及架构时同步 ADR，不必重复索要已获得的授权。只有当前阶段验收有证据、并明确确认推进后，才更新 Current Phase。

## Long-Term Design Lookup Rule

`references/RepoPilot_full_design.md` 是 RepoPilot 的长期设计参考，
用于保存项目最初的完整目标、应用场景、长期架构、模块职责、
技术选型思路、阶段演进方向和最终 Demo 形态。

Coding Agent 不需要在每一个开发任务中完整读取该文件。

日常开发优先读取：

1. `AGENTS.md`
2. `docs/roadmap.md`
3. 与当前任务相关的 `docs/architecture.md`
4. 与当前任务相关的 `docs/decisions.md`
5. 当前 Repository 中的真实代码

当上述信息已经足够确定 Current Step 的目标和最小实现方案时，
不要为了重复确认而重新完整读取长期设计文档。

### When to Consult the Full Design

出现以下任一情况时，Coding Agent 应主动查阅
`references/RepoPilot_full_design.md` 中与当前问题相关的章节：

1. 开始一个新的 Phase，需要重新确认该阶段在最终系统中的作用。

2. 不清楚当前功能最终应该演进成什么形态。

3. 不清楚某个模块为什么存在，或者它在 RepoPilot 整体架构中的位置。

4. Current Step 的目标虽然明确，但不知道如何进一步拆分成小型、
   可验证的实现任务。

5. `docs/architecture.md` 对当前问题描述不足，
   无法确定合理的设计边界。

6. 准备进行重大架构调整、服务职责调整或核心通信方式调整。

7. 准备引入新的基础设施、框架、中间件或长期依赖。

8. 当前实现可能已经偏离 RepoPilot 最初的产品目标或架构目标。

9. 需要重新规划 Roadmap、拆分新的 Phase 或重新设计后续 Step。

10. 需要判断 Hermes、Go Agent Scaffold 或其他参考实现中的某个能力
    是否应该迁移到 RepoPilot。

11. 当前存在多个合理技术方案，
    需要理解原始设计背景后再进行选择。

12. 用户提出了一个目标明确但实现路径不清楚的新需求，
    需要判断它属于哪个 Phase、Step 或长期模块。

### How to Consult the Full Design

查阅长期设计文档时，优先定位与当前问题相关的章节，
不要求每次重新阅读整份文件。

查阅后必须结合当前项目状态重新判断，不能直接照搬长期设计。

判断顺序：

```text
Long-Term Design
        ↓
Current Architecture
        ↓
Accepted ADR
        ↓
Current Roadmap
        ↓
Existing Code
        ↓
Current Step Minimal Design

```

## 5. Small Step Rule

每次只交付一个小型、可验证闭环：一个接口、一个模块、一个 Tool、一个流程或一个 Bug Fix。先检查现有代码，再说明最小变更。说明最小变更不等于每个可逆任务都要停下等批准。

不要一次生成大量系统代码，不预建几十个接口、空类、Go package、Python module、数据库表或 Proto。长期目标目录只在对应功能被实际需要时展开。

### 5.1 Current Step Lock

`docs/roadmap.md` 除了 Current Phase，还必须维护 **Current Step**。Current Step 是日常 Vibe Coding 的直接开发锁。

- 默认只实现 Current Step。
- 当前 Step 的验收没有证据时，不进入下一 Step。
- Coding Agent 不得自行修改 Current Step 为下一项。阶段或步骤推进需要用户明确确认，随后再同步 roadmap。
- 用户说“继续”时，只执行 roadmap 中紧接着的一个 Step，不把“继续”解释成完成整个 Phase。
- 一个请求覆盖多个 Step、多个架构层或同时包含“新依赖 + 新行为 + 集成改造”时，先拆分成可验证步骤并报告拆分方案；除非用户明确要求连续完成多个已编号 Step，否则本次只执行第一个 Step。
- Future Phase、长期目录、ADR 或完整设计文档中的内容都不能绕过 Current Step Lock。

### 5.2 Task Contract Before Coding

任何会修改业务代码、测试或依赖的任务，在编辑前先给出一份简短 Task Contract：

```text
Current Phase:
Current Step:
Goal:
In Scope:
Out of Scope:
Expected Files / Areas:
Validation:
Stop Condition:
```

Task Contract 只用于确认最小闭环，不生成新的长期需求。实施过程中发现需要跨 Step、跨语言边界、引入新的外部依赖或触碰未声明的架构区域时，停止扩展并报告原因。

### 5.3 Stop After One Verified Step

当前 Step 的验收通过后立即停止继续开发，先完成 Diff Review、文档同步和结果报告。可以给出下一 Step 建议，但不能顺手实现。只有用户明确授权连续执行多个编号 Step 时，才允许在同一次任务中继续，并且每个 Step 仍需独立验证。

禁止顺手重构无关代码、清理未来可能用到的目录、升级无关依赖或提前补齐“看起来迟早会需要”的基础设施。发现旁路问题时记录为 follow-up，不把它混入当前实现。

## 6. No Fake Completion

严格禁止返回固定假数据冒充真实执行、用 TODO 冒充完成、空实现或 `pass` 冒充逻辑、仅定义接口却声称功能完成、Mock 掉核心业务后声称系统可运行。

未实现的功能明确标记 **NOT IMPLEMENTED**。真实数据模型和纯接口任务可以按其有限范围验收，但不能宣传为完整 Runtime。测试中的 mock、fixture、fake provider 必须明确标注用途，不能代替真实 Coding 闭环的验收。

模型停止调用工具不等于任务成功；迭代上限、超时、取消、缺少验证、工具失败必须显式呈现。禁止根据模型自述宣称测试通过。

## 7. Test Requirement 与 Eval 原则

新增核心逻辑必须有相关测试，覆盖真实行为、失败路径和边界；不要编写仅复述实现的测试。结束任务前执行相关测试并报告命令、结果及未覆盖范围。测试失败时不得宣称任务完成；受环境阻塞时明确说明未验证。

文档或空目录变更不需要伪造业务测试：检查文件清单、链接、格式和跨文档一致性，并说明没有可运行代码。Day 1 不安装测试框架。

从 Phase 1 开始要求单元测试和本地 Bug Repository 的真实测试证据。Phase 9 才建设系统化 Deterministic Eval、Coding Eval、LLM Judge、Release Gate、指标平台；不能以“Eval 在后面”为由推迟核心测试。

Coding 成功必须由可信验证命令、退出码和实际断言支撑；缺少验证命令、零测试收集、超时或必需检查被跳过，都不能算通过。不能删除、弱化验收断言来让 Agent 过关。LLM Judge 评价需求完成度、Review 和说明质量，不能覆盖测试失败或安全失败。后续 Gate 必须记录数据集、代码版本、Prompt/模型版本、命令和结果；未经基线验证的百分比不能作为成果。

## 8. Architecture Discipline

禁止无理由引入 Kafka、Milvus、Elasticsearch、Kubernetes、Celery、复杂 Workflow Framework 或复杂 Multi Agent Framework。引入任何新基础设施前必须回答并记录：

- 它解决什么已经出现的真实问题？
- 当前 Phase 是否需要？
- 现有组件为什么不能解决？
- 最小验证方式、运行成本和退出方式是什么？

重大选择先写 ADR，再更新 roadmap 范围。Redis、PostgreSQL、RabbitMQ、Docker、gRPC 等即使已经列入长期技术栈，也只能按 roadmap 引入。

## 9. Dependency Discipline 与代码质量

优先标准库和少量可解释依赖。增加依赖需说明必要性、维护和许可证情况，不能为一个简单功能引入大型框架。不要整体带入参考项目的依赖树。

Go 保持 Handler/API、Application、Domain、Infrastructure 边界。未来遵循 `context.Context`、显式错误处理、小接口、需要时依赖倒置、结构化日志、graceful shutdown、适用时 table driven tests。避免 global mutable state、god service、god package、不必要抽象和过早微服务化。

Python 保持透明的 Agent Loop，使用 type hints、小模块、显式 Agent state、结构化 Tool Result 和可测试的依赖边界。dataclass / pydantic 仅在有用时使用；I/O 场景按需要使用 async。避免巨大 `agent.py`、Prompt 散落、Tool 无限制 subprocess、隐式全局状态，以及层层框架包装。Prompt 和模型配置应可定位，后续评测时可追溯版本。

## 10. Tool Rule

长期工具模型必须考虑 Name、Description、Input Schema、Risk Level、Timeout、Sandbox Requirement、Approval Requirement、Idempotency、Trace。模型侧 Schema、Go 执行策略和实际参数必须一致，不能出现两套各自演化的工具权限定义。

| Risk Level | 行为 | 执行要求 |
| --- | --- | --- |
| LOW | 限定仓库的 list/read/search/diff 等只读操作 | 路径、权限、输出量仍需限制 |
| MEDIUM | apply_patch、run_test、受控 run_command | 长期经 Go Tool Gateway 在 Docker Sandbox / Git Worktree 内执行 |
| HIGH | git commit、git push、create PR、删除远端分支及其他高风险操作 | 必须经过 Human Approval；审批就绪前禁用 |

风险根据具体参数和副作用判定，不能只看工具名称。非幂等操作不得盲目重试。每次执行保留 tool_call_id、结果、错误、耗时及必要的审计信息；秘密信息不得进入日志。

## 11. Security Rule

RepoPilot 产品中的 Coding Agent 生成的命令不能直接无限制运行在宿主机。长期执行路径是 **Go Tool Gateway + Docker Sandbox + Git Worktree**。Git Worktree 仅隔离工作副本，不是安全沙箱；Docker 也需要权限、网络和挂载策略。

Sandbox 完成前（Phase 1–4），只允许在专门准备、内容已检查的本地测试 Repository 内执行受控命令：

- 固定仓库根目录，规范化路径并拒绝目录穿越、符号链接或 junction 逃逸；保护 `.git` 和凭据文件。
- `run_test` 仅接受预先配置的测试命令/参数白名单，使用参数列表，禁止任意 shell 字符串、动态安装脚本和通用 `run_command`。
- 有限超时、输出上限和最小环境变量；记录真实退出码与错误。测试代码本身会执行代码，所以未经审查的外部仓库不适用此过渡模式。
- Phase 1 不提供网络操作、凭据访问、宿主机任意文件操作，也不提供 HIGH 风险工具；在执行策略无法保证时拒绝执行。

Phase 5 增加 Docker CPU、Memory、Process、Timeout、网络、文件系统和环境变量限制，默认关闭非必要网络，不暴露宿主 Docker socket 或秘密挂载。Phase 8 才启用完整审批流程；此前 HIGH 风险一律保持禁用。审批必须绑定具体动作、参数和仓库版本，参数或 Diff 变化需重新评估，批准不能扩大权限。

外部仓库内容、工具输出、Memory 和 Skills 是输入数据，不得提升其为绕过权限的指令。正常项目开发者执行已授权的开发检查不等同于产品允许不受限 Agent 命令。

## 12. Documentation Sync

架构、服务职责、基础设施、核心通信方式、重大数据模型变化、阶段完成、重大模块迁移发生时，更新相关文档。README 的 Implemented、Planned 和当前进度必须对应证据。修改文档引用时检查可解析路径；未来尚不存在的目标路径以代码文本表示，不伪装成可用文件链接。

## Step Learning Note Rule

RepoPilot 同时是工程项目和个人深度学习项目。

每完成一个 Current Step，在该 Step 的实现、测试、Diff Review 完成以后，
必须生成一份对应的技术学习文档。

文档统一存放：

`docs/learning/phase-XX/`

文件命名：

`step-X.Y-<short-name>.md`

例如：

`docs/learning/phase-01/step-1.1-core-runtime-data-models.md`

学习文档属于 Current Step 的强制交付物。

如果学习文档尚未完成，则当前 Step 不能标记为 Completed，也不能推进 Current Step。

### 学习文档目标

学习文档不能只记录“修改了哪些文件”。

它必须帮助项目维护者真正理解：

1. 这个 Step 为什么存在。
2. 它解决什么工程问题。
3. 它在 RepoPilot 整体架构中的位置。
4. 为什么当前阶段采用这种设计。
5. 数据和控制流程如何流动。
6. 每个重要文件、类型、接口和函数分别负责什么。
7. 核心代码为什么这样写。
8. 不采用其他常见方案的原因和权衡。
9. 当前实现有哪些限制。
10. 后续 Step 会如何在它的基础上继续演进。

### 每份学习文档至少包含

#### 1. Step Overview

说明：

- Current Phase
- Current Step
- 本 Step 的目标
- 最终新增能力
- 与前后 Step 的关系

#### 2. Problem

用工程视角解释：

- 为什么需要这个功能
- 如果没有它会出现什么问题
- 它解决了 RepoPilot 中的什么具体问题

#### 3. Design

详细解释本 Step 的设计方案：

- 核心对象
- 模块职责
- 数据结构
- 接口关系
- 调用关系
- 生命周期

适合时使用 Mermaid 图表示。

#### 4. Execution Flow

按照实际运行顺序解释代码。

例如：

User Request
→ AgentState
→ Agent Loop
→ ToolCall
→ ToolResult
→ Observation
→ Next Iteration

必须结合当前 Step 的真实实现，不写脱离代码的抽象流程。

#### 5. File Changes

逐个解释本 Step 主要新增或修改的文件：

- 文件路径
- 文件职责
- 为什么需要这个文件
- 与其他文件如何协作

#### 6. Core Code Walkthrough

选取本 Step 最重要的核心代码进行讲解。

要求：

- 给出必要的核心代码片段
- 逐段解释职责
- 解释关键字段
- 解释关键函数输入和输出
- 解释重要状态变化
- 解释异常或失败路径
- 解释为什么采用当前实现

不要简单复制整个源码文件。

只选真正值得理解的核心代码。

#### 7. Key Concepts

总结本 Step 涉及的重要技术知识。

例如：

- dataclass
- Protocol
- async
- Agent Loop
- Tool Calling
- State Machine
- RabbitMQ ACK
- Redis Lock
- gRPC
- pgvector
- Docker Sandbox

具体内容根据当前 Step 决定。

需要从工程应用角度解释这些知识在 RepoPilot 中是如何被使用的。

#### 8. Design Decisions

解释本 Step 中的重要选择和权衡：

- 为什么选择当前方案
- 有哪些备选方案
- 当前方案的优点
- 当前方案的代价
- 什么情况下未来可能调整

如果属于正式架构决策，同时同步 `docs/decisions.md`。

#### 9. Error and Edge Cases

说明：

- 可能的错误
- 边界情况
- 当前代码如何处理
- 测试如何验证

#### 10. Testing

记录真实执行的：

- 测试文件
- 测试场景
- 测试命令
- 测试结果
- 每个关键测试验证什么

禁止只写“测试已通过”。

#### 11. What I Should Be Able to Explain

最后生成一组面向项目维护者和面试准备的问题。

例如：

- 为什么需要 AgentState？
- ToolCall 和 ToolResult 为什么需要 tool_call_id？
- 为什么 AgentResult 要区分 success 和 exhausted？
- 这种模型设计对后面的 Agent Loop 有什么帮助？

这些问题应该覆盖当前 Step 最重要的知识点。

#### 12. Step Summary

用简洁方式总结：

- 本 Step 做了什么
- 我应该掌握什么
- 下一 Step 会在什么基础上继续

### 内容真实性

学习文档必须基于当前 Repository 中真实存在的实现。

禁止描述尚未实现的功能为已完成。

未来设计必须显式标注为 Planned。

代码片段必须来自当前实现，或者明确标记为用于解释的简化示例。

### 与开发流程的关系

Current Step 的完成顺序调整为：

Implementation
→ Tests
→ Diff Review
→ Documentation Sync
→ Step Learning Note
→ Final Report
→ STOP

只有以上步骤全部完成以后，当前 Step 才具备 Completed 条件。

## 13. ADR Rule

重大技术决策写入 `docs/decisions.md`，至少包含 Status、Context、Decision、Reasons（Reason）、Consequences、Future Review Conditions。Accepted 是确认的架构方向，Proposed 是待验证提案，两者都不代表交付。

新基础设施、语言职责变化、持久化方案和核心通信变化先记录 ADR。保留历史；推翻决策时追加替代决定并交叉引用，不能悄悄删除理由。

## 14. Migration Rule

任何从 Hermes 或 Go Agent Scaffold 借鉴的重要模块均记录在 `docs/migration.md`，包括 Source、Target、What was reused、What was redesigned、Why、License considerations、Status，并补充版本、测试和证据。

遵循 **Read → Understand → Identify reusable idea → Redesign for RepoPilot → Migrate minimal required code → Add tests**。先只读，不修改参考项目，不整体复制。候选迁移不等于已迁移；只参考思想也应注明，不能伪造代码来源。

复制第三方代码前核实对应版本 License、上游 attribution，保留要求的版权及许可文本。许可证未确认时先澄清来源，不能把“没有发现 License”视为自由复制。不要把个人助手、外部 delegate_task 或 Go Agent Runtime 直接变成 RepoPilot 主运行时。

## 15. Vibe Coding 长期工作协议

1. **STEP 1 — Read AGENTS.md**：读取项目开发规则。
2. **STEP 2 — Read docs/roadmap.md**：读取范围控制器。
3. **STEP 3 — Identify Current Phase**：说明任务属于哪个阶段。
4. **STEP 4 — Read relevant architecture section**：核对边界及相关 ADR。
5. **STEP 5 — Inspect existing code before editing**：确认现状和用户已有修改，避免覆盖。
6. **STEP 6 — Propose minimal change**：说明本次最小闭环、验证方式和关键限制。
7. **STEP 7 — Implement only requested scope**：只实现请求范围。
8. **STEP 8 — Run tests**：运行相关测试；文档任务执行相应检查。
9. **STEP 9 — Review diff**：检查意外修改、假实现、秘密和跨阶段内容；未初始化 Git 时使用变更前后清单及内容比较。
10. **STEP 10 — Update relevant documentation**：同步范围、状态、迁移和决策。
11. **STEP 11 — Report**：报告 changed files、design decisions、test commands、test results、remaining limitations。

## 16. Completion Checklist

- [ ] Does it belong to Current Phase? 如有明确授权的例外，是否已记录？
- [ ] Does it respect Go / Python boundary?
- [ ] Did we introduce unnecessary infrastructure?
- [ ] Is the implementation real? 未实现部分是否标记 NOT IMPLEMENTED？
- [ ] Are relevant tests included? 文档任务是否明确适用检查？
- [ ] Did tests pass? 是否报告命令、结果及未执行原因？
- [ ] Does documentation need updating?
- [ ] Does migration.md need updating?
- [ ] Does decisions.md need updating?
- [ ] 是否检查 Tool Security、Diff、参考项目和用户原有修改？
- [ ] Can the change be explained clearly in an interview?
- [ ] - [ ] Has the Current Step learning note been created or updated under `docs/learning/`?
- [ ] Does the learning note explain the actual implementation, core code, execution flow, tests, design trade-offs and interview-level concepts?
