# Python Agent Runtime

**Status: PARTIALLY IMPLEMENTED。** Steps 1.1–1.5 已完成；Phase 1.6 Apply Patch Tool 已实现并通过本地测试，等待用户验收；完整 Python Coding Agent MVP 仍为 NOT IMPLEMENTED。

Python 拥有唯一主要 Agent Loop，并长期负责 Planner、Context Builder、Tool Selection / Calling、Code RAG、Memory、Skills、Reviewer、Evaluator、LLM Provider、Retrieval Gate 与 Memory Consolidation。

Phase 1.1 在 `app/agent/models.py` 中提供 Provider 无关的 Message、ToolCall、ToolResult、AgentState、AgentResult，并校验工具调用关联、迭代预算和三种终态。

Phase 1.2 在 `app/tools/registry.py` 中提供 Tool 元数据与类型化 handler 契约、确定性注册顺序、按名称查找、重复注册/未知工具显式错误，以及 JSON-compatible 顶层 object Schema 的防御性快照。

Phase 1.3 在 `app/agent/loop.py` 中提供同步 `ChatModel` Protocol 与透明 `AgentLoop`。Loop 每轮将当前消息快照和 Registry Schema 交给模型，顺序执行返回的一个或多个 Tool Call，将结构化成功/失败结果作为 tool Message 回填，并明确返回 succeeded、failed 或 exhausted。未知工具、handler 异常和非法返回会转换为关联原调用的失败 Observation，供下一轮模型读取。

Phase 1.4 在 `app/tools/safe_read.py` 中提供 `RepositoryBoundary`、`list_files` 和 `read_file`。两个 Tool 只接受固定仓库内的相对路径，在跟随 symlink / Junction 后复查边界，保护 `.git` 和常见凭据文件，并限制扫描、列表和读取输出。`read_file` 只返回 UTF-8 且不含 NUL 的普通文本并保留原始换行。`tests/test_safe_read_tools.py` 使用真实临时文件系统覆盖正常读取、参数错误、路径穿越、绝对路径、链接逃逸、受保护文件、二进制内容和截断。

Phase 1.5 在 `app/tools/search_code.py` 中提供大小写敏感、单行字面量 `search_code`。工具复用 `RepositoryBoundary`，可搜索一个相对文件或目录；按路径和行号确定性返回包含 `path`、`line`、`column`、`text` 的 JSON 数组，无命中返回成功空数组。候选文件、目录项、单文件字符、命中数和 JSON 输出都有上限，截断保持 JSON 可解析并设置 `ToolResult.truncated`。`tests/test_search_code_tool.py` 使用真实临时文件系统覆盖 10 个搜索、参数、安全、非文本和限制场景；该 Step 已完成。

Phase 1.6 在 `app/tools/apply_patch.py` 中提供严格的单文件 unified diff `apply_patch`。工具只修改固定 Repository 内既有 UTF-8 普通文本文件，拒绝绝对/穿越/受保护路径、链接写入、新增/删除/重命名和多文件 Patch。所有 header、hunk 计数、顺序、上下文及换行语义先在内存校验和应用，成功后才通过同目录临时文件与 `os.replace` 原子替换；返回值是根据实际前后内容重新生成的 Diff。Patch、目标文件和输出都有字符上限，支持 CRLF 与无末尾换行。`tests/test_apply_patch_tool.py` 使用真实临时文件系统覆盖 10 个成功、冲突、格式、安全、文本和限制场景。连同前五步共有 60 个标准库测试。当前 Step 锁为 1.6，等待用户验收。

Phase 1 后续仍限于 `run_test` 和一个真实 LLM Provider，并在专门准备的受控测试 Repository 中验证 Bug Fix。多文件补丁事务、文件新增/删除/重命名、完整 Schema 参数语义校验、async/streaming、超时/取消和 Provider 均未实现。

Phase 1–4 本地受控工具是有限过渡；Phase 5 执行职责交给 Go Tool Gateway / Sandbox，Python 保留选择和调用。Phase 8 前 HIGH 工具禁用。范围见 [roadmap](../../docs/roadmap.md)，执行约束见 [AGENTS](../../AGENTS.md)。当前没有 pyproject.toml、外部依赖、Provider 集成或可运行入口。
