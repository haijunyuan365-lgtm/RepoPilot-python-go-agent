# Python Agent Runtime

**Status: PARTIALLY IMPLEMENTED。** Steps 1.1–1.3 已完成；Phase 1.4 Safe Read Tools 已实现并通过本地测试，等待用户验收；完整 Python Coding Agent MVP 仍为 NOT IMPLEMENTED。

Python 拥有唯一主要 Agent Loop，并长期负责 Planner、Context Builder、Tool Selection / Calling、Code RAG、Memory、Skills、Reviewer、Evaluator、LLM Provider、Retrieval Gate 与 Memory Consolidation。

Phase 1.1 在 `app/agent/models.py` 中提供 Provider 无关的 Message、ToolCall、ToolResult、AgentState、AgentResult，并校验工具调用关联、迭代预算和三种终态。

Phase 1.2 在 `app/tools/registry.py` 中提供 Tool 元数据与类型化 handler 契约、确定性注册顺序、按名称查找、重复注册/未知工具显式错误，以及 JSON-compatible 顶层 object Schema 的防御性快照。

Phase 1.3 在 `app/agent/loop.py` 中提供同步 `ChatModel` Protocol 与透明 `AgentLoop`。Loop 每轮将当前消息快照和 Registry Schema 交给模型，顺序执行返回的一个或多个 Tool Call，将结构化成功/失败结果作为 tool Message 回填，并明确返回 succeeded、failed 或 exhausted。未知工具、handler 异常和非法返回会转换为关联原调用的失败 Observation，供下一轮模型读取。

Phase 1.4 在 `app/tools/safe_read.py` 中提供 `RepositoryBoundary`、`list_files` 和 `read_file`。两个 Tool 只接受固定仓库内的相对路径，在跟随 symlink / Junction 后复查边界，保护 `.git` 和常见凭据文件，并限制扫描、列表和读取输出。`read_file` 只返回 UTF-8 且不含 NUL 的普通文本并保留原始换行。`tests/test_safe_read_tools.py` 使用真实临时文件系统覆盖正常读取、参数错误、路径穿越、绝对路径、链接逃逸、受保护文件、二进制内容和截断。连同前三步共有 40 个标准库测试。当前 Step 锁为 1.4，等待用户验收。

Phase 1 后续仍限于 `search_code`、`apply_patch`、`run_test` 和一个真实 LLM Provider，在专门准备的受控测试 Repository 中验证 Bug Fix。完整 Schema 参数语义校验、async/streaming、超时/取消和 Provider 均未实现。

Phase 1–4 本地受控工具是有限过渡；Phase 5 执行职责交给 Go Tool Gateway / Sandbox，Python 保留选择和调用。Phase 8 前 HIGH 工具禁用。范围见 [roadmap](../../docs/roadmap.md)，执行约束见 [AGENTS](../../AGENTS.md)。当前没有 pyproject.toml、外部依赖、Provider 集成或可运行入口。
