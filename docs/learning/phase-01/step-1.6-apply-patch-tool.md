# Phase 1.6 学习笔记：Apply Patch Tool

## 1. Step Overview

- **Current Phase**：Phase 1 — Python Coding Agent MVP
- **Current Step**：Phase 1.6 — Apply Patch Tool
- **一句话能力说明**：本 Step 让 Agent 第一次能够把一个经过严格校验的单文件 unified diff 真实、受控地写入 Repository，并获得由落盘前后内容重新生成的 Diff Observation。
- **本 Step 目标**：实现固定 Repository 范围内的真实代码修改，同时让格式错误、上下文冲突、路径越界和写入失败显式可见，并保证校验失败时不留下部分修改。
- **前置能力（Implemented）**：Steps 1.1–1.5 已提供数据模型、Tool Registry、最小 Agent Loop、`list_files`、`read_file` 和 `search_code`。
- **本 Step 新增能力（Implemented / Awaiting Acceptance）**：严格单文件 unified diff 解析、多个 hunk 应用、上下文冲突检测、链接写入拒绝、原子替换和真实 Diff 输出。
- **后续能力（Planned / NOT IMPLEMENTED）**：Phase 1.7 才实现 `run_test`。当前修改完成后还不能执行测试并根据失败继续修复。

## 2. Agent Execution Position and Capability Gap

### 2.1 本 Step 位于完整流程的哪里

```text
User Request
    ↓
AgentState + AgentLoop                         [此前已实现]
    ↓
search_code → ToolResult → Observation         [此前已实现]
    ↓
read_file → ToolResult → Observation           [此前已实现]
    ↓
模型生成 ToolCall(name="apply_patch", patch=...)
    ↓
解析 unified diff                              [本 Step 实现]
    ↓
RepositoryBoundary + 写入专用链接检查          [本 Step 实现]
    ↓
内存应用全部 hunk / 检测冲突                   [本 Step 实现]
    ↓
同目录临时文件 + os.replace                    [本 Step 实现]
    ↓
真实 Diff → ToolResult → AgentLoop Observation [本 Step 实现]
    ↓
run_test → Test Observation                    [Phase 1.7 Planned / NOT IMPLEMENTED]
    ↓
失败后 Retry / 最终测试通过                    [Phase 1.9 Planned / NOT IMPLEMENTED]
```

这张图不能理解成完整 Coding Agent 已经交付。目前真实可运行的是：测试代码直接构造 `ToolCall`，通过 Tool Registry 取得 `apply_patch` handler，handler 修改临时 Repository，再返回 `ToolResult`。已有 `AgentLoop` 能执行任何注册 Tool 并回填 Observation，但项目尚未提供把五个工具统一组装起来的生产入口，也没有真实 LLM Provider 和 `run_test`。

### 2.2 Before：此前为什么仍无法完成修复

Step 1.5 结束时，Agent 已经能够：

1. 用 `search_code` 定位关键词所在文件和行列。
2. 用 `read_file` 读取目标源码。
3. 通过 Agent Loop 请求 Tool，并把 ToolResult 作为下一轮模型可见的 Observation。

流程仍然卡在“知道应该改什么，但不能真实修改”。如果直接把模型输出当作成功，会产生两个严重问题：

- Repository 内容没有变化，后续测试即使存在也只能测试旧代码。
- Patch 与当前文件不一致时没有冲突信号，模型无法知道自己基于过期上下文生成了修改。

### 2.3 Current Step：输入、处理和输出

本 Step 的最小数据流是：

```text
ToolCall.patch
    ↓
参数大小和基本文本校验
    ↓
_parse_patch：header → hunk range → hunk body
    ↓
_resolve_direct_file：仓库边界 + 拒绝链接别名
    ↓
_read_text：有界 UTF-8 读取
    ↓
_apply_hunks：逐行核对 context/removal，并在内存构造新内容
    ↓
_render_unified_diff：根据真实 before / after 重新生成 Diff
    ↓
_atomic_write：临时文件写入、flush/fsync、os.replace
    ↓
ToolResult(success=True, output=<real diff>)
```

任何步骤失败都会返回：

```text
ToolResult(
    tool_call_id=<原调用 ID>,
    tool_name="apply_patch",
    success=False,
    output="",
    error=<明确错误>,
)
```

因此失败是 Agent 可观察、可继续推理的 Observation，而不是被吞掉的 Python 异常，也不是伪成功。

### 2.4 After：流程增加了什么

完成本 Step 后，Agent 已经具备“查找 → 读取 → 修改”三段真实文件能力。成功时 Repository 确实变化，返回内容是实际 before/after Diff；冲突时 Repository 保持原样，下一轮 Agent 可以重新读取文件并生成新 Patch。

当前仍不能把“修改成功”解释为“任务成功”。缺少 Phase 1.7 的真实测试执行和 Phase 1.9 的失败后修复闭环时，代码是否正确尚无验证证据。

## 3. Design

### 3.1 Tool 输入契约

模型可见 Schema 为：

```json
{
  "type": "object",
  "properties": {
    "patch": {
      "type": "string",
      "minLength": 1
    }
  },
  "required": ["patch"],
  "additionalProperties": false
}
```

Patch 必须采用以下最小 unified diff 形式：

```diff
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,2 @@
 def answer():
-    return 41
+    return 42
```

输入只允许描述一个已存在文件，可以包含多个有序 hunk。当前明确拒绝：

- 文件新增或删除（`/dev/null`）。
- 文件重命名。
- 多文件 Patch。
- `diff --git`、`index` 等额外 Git 元数据。
- 任意 shell 或 Git 命令。

### 3.2 核心数据结构

| 对象 | 作用 | 生命周期 |
| --- | --- | --- |
| `_TextLine` | 保存文件一行的内容和真实换行符；可区分 LF、CRLF 和无末尾换行 | 读取目标文件后创建，写入完成后释放 |
| `_PatchLine` | 保存 hunk 行类型（空格、`+`、`-`）、内容及是否有换行 | Patch 解析阶段创建 |
| `_Hunk` | 保存新旧起始行、行数和 hunk body | 一个 Patch 内可以有多个 |
| `_ParsedPatch` | 保存唯一目标路径和全部 hunk | parser 输出，交给应用阶段 |
| `ApplyPatchTool` | 固定 Repository 根、资源上限并执行整个补丁流程 | 每个受控 Repository 创建一个实例 |
| `ToolResult` | 将真实成功 Diff 或失败错误关联回原 `ToolCall` | 返回 Agent Loop，形成 Observation |

这些类型都只是当前进程内的透明结构，没有引入新的序列化协议、数据库或依赖。

### 3.3 三层校验

本实现不是“看到 `+` 和 `-` 就改字符串”，而是分三层验证：

1. **语法层**：检查 `---` / `+++` header、单文件路径、hunk header、正文前缀、声明行数和 `No newline` 标记。
2. **安全层**：复用 `RepositoryBoundary` 检查相对路径、`..`、绝对路径、真实路径、`.git` 和凭据文件；写入再额外拒绝 symlink / Junction 别名。
3. **内容层**：检查 hunk 是否有序、旧范围是否存在、上下文/删除行是否与当前文件逐行相同、新范围是否与前面变化后的偏移一致。

只有三层全部成功，代码才进入写盘阶段。

### 3.4 默认资源边界

| 限制 | 默认值 | 超限行为 |
| --- | ---: | --- |
| `max_patch_chars` | 200,000 字符 | 失败，不解析、不写入 |
| `max_file_chars` | 500,000 字符 | 失败，不应用、不写入 |
| `max_output_chars` | 200,000 字符 | 修改成功，Diff Observation 截断并设置 `truncated=True` |

输入和目标文件超限时不能安全判断完整语义，所以拒绝修改。输出超限发生在真实修改已经完成之后，因此保留成功结果，但必须通过 `truncated` 告诉 Agent 当前 Observation 不完整。

### 3.5 写入一致性边界

一个 ToolCall 只修改一个现有文件，所有 hunk 先在内存应用。写盘采用：

```text
在目标目录创建临时文件
→ 写入完整 UTF-8 内容
→ flush + fsync 临时文件
→ 复制原文件权限位
→ os.replace(临时文件, 目标文件)
```

临时文件与目标文件位于同一目录，因此正常文件系统语义下替换是单文件原子的：其他读取者看到旧文件或新文件，不会看到只写了一半的内容。

这里的“原子”只指单文件替换，不代表多文件事务，也不解决并发 Agent、替换瞬间的路径竞态、目录 fsync 或宿主机安全隔离；这些属于后续 Worktree / Sandbox 和执行编排边界。

## 4. End-to-End Agent Execution Flow

### 4.1 成功路径：修正返回值

用户任务示例：“`answer()` 应该返回 42。”

1. **Agent Loop（此前已实现）**：模型先调用 `search_code(query="return 41")`。
2. **Search Tool（此前已实现）**：返回 `src/app.py` 的命中位置。
3. **Read Tool（此前已实现）**：返回当前文件内容。
4. **模型输出 ToolCall**：

   ```python
   ToolCall(
       id="call-patch",
       name="apply_patch",
       arguments={"patch": "--- a/src/app.py\n..."},
   )
   ```

5. **Registry / Loop（此前已实现）**：按名称找到 `apply_patch` handler 并调用。
6. **`ApplyPatchTool.apply_patch()`（本 Step）**：解析单文件 Patch，验证路径，读取当前 UTF-8 内容。
7. **`_apply_hunks()`（本 Step）**：确认 `return 41` 确实存在，构造包含 `return 42` 的完整新内容。
8. **`_atomic_write()`（本 Step）**：原子替换目标文件。
9. **ToolResult（本 Step）**：返回 `success=True`，`output` 包含真实的 `- return 41` / `+ return 42` Diff。
10. **Agent Loop（此前已实现）**：把 ToolResult 包装成 tool Message，下一轮模型能够看到修改已发生。
11. **下一步（Planned）**：Phase 1.7 的 `run_test` 将验证这次修改；当前尚不能执行。

### 4.2 失败路径：第二个 hunk 冲突

测试构造一个包含两个 hunk 的 Patch：第一个 hunk 与当前文件匹配，第二个 hunk 试图删除不存在的文本。

执行过程是：

```text
第一个 hunk 在内存 result 中成功
    ↓
第二个 hunk 的删除行与 source 不匹配
    ↓
抛出 PatchError("patch conflict ...")
    ↓
尚未进入 _atomic_write
    ↓
原文件字节保持完全不变
    ↓
失败 ToolResult 回到 Agent Loop
```

这就是“校验失败零落盘”的真实含义。它不是失败后回滚，而是失败发生时根本还没有开始修改目标文件。

## 5. File Changes

### 5.1 业务代码与测试

| 文件 | 变更 | 具体新增 / 修改内容 |
| --- | --- | --- |
| `services/agent_runtime/app/tools/apply_patch.py` | **新增** | 新增 `ApplyPatchTool`、输入/文件/输出三项上限、严格 unified diff parser、内部行与 hunk 数据结构、仓库和链接写入检查、UTF-8 有界读取、多 hunk 内存应用、上下文冲突检测、CRLF/无末尾换行处理、真实 Diff 生成、原子替换、成功/失败 ToolResult 和 `build_apply_patch_tool()` 工厂 |
| `services/agent_runtime/app/tools/__init__.py` | **修改** | 导出 `ApplyPatchTool` 与 `build_apply_patch_tool`；保持 Registry 首先初始化，并添加中文注释解释该导入顺序用于避免 `app.agent.loop ↔ app.tools` 循环导入 |
| `services/agent_runtime/tests/test_apply_patch_tool.py` | **新增** | 新增 10 个测试方法，使用真实临时 Repository、真实文件写入、真实 symlink/Junction，覆盖成功、多个 hunk、冲突零落盘、无效 Patch、越界/凭据/链接、非文本、大小限制、CRLF 和无末尾换行 |

### 5.2 状态与说明文档

| 文件 | 变更 | 具体同步内容 |
| --- | --- | --- |
| `docs/roadmap.md` | **修改** | Step 1.5 标记 Completed；Current Step 更新为 1.6 / Awaiting Acceptance；记录实现边界、60 个测试和 Step 1.7 仍未实现 |
| `docs/architecture.md` | **修改** | 当前实现范围更新到 Phase 1.1–1.6；新增 Apply Patch 输入、三层校验、原子写入、Diff 和限制说明 |
| `README.md` | **修改** | 更新项目结构、Current Step、Implemented / Planned、60 个测试证据和下一推荐 Step |
| `services/agent_runtime/README.md` | **修改** | 增加 Runtime 级 Apply Patch 行为、测试范围、过渡安全边界和当前限制 |
| `docs/learning/phase-01/step-1.6-apply-patch-tool.md` | **新增** | 当前学习笔记，基于真实代码讲解流程、实现、测试、权衡、限制和面试知识点 |

`docs/decisions.md` 没有修改：ADR 007 已接受 Phase 1–4 的 Python 受控本地工具过渡方案，本 Step 没有改变 Go / Python 长期职责，也没有引入新基础设施。

`docs/migration.md` 没有修改：本 Step 没有复制 Hermes、Go Agent Scaffold 或其他第三方实现；长期设计只用于确认 `read_file → apply_patch → run_test` 的流程位置。

## 6. Core Code Walkthrough

### 6.1 Tool 定义固定能力边界

真实代码：

```python
return Tool(
    name="apply_patch",
    description=(
        "Apply one unified diff to one existing UTF-8 repository file. "
        "Use --- a/path and +++ b/path headers; file creation, deletion, "
        "rename, and multi-file patches are not supported."
    ),
    input_schema={
        "type": "object",
        "properties": {"patch": {"type": "string", "minLength": 1}},
        "required": ["patch"],
        "additionalProperties": False,
    },
    handler=self.apply_patch,
)
```

Tool 描述直接告诉模型当前只支持一个现有文件，避免 Schema 看起来允许任意 Git Patch。Registry 保存这份 Provider 无关定义，未来 Provider 只需做格式转换。

### 6.2 严格按 hunk 计数解析

真实核心逻辑：

```python
while old_seen < old_count or new_seen < new_count:
    if index >= len(raw_lines):
        raise PatchError("hunk body does not match its declared line counts")
    logical = self._strip_line_ending(raw_lines[index])
    if logical == _NO_NEWLINE_MARKER:
        self._mark_previous_without_newline(body)
        index += 1
        continue
    if not self._has_line_ending(raw_lines[index]):
        raise PatchError(
            "patch body lines must end with a line break; use the "
            "no-newline marker for an unterminated file line"
        )
    if not logical or logical[0] not in {" ", "+", "-"}:
        raise PatchError(f"invalid hunk body line: {logical!r}")
```

hunk header 中的旧行数等于“上下文行 + 删除行”，新行数等于“上下文行 + 新增行”。parser 按声明计数消费正文，能够识别正文缺失、计数过多和第二个文件 header，避免宽松解析误改代码。

### 6.3 写入比读取采用更严格的链接规则

真实代码：

```python
file_path = self._boundary.resolve(relative_path)
lexical_path = Path(os.path.abspath(self._boundary.root / Path(relative_path)))
if os.path.normcase(str(lexical_path)) != os.path.normcase(str(file_path)):
    raise RepositoryAccessError(
        "apply_patch does not write through symbolic links or junctions"
    )
```

`RepositoryBoundary.resolve()` 先跟随链接并确认真实目标仍在仓库内。写入阶段进一步比较用户所写的词法路径和解析后的真实路径：即使链接目标也在仓库内，仍拒绝通过别名写入。

原因是读取链接只暴露已授权仓库内内容，而写入链接会让“Patch header 指向的文件”和“真正被修改的文件”不同，增加审查歧义和副作用风险。

### 6.4 先在内存应用全部 hunk

真实核心代码：

```python
for patch_line in hunk.lines:
    if patch_line.kind in {" ", "-"}:
        if current >= len(source) or not self._line_matches(
            source[current], patch_line
        ):
            raise PatchError(
                f"patch conflict at source line {current + 1}: "
                "context or removed text does not match"
            )
        if patch_line.kind == " ":
            result.append(source[current])
        current += 1
    elif patch_line.kind == "+":
        result.append(
            _TextLine(
                content=patch_line.content,
                ending=preferred_ending if patch_line.has_newline else "",
            )
        )
```

- 空格行必须匹配并保留。
- `-` 行必须匹配但不进入新结果。
- `+` 行进入新结果，不消耗旧文件行。
- `_line_matches()` 同时比较文本和“是否有换行”，防止无末尾换行语义被悄悄改变。

这里操作的是内存列表，不是打开原文件边解析边写，因此后面的 hunk 冲突不会留下前面 hunk 的修改。

### 6.5 返回真实 Diff 而不是回显输入

```python
diff = self._render_unified_diff(
    original_lines,
    updated_lines,
    parsed.path,
)
self._atomic_write(file_path, updated)
```

模型输入只表达“希望怎样改”；工具输出需要表达“实际怎样改”。因此实现用 `difflib.SequenceMatcher` 比较真实 before / after，再生成统一格式 Diff。即使输入 hunk 的上下文范围较窄，输出仍代表最终文件变化。

### 6.6 原子替换

真实核心代码：

```python
with os.fdopen(
    descriptor,
    "w",
    encoding="utf-8",
    errors="strict",
    newline="",
) as stream:
    stream.write(content)
    stream.flush()
    os.fsync(stream.fileno())
os.chmod(temporary_path, stat.S_IMODE(file_path.stat().st_mode))
os.replace(temporary_path, file_path)
```

新内容先完整写入同目录临时文件，随后一次替换目标。`newline=""` 防止 Python 在写入时自动重写已经确定的 CRLF / LF；权限位在替换前从原文件复制。

## 7. Key Concepts

### 7.1 Unified Diff

**通俗解释**：它是一份带定位信息的“删哪些行、加哪些行”说明书。

**工程定义**：unified diff 由旧/新文件 header 和一个或多个 hunk 组成；hunk 使用旧范围、新范围以及空格/`-`/`+` 前缀描述上下文、删除和新增。

**在本 Step 中**：`patch` 是 Agent 到写入工具的输入协议。严格结构让工具能够在修改前验证模型意图是否仍适用于当前文件。

**缺失后果**：如果只用不带上下文的字符串替换，同一个文本出现多次时无法稳定定位，也难以审查修改范围。

### 7.2 Hunk 与 Context Conflict

**通俗解释**：hunk 是一小块局部修改；context 就是它周围的“指纹”。

**工程定义**：hunk 声明变更在新旧文件中的行范围，并包含未变化的上下文行。应用时上下文或删除行与当前文件不一致称为 conflict。

**在本 Step 中**：`_apply_hunks()` 精确匹配内容和末尾换行存在性，冲突返回失败 ToolResult。

**缺失后果**：Agent 基于旧版本文件生成的 Patch 可能改错位置，或静默覆盖用户/其他任务的新修改。

### 7.3 Repository Boundary

**通俗解释**：它是围绕允许修改的 Repository 画的一道围栏。

**工程定义**：`RepositoryBoundary` 对相对路径做词法检查，解析真实路径后再确认目标仍位于固定根目录，并阻止 `.git` 与常见凭据路径。

**在本 Step 中**：Patch header 的路径必须通过 Boundary，写入还拒绝链接别名。

**缺失后果**：`../`、绝对路径或仓库内逃逸链接可能修改宿主机其他文件。

### 7.4 Atomic Replace

**通俗解释**：先在旁边写好完整新文件，再一次性把旧文件换掉。

**工程定义**：在同一文件系统中使用临时文件和 `os.replace()`，使目标路径从旧内容切换到完整新内容，不暴露中间部分写入状态。

**在本 Step 中**：它保护单文件落盘过程；解析或冲突失败甚至不会进入该阶段。

**缺失后果**：直接覆盖写入时，进程异常、编码错误或磁盘错误可能留下半个文件。

### 7.5 Observation

**通俗解释**：Observation 是工具把“实际发生了什么”告诉 Agent 的回执。

**工程定义**：RepoPilot 使用与原 `tool_call_id` 关联的结构化 `ToolResult`，表达成功输出、失败错误、耗时和截断状态。

**在本 Step 中**：成功 Observation 是重新生成的真实 Diff；失败 Observation 是明确的格式、安全、冲突或 I/O 错误。

**缺失后果**：模型只能猜测文件是否真的改变，无法可靠地重新读取、重试或解释失败。

## 8. Design Decisions

### 8.1 为什么当前只支持单文件 Patch

单文件使“全部 hunk 先验证、一次原子替换”形成清晰闭环。多文件 Patch 需要事务或可靠回滚策略，否则第三个文件失败时前两个文件可能已经改变。当前 Bug Fix MVP 可以通过多个 ToolCall 逐文件修改，不应为未来便利提前引入多文件事务。

代价是一次调用不能同时修改源码和测试文件；未来出现真实需求时，应先设计多文件一致性和 Observation，而不是简单循环写入。

### 8.2 为什么不调用 `git apply` 或系统 `patch`

标准库 parser 的行为、支持范围和安全检查都在 Python 代码中可见，不依赖宿主机命令版本，也不会把 Patch 交给更宽泛的外部执行器。代价是当前只实现 unified diff 的受控子集。

Phase 5 后执行职责迁移至 Go Tool Gateway / Sandbox 时可以重新评估底层实现，但共享契约和失败语义必须保持一致。

### 8.3 为什么不支持新增、删除和重命名

这些操作改变目录结构、恢复语义和审查风险；删除尤其需要更严格的副作用控制。Step 1.6 的最小验收只是“正常修改、冲突/无效 Patch、越界拒绝”。因此当前只修改既有普通文本文件。

### 8.4 为什么拒绝仓库内链接写入

仓库内链接虽然不越界，但 Patch 显示的路径和真实落盘路径可能不同。写操作比读操作副作用更大，因此选择更严格的直接路径约束，以提高审查可解释性。

### 8.5 为什么成功输出由 before / after 重新生成

直接回显输入只能证明工具收到什么，不能证明实际改了什么。重新 Diff 能把 Observation 绑定到真实结果，后续 Review 和测试才有可信输入。

### 8.6 为什么没有新增依赖或 ADR

`pathlib`、`difflib`、`tempfile`、`os` 和 `unittest` 已足以完成当前小闭环。ADR 007 已覆盖 Phase 1–4 本地受控工具的过渡定位，没有新语言边界、基础设施或通信决策需要记录。

## 9. Error and Edge Cases

| 场景 | 当前行为 | 测试证据 |
| --- | --- | --- |
| 缺少、空或非字符串 `patch` | 失败 ToolResult | `test_rejects_invalid_patch_shapes_without_changing_the_file` |
| 多余参数 | 失败，列出 unexpected arguments | 同上 |
| header 缺失、路径不一致 | 失败，不写入 | 同上 |
| hunk 声明计数与正文不一致 | 失败，不写入 | 同上 |
| 无任何 `+` / `-` | 失败，拒绝 no-op Patch | 同上 |
| 多文件 Patch | 明确拒绝 | 同上 |
| `/dev/null` 新增/删除 | 明确拒绝 | 同上 |
| 第二个 hunk 冲突 | 整个 ToolCall 失败，第一个 hunk 也不落盘 | `test_rejects_conflict_without_changing_the_file` |
| `../`、绝对路径、缺失目标 | Boundary 拒绝 | `test_rejects_escape_absolute_protected_and_missing_paths` |
| `.env` 等受保护文件 | Boundary 拒绝 | 同上 |
| 仓库内链接别名 | 写入专用检查拒绝 | `test_rejects_repository_links_even_when_the_target_is_inside` |
| 链接解析到仓库外 | canonical boundary 拒绝 | 同上 |
| 非 UTF-8、NUL 文件 | 失败且不返回/写入部分内容 | `test_rejects_non_text_and_oversized_files_without_writing` |
| 目标文件超过限制 | 失败且不写入 | 同上 |
| CRLF 文件 | 新增行沿用 CRLF | `test_preserves_crlf_and_supports_no_final_newline` |
| 无末尾换行 | 识别 marker 并保持语义 | 同上 |
| Patch 超限 | 失败且不解析 | `test_enforces_input_and_output_limits` |
| Diff 输出超限 | 修改成功、输出前缀、`truncated=True` | 同上 |
| 非法 Repository 根或限制 | 构造阶段 `ValueError` | `test_rejects_invalid_roots_and_limits` |

## 10. Testing

### 10.1 测试夹具为何是真实的

`services/agent_runtime/tests/test_apply_patch_tool.py` 每个测试创建真实临时 Repository 和真实文件。成功断言读取修改后的磁盘字节，失败断言比较修改前后字节；链接测试实际创建 symlink，Windows 无权限时通过 Junction 提供等价目录重解析点。

这些测试没有 Mock `_atomic_write()`、`RepositoryBoundary` 或 parser，因此验证的是实际文件系统行为，而不是伪造的返回值。

### 10.2 十个测试方法验证什么

1. `test_builds_contract_applies_real_change_and_returns_diff`：Schema、Registry、真实修改、关联 ID 和真实 Diff。
2. `test_applies_multiple_hunks_with_insert_and_delete_ranges`：一个文件的多个有序 hunk，以及 `old_count=0` 的纯新增和 `new_count=0` 的纯删除范围都正确落盘。
3. `test_rejects_conflict_without_changing_the_file`：第一个 hunk 成功、第二个冲突时整个文件保持原字节。
4. `test_rejects_invalid_patch_shapes_without_changing_the_file`：参数、header、计数、no-op、多文件和新增文件拒绝。
5. `test_rejects_escape_absolute_protected_and_missing_paths`：父路径、绝对路径、凭据和缺失文件。
6. `test_rejects_repository_links_even_when_the_target_is_inside`：仓库内链接写入与仓库外链接逃逸都失败。
7. `test_rejects_non_text_and_oversized_files_without_writing`：非法 UTF-8、NUL 和超大文件。
8. `test_preserves_crlf_and_supports_no_final_newline`：换行风格及 EOF 语义。
9. `test_enforces_input_and_output_limits`：输入拒绝与成功输出截断语义。
10. `test_rejects_invalid_roots_and_limits`：构造器边界。

### 10.3 实际执行命令与最终结果

实现前基线：

```powershell
cd services/agent_runtime
python -B -m unittest discover -s tests -v
```

结果：

```text
Ran 50 tests in 0.209s
OK
```

最终实现 / 导入检查：

```powershell
python -B -c "import ast; ...; import app.agent, app.tools"
```

结果：3 个变更 Python 文件语法解析成功，`app.agent` 与 `app.tools` 同时导入成功。

最终专项测试：

```powershell
python -B -m unittest tests.test_apply_patch_tool -v
```

结果：

```text
Ran 10 tests in 0.115s
OK
```

最终全量回归：

```powershell
python -B -m unittest discover -s tests -v
```

结果：

```text
Ran 60 tests in 0.298s
OK
```

### 10.4 测试发现并修复了什么

新专项测试第一次通过后，第一次全量回归发现 `app.tools.__init__` 在 Registry 之前导入 `apply_patch`，触发：

```text
app.agent.loop → app.tools → apply_patch → app.agent.models → app.agent.loop
```

此时 `app.tools` 仍处于半初始化状态，旧的 Agent Loop 测试导入失败。修复方式是让其他 Tool 依赖的 `registry` 基础契约先完成导入，再导入具体 Tool 模块，并用中文注释解释不可随意调整的顺序。修复后专项和 60 个全量测试均重新执行并通过。

这说明只运行新增测试不能代替全量回归；模块导出变更会影响已有导入图。

### 10.5 Diff Review

实际检查包括：

```powershell
git diff --check
git status --short
rg -n "TODO|FIXME|NotImplemented|\bpass\b" ...
rg -n "run_test|shell=True|docker|requests|http" ...
```

结论：

- `git diff --check` 未发现空白错误；Windows Git 仅提示已跟踪文件未来可能执行 LF/CRLF 转换。
- 没有 TODO、空实现、固定成功数据或 `pass` 冒充核心逻辑。
- 业务实现没有 subprocess、shell、网络、Docker 或 `run_test`。
- 测试中的 subprocess 只在 Windows 创建 Junction 夹具，参数固定且不属于产品执行路径。
- 变更只覆盖 Step 1.6 代码、测试和必要文档，没有提前实现 Step 1.7。
- 没有新依赖、秘密或参考项目复制内容。

## 11. What I Should Be Able to Explain

完成学习后，应能够清楚回答：

1. `apply_patch` 在 RepoPilot 的 Search → Read → Modify → Test 流程中位于哪里？
2. 为什么 Step 1.6 完成后仍不能宣称 Coding Agent 已完成一次 Bug Fix？
3. unified diff 的 file header、hunk header、context、deletion、addition 分别表达什么？
4. hunk 的 old count 和 new count 分别如何计算？
5. 为什么上下文不匹配必须返回 conflict，而不能做模糊替换？
6. 为什么全部 hunk 先在内存应用，比逐 hunk 直接写文件更安全？
7. 单文件原子替换和多文件事务有什么区别？
8. `flush`、`fsync`、同目录临时文件和 `os.replace` 各自解决哪一段问题？
9. 为什么读取工具可以跟随仓库内链接，而当前写入工具拒绝链接别名？
10. 为什么成功输出要重新比较 before / after，而不是回显输入 Patch？
11. `success=True, truncated=True` 在本工具中准确表示什么？
12. CRLF 和“无末尾换行”为什么属于 Patch 正确性，而不只是格式美观？
13. 为什么当前不调用 `git apply`，这种选择的收益和代价是什么？
14. 为什么单文件 Patch 是当前 Step 的合理最小闭环？
15. `tool_call_id` 如何让成功或失败 Observation 回到正确的 Agent 推理步骤？
16. 第一次全量回归发现的循环导入是怎样形成的，为什么调整导入顺序能修复？

## 12. Step Summary

### 12.1 Before → After

- **Before**：Agent 能查找和读取真实代码，但只能描述修改意图，Repository 不会变化。
- **After**：Agent 能对一个既有 UTF-8 文件应用严格 unified diff；成功得到真实 Diff，冲突得到明确失败，格式或安全校验失败时文件不变。

本 Step 补上了完整 Coding 流程中的 **Modify** 节点。它重要的原因不是“会写文件”这么简单，而是把模型提出的修改转换成一个受边界保护、可冲突检测、可观察、可审查的真实副作用。

### 12.2 Current Limitations

当前真实限制：

- 只支持一个既有普通文本文件；不支持新增、删除、重命名和多文件 Patch。
- 只支持受控 unified diff 子集，不接受 Git metadata 或 binary patch。
- 单次调用只有单文件原子性，没有多文件事务或跨调用回滚。
- 没有并发写锁、文件版本号或 compare-and-swap；context conflict 只能检测内容不匹配，不能完全消除校验与替换之间的竞态。
- Phase 1–4 仍是已检查测试 Repository 的本地过渡工具，不是生产 Sandbox。
- 输出截断时只返回 Diff 前缀，不保证该前缀本身是完整可重新应用的 Patch；它只是 Observation。
- 尚无 `run_test`，不能验证修改是否修复问题。
- 尚无真实 LLM Provider 和统一 Runtime 启动入口。

### 12.3 最应掌握的内容

本 Step 最应掌握：**unified diff 与 hunk 语义、严格解析与上下文冲突、Repository canonical boundary、写入链接风险、先验证后副作用、单文件原子替换、真实 Diff Observation，以及专项测试与全量回归的不同职责。**

下一推荐 Step 是 **Phase 1.7 — Run Test Tool**。它会在当前真实修改能力之后增加白名单测试命令、超时、stdout/stderr 和 exit code，但在用户验收并明确继续前仍是 **Planned / NOT IMPLEMENTED**。
