# Python Agent Runtime

**Status: PARTIALLY IMPLEMENTED。** Phase 1.1 Core Runtime Data Models 已完成；Phase 1.2 Tool Registry Contract 已实现并通过本地测试，等待用户验收；完整 Python Coding Agent MVP 仍为 NOT IMPLEMENTED。

Python 拥有唯一主要 Agent Loop，并长期负责 Planner、Context Builder、Tool Selection / Calling、Code RAG、Memory、Skills、Reviewer、Evaluator、LLM Provider、Retrieval Gate 与 Memory Consolidation。

Phase 1.1 在 `app/agent/models.py` 中提供 Provider 无关的 Message、ToolCall、ToolResult、AgentState、AgentResult，并校验工具调用关联、迭代预算和三种终态。

Phase 1.2 在 `app/tools/registry.py` 中提供 Tool 元数据与类型化 handler 契约、确定性注册顺序、按名称查找、重复注册/未知工具显式错误，以及 JSON-compatible 顶层 object Schema 的防御性快照。测试位于 `tests/test_tool_registry.py`；连同模型回归共 23 个测试，只依赖 Python 标准库。当前 Step 锁为 1.2，等待用户验收。

Phase 1 后续仍限于 Agent Loop，以及 list_files、read_file、search_code、apply_patch、run_test，在专门准备的受控测试 Repository 中验证 Bug Fix。Loop、工具执行、完整 Schema 参数语义校验、真实工具和 Provider 均未实现。

Phase 1–4 本地受控工具是有限过渡；Phase 5 执行职责交给 Go Tool Gateway / Sandbox，Python 保留选择和调用。Phase 8 前 HIGH 工具禁用。范围见 [roadmap](../../docs/roadmap.md)，执行约束见 [AGENTS](../../AGENTS.md)。当前没有 pyproject.toml、外部依赖、Provider 集成或可运行入口。
