# 实施交接：RAG 切片 A + 上下文切片 X1

日期：2026-10-28  
交接对象：代码执行代理（Codex）  
状态：**待执行**  
适用工程：`pdos-next/`

本文件是可以逐步照做的操作说明。每个任务都写明要改的文件、具体改法、不能做的事、要加或要改的测试、要跑的命令和完成判据。遇到“停止条件”里的情况，**停下来报告，不要自行变通**。

依据设计（只在需要理解原因时查阅，执行以本文件为准）：

- [小Pai日常问答与企业 RAG 设计 v0.4](2026-10-27-xiaopai-daily-assistant-enterprise-rag-design.md) §6.2、§6.3、§8.2、§13 切片 A；
- [小Pai上下文设计 v0.2](2026-10-28-xiaopai-context-design.md) §5.1、§5.2、§5.4、§5.5、§6.1、§8、§9、§11 切片 X1；
- [设计确认稿](2026-10-08-pdos-next-design-confirmation.md) P30、P32。

所有路径相对仓库根目录 `ai-native-R&D-platform/`。后端代码在 `pdos-next/server/pdos_next/`，后端测试在 `pdos-next/server/tests/`，前端在 `pdos-next/web/src/`。文中行号按 2026-10-28 工作树，仅供定位，以函数名为准。

---

## 0. 范围

**本次要做（10 个任务，按表中顺序执行；后一个任务可能依赖前一个）**：

| 编号 | 任务 | 来源 |
|---|---|---|
| A1 | 个人全局对话不再默认预载品类技能；“新建品类 → 与小Pai一起创建”显式带上该技能 | RAG §6.2 |
| A2 | 固定系统提示补充日常问答与公司资料规则 | RAG §6.3 |
| A3 | 纯对话回答由服务器标注“未查公司资料” | RAG §8.2 |
| X1-1 | 模型连接配置增加上下文窗口字段 | 上下文 §6.1 |
| X1-2 | 每次模型调用记录分段体积估算 | 上下文 §9 |
| X1-3 | 会话历史保留规则：撤权才隐藏、更新只标注 | 上下文 §5.1、P32 |
| X1-4 | 会话历史分层与体积上限 | 上下文 §5.5 |
| X1-5 | 运行内冻结历史，只复核权限 | 上下文 §5.2、P32 |
| X1-6 | 跨轮延续技能 | 上下文 §5.4 |
| X1-7 | Anthropic 路线增加缓存标记 | 上下文 §8 |

X1-3 与 X1-4 改同一个函数，必须一起做；X1-2 依赖 X1-1 的新字段；X1-5 依赖 X1-3 的 `outcome_state`。

**本次不做**：个人偏好（RAG §6.5，另出交接）；工作状态、单条结果上限与续读、运行内清理（上下文 X2、X3）；`assistant.search` 等企业检索（RAG 切片 B）；欢迎示例文案（等切片 B 完成后再按可用能力更新）；任何真实模型调用。

---

## 1. 全局规则（每个任务都适用）

1. **不提交、不推送**：除非用户明确要求，不执行 `git commit`、`git push`。
2. **不动别人的在途修改**：工作树里有其他会话尚未提交的改动。不要回退、重排、格式化或“顺手修复”你没有被要求改的代码。
3. **不调用真实模型或服务商**：测试一律用现有的合成客户端（如 `tests/agent_kernel/test_gateway.py` 里的 `Client`、`configured_route`）。
4. **数据库测试**：只用显式的 `TEST_DATABASE_URL`（以及 `DATABASE_URL`、`AUTH_DATABASE_URL`、`DISPATCH_DATABASE_URL`）指向已核对的独立临时 `pdos_test` 库，不得读取或回退 `.env`。没有可用的测试库时，只跑纯测试，把数据库测试列为“未运行”，不要自己建库或改连接串。
5. **不改冻结文件**：不改 `docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md`、确认稿、`pdos-next/contracts/operations.json`、`events.json`、`acceptance.json`。`openapi.json`、`payloads.schema.json` 只能通过导出脚本重新生成（X1-1）。
6. **不新增依赖**，不新增数据库迁移（本批任务都不需要迁移；如果你认为需要，停下来报告）。
7. **错误码**：新的错误原因只能在 `pdos_next/error_catalog.py` 的 `REASONS` 中登记并映射到已有分类，不新增分类。
8. **前缀冻结**：系统提示与工具定义里不放动态内容（AGENTS.md 不可协商项 4）。
9. 每完成一个任务，跑该任务列出的检查；全部完成后跑 §12 的总检查。

### 停止条件（任一出现即停，报告现状与原因）

- 要改的文件里有不是你写的未提交改动，而你的改动会和它们交叉（同一函数或相邻几行）；
- 任务要求之外的测试开始失败，且原因不在本次改动；
- 需要新增迁移、依赖、错误分类，或修改第 5 条列出的冻结文件；
- 某个任务要改的文件数明显超过本文件列出的范围（超出 2 个以上）；
- 导出合同后，`openapi.json` 或 `payloads.schema.json` 出现与 `context_window_tokens` 无关的大段差异。

---

## 2. 开工前检查（必须做）

```bash
cd ai-native-R\&D-platform
git status --short
git diff --stat -- \
  pdos-next/server/pdos_next/agent_kernel/bootstrap.py \
  pdos-next/server/pdos_next/agent_kernel/conversation.py \
  pdos-next/server/pdos_next/agent_kernel/graph.py \
  pdos-next/server/pdos_next/agent_kernel/requested_skills.py \
  pdos-next/server/pdos_next/agent_kernel/gateway.py \
  pdos-next/server/pdos_next/providers/agent_client.py \
  pdos-next/server/pdos_next/providers/types.py \
  pdos-next/server/pdos_next/model_configuration/host.py \
  pdos-next/server/pdos_next/schemas/model_configuration/dto.py \
  pdos-next/web/src/components/category-create/personal-xiaopai.tsx \
  pdos-next/web/src/components/pai-conversation.tsx
```

- 记录哪些目标文件已有未提交改动（2026-10-28 已知 `conversation.py` 当天有在途修改）。
- **对已有在途改动的文件**：先把清单报告给用户，确认这些改动已完成、可以在其上继续，再开始对应任务。
- 记录基线：在 `pdos-next/server` 下跑一次 §12 的纯测试命令，保存失败清单，作为“改动前已失败”的基线。

---

## 3. 任务 A1：个人全局对话不再默认预载品类技能

**目的**：普通对话不再每条都带 16.7 KB 的 `category_framing` 技能；“新建品类 → 与小Pai一起创建”仍然带上它。

### 3.1 后端

文件：`pdos-next/server/pdos_next/agent_kernel/bootstrap.py`，方法 `default_preload`（约 464 行）。

现在：

```python
if scope.category_id is None:
    return ("category_framing",)
```

改为：

```python
if scope.category_id is None:
    # 个人全局自由对话只用技能目录，业务技能由页面动作显式请求或 skill.load 加载
    # （RAG 设计 v0.4 §6.2）。
    return ()
```

不要改这个方法里品类、提案、项目分支的逻辑。

### 3.2 前端

“与小Pai一起创建”按钮在 `pdos-next/web/src/components/category-workspace.tsx`（约 69 行，`新建品类` 对话框里，调用 `onOpenPai()`）。它打开的是 `PaiRail` 里的 `PersonalXiaopai`（`components/category-create/personal-xiaopai.tsx`）。

步骤：

1. 把 `onOpenPai` 的类型从 `() => void` 改为 `(options?: { presetSkillKeys?: string[] }) => void`。
2. 只在“与小Pai一起创建”这个按钮上传入：`onOpenPai({ presetSkillKeys: ["category_framing"] })`。其他调用点不传参数，行为不变。
3. 用 `grep -rn "onOpenPai=" pdos-next/web/src` 找到传入 `onOpenPai` 的上层组件，把 `presetSkillKeys` 存进打开小Pai时的状态，经 `PaiRail` 传给 `PersonalXiaopai`。在 `PaiRail` 和 `PersonalXiaopai` 的 Props 上各加一个可选属性 `presetSkillKeys?: string[]`。
4. 在 `ScopedPersonalXiaopai` 里：当 `presetSkillKeys` 非空、当前没有 `run`、`requestedSkills` 为空时，在 `useEffect` 中请求 `const reading = await api<{ items: SkillChoice[] }>("v1/personal/agent-skills")`（写法与 `components/pai/skill-picker.tsx` 第 25 行相同，`SkillChoice` 类型从该文件导出或照其字段在本文件声明），把返回 `items` 中 `skill_key` 在 `presetSkillKeys` 里且 `enabled === true` 的项转换为 `{ key: item.skill_key, version: item.skill_version, digest: item.skill_digest }`，调用 `setRequestedSkills`。已存在的发送逻辑（约 307 行）会把 `requested_skills` 带上，不需要再改发送代码。
5. 技能未启用或取不到时不报错、不阻止发送（模型仍可用 `skill.load`）。

**不要做**：不改 `SkillPicker` 本身；不改 `run-start-intent.ts` 的校验；不在服务器端为“新建品类”加新字段。

### 3.3 测试

- 修改 `pdos-next/server/tests/agent_kernel/test_m3_default_preload.py` 中 `test_personal_entry_preloads_category_framing_without_business_scope`：改名为 `test_personal_entry_has_no_default_business_skill`，断言 `f.owner.default_preload(f.scope) == ()`。
- 执行 `grep -rn "category_framing" pdos-next/server/tests`，找出依赖“个人范围默认预载 category_framing”的其他测试，只改这一假设（改为显式 `requested_skills` 或断言空预载），不要改与默认预载无关的断言。
- 前端：如果已有渲染 `PersonalXiaopai` 的测试文件，在其中加一个用例，断言传入 `presetSkillKeys` 时会把对应技能放入请求；没有现成的渲染测试就不新建，在报告里写明“前端由类型检查和 lint 覆盖”。

### 3.4 检查与完成判据

```bash
cd pdos-next/server && uv run ruff check pdos_next/agent_kernel/bootstrap.py
cd pdos-next/web && npm run typecheck && npm run lint
```

- [ ] 个人全局对话（无品类）默认预载为空；
- [ ] “与小Pai一起创建”发起的第一轮请求体里带 `requested_skills`，其中有 `category_framing`；
- [ ] 品类、提案、项目页的默认预载测试全部照旧通过。

---

## 4. 任务 A2：固定系统提示补充规则

文件：`pdos-next/server/pdos_next/agent_kernel/graph.py`，常量 `SYSTEM_BASE`（约 25 行）。

在 `SYSTEM_BASE` 中 “internal IDs or workflow terminology unless the user asks for them.” 这一行**之后**、“Respond to the latest human message; …” 这一行**之前**，插入以下三行（原样复制，英文；每行末尾照原有风格换行）：

```text
For explanation, translation, writing, summarizing or general knowledge, answer directly without company lookups.
When the user asks how "we", the company or this factory does something, or about company standards, parameters, projects or history, look up company data first; never present general knowledge as company practice.
If a lookup finds nothing, say it was not found in the searched scope; never conclude that it does not exist.
```

**注意**：

- 运行开始时会记录系统提示摘要（`gateway.py` 的 `prompt_prefixes`），改动后，改动前已开始、尚未结束的运行恢复时会报 `VERSION_CONFLICT`。这是预期行为，在报告里写明，不要绕过。
- 不为这段文字新增“镜像文字”的测试（AGENTS.md：低风险文案不新增镜像测试）。如果已有测试断言 `SYSTEM_BASE` 原文或摘要，按新文本更新。

检查：

```bash
cd pdos-next/server && uv run pytest tests/agent_kernel/test_graph.py -q
```

- [ ] 三行规则已加入，`SYSTEM_BASE` 其余文字不变；
- [ ] `test_graph.py` 通过。

---

## 5. 任务 A3：纯对话回答标注“未查公司资料”

**规则**：一次运行中，除 `skill.load` 外**没有任何工具调用**时，服务器在结果里附加 `result.assistant = {"version": 1, "kind": "general", "lookup": "not_run"}`；其他情况不附加（切片 B 再补完整状态）。模型自己写的 `assistant` 一律删除。

### 5.1 后端

1. 新建文件 `pdos-next/server/pdos_next/agent_kernel/assistant_result.py`：

```python
"""Server-attached answer grounding for ordinary replies (RAG design v0.4 §8.2)."""

from copy import deepcopy

NON_LOOKUP_TOOLS = frozenset({"skill.load"})


def attach(output, tool_results):
    result = deepcopy(output)
    body = result.get("result")
    if not isinstance(body, dict):
        return result
    body.pop("assistant", None)  # Only the server authors grounding.
    if all(tool.get("tool") in NON_LOOKUP_TOOLS for tool in tool_results):
        body["assistant"] = {"version": 1, "kind": "general", "lookup": "not_run"}
    return result
```

2. 文件 `bootstrap.py`，方法 `verify_result`（约 448 行）末尾现在是：

```python
from .research_result import attach

return attach(result, tool_results)
```

改为：

```python
from .assistant_result import attach as attach_assistant
from .research_result import attach

return attach_assistant(attach(result, tool_results), tool_results)
```

### 5.2 前端

文件：`pdos-next/web/src/components/pai-conversation.tsx`，组件 `PaiResponse`（约 62 行）。

1. Props 类型中 `result?: { summary?: string } | null` 扩展为 `result?: { summary?: string; result?: { assistant?: { lookup?: string } } | null } | null`。
2. 计算 `const notLooked = run.status === "completed" && run.result?.result?.assistant?.lookup === "not_run";`。
3. 在两个返回分支中，正文之后追加 `{notLooked && <p className={styles.lookupNote}>未查公司资料</p>}`（第一个分支本来就是片段 `<>…</>`；第二个分支用 `<>…</>` 包起来）。
4. 在 `pai-conversation.module.css` 增加：

```css
.lookupNote { margin-top: 4px; font-size: 12px; color: var(--text-subtle); }
```

不改其他展示逻辑。

### 5.3 测试

新建 `pdos-next/server/tests/agent_kernel/test_assistant_result.py`（纯测试，不用数据库），至少五个用例：

| 用例 | 输入 | 断言 |
|---|---|---|
| `test_no_tools_marks_not_run` | `tool_results=[]` | `result["result"]["assistant"]["lookup"] == "not_run"` |
| `test_skill_load_only_marks_not_run` | 只有 `{"tool": "skill.load"}` | 同上 |
| `test_any_other_tool_has_no_assistant` | 含 `{"tool": "category.read"}` | `"assistant" not in result["result"]` |
| `test_model_authored_assistant_is_removed` | 输出里自带 `assistant`，且有其他工具 | `"assistant" not in result["result"]` |
| `test_non_dict_result_is_unchanged` | `output["result"]` 为字符串 | 返回值等于输入 |

检查：

```bash
cd pdos-next/server && uv run pytest tests/agent_kernel/test_assistant_result.py tests/agent_kernel/test_verification.py -q
cd pdos-next/web && npm run typecheck && npm run lint
```

- [ ] 纯对话回答下方显示“未查公司资料”；有任何业务读取、研究或候选的回答不显示；
- [ ] 模型无法自行写入 `assistant` 字段。

---

## 6. 任务 X1-1：模型连接增加上下文窗口字段

**做法**：以现有的 `max_output_tokens` 为样板，逐处镜像一个新字段 `context_window_tokens`（可空整数，单位 tokens）。

| 位置 | 改法 |
|---|---|
| `providers/types.py` 的 `ProviderRoute`（约 25 行） | 增加 `context_window_tokens: int \| None = None`；在 `__post_init__` 校验：为 `None`，或为 `int` 且 `1024 <= 值 <= 10_000_000`，否则 `raise ValueError("Invalid context window")`。在 `digest` 属性里**只在不为 None 时**加入 `body["context_window_tokens"]`（照抄同函数里 `openai_response_mode` 的写法），这样现有路由的摘要不变 |
| `model_configuration/host.py` 的 `ModelHost`（约 68–93 行） | 加 `context_window_tokens: int \| None = Field(default=None, strict=True, ge=1024, le=10_000_000)`；如该文件的 `ManagedConnection`（约 112 行）或其他类也保存 `max_output_tokens`，同样加入 |
| `schemas/model_configuration/dto.py`（约 21 行字段、约 48–54 行构造 `ProviderRoute` 处） | 加同样的字段，并在 `ProviderRoute(...)` 中传入 `context_window_tokens=self.context_window_tokens` |
| `web/src/components/model_configuration/contracts.ts` | 类型加 `context_window_tokens?: number \| null` |
| `web/src/components/model_configuration/connection-editor.tsx` | 加一个可选数字输入，标签“上下文窗口（tokens）”，说明文字“不填时按 32,000 估算”；留空提交 `null` |
| `web/src/components/model_configuration/settings.tsx` | 连接详情里显示该值，空值显示“未填写（按 32,000 估算）” |
| `web/src/components/model_configuration/render.test.mjs` | 按现有用例风格，增加该字段的渲染断言 |

上表是已核实的位置。动手前再执行 `grep -rn "max_output_tokens" pdos-next/server/pdos_next pdos-next/web/src`，凡是保存、校验、传递 `max_output_tokens` 的地方都要同样处理 `context_window_tokens`（`providers/types.py` 的 `digest` 按上表条件加入；`agent_client.py`、`client.py`、`gateway.py` 里把它当输出上限用的地方不需要加）。

**合同导出**（只用脚本生成，不手改）：

```bash
cd pdos-next/server && uv run python ../tools/export_contracts.py
cd pdos-next && git diff --stat -- contracts/openapi.json contracts/payloads.schema.json
```

差异应只包含 `context_window_tokens`。出现其他大段差异时，**停止**并报告（可能是其他在途改动尚未导出）。导出脚本因缺少环境变量或数据库而无法运行时，也停止并报告，不要手改合同文件。

**测试**：在 `tests/model_configuration/` 或 `tests/agent_kernel/test_model_configuration_transactions.py`、`test_model_connections_pg.py` 中找到保存/读取 `max_output_tokens` 的用例，仿写：

- 保存 `context_window_tokens=200000` 后读回一致；
- `context_window_tokens=512` 被拒绝；
- 不填时为 `None`，且该路由的 `digest` 与改动前相同（构造一个不带新字段的 `ProviderRoute`，断言其 `digest` 与固定期望值或同参数旧构造一致）。

检查：

```bash
cd pdos-next/server && uv run pytest tests/agent_kernel/test_native_protocols.py tests/agent_kernel/test_openai_compatible.py tests/agent_kernel/test_gateway.py -q
cd pdos-next/web && npm run typecheck && npm run lint && node --test src/components/model_configuration/render.test.mjs
```

- [ ] 配置页可填写、可留空；
- [ ] 现有路由摘要不变；
- [ ] 导出的合同只多了这个字段。

---

## 7. 任务 X1-2：每次模型调用记录分段体积估算

**目的**：知道每次调用里各部分占了多少，后续才能按预算缩减。本任务**只记录，不缩减、不拦截**。

### 7.1 新建 `pdos-next/server/pdos_next/agent_kernel/context_budget.py`

```python
"""Per-call context size estimates (context design §4.2, §9). Recording only."""

import json
import math

DEFAULT_WINDOW = 32_000
TOOL_RESULT_RESERVE = 4_000
FOCUS_CAP = 64_000


def _is_wide(char):
    code = ord(char)
    return (
        0x3400 <= code <= 0x9FFF
        or 0xF900 <= code <= 0xFAFF
        or 0x3000 <= code <= 0x303F
        or 0xFF00 <= code <= 0xFFEF
    )


def estimate_tokens(text):
    if not text:
        return 0
    wide = sum(1 for char in text if _is_wide(char))
    return wide + math.ceil((len(text) - wide) / 4)


def budget_for(route):
    window = route.context_window_tokens or DEFAULT_WINDOW
    reserve = route.max_output_tokens + TOOL_RESULT_RESERVE
    return {
        "window": window,
        "window_configured": route.context_window_tokens is not None,
        "reserve": reserve,
        "focus": max(0, min(window - reserve, FOCUS_CAP)),
    }


def _text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)


def segments(system, tools, messages):
    first_assistant = next(
        (i for i, m in enumerate(messages) if m.get("role") == "assistant"), len(messages)
    )
    envelope_text = _text(messages[0].get("content", "")) if messages else ""
    history = 0
    try:
        conversation = json.loads(envelope_text).get("context", {}).get("conversation")
        if conversation is not None:
            history = estimate_tokens(_text(conversation))
    except (ValueError, AttributeError):
        history = 0
    envelope = estimate_tokens(envelope_text)
    skills = sum(
        estimate_tokens(_text(m.get("content", "")))
        for m in messages[1:first_assistant]
        if m.get("role") == "user"
    )
    loop = sum(estimate_tokens(_text(m.get("content", ""))) for m in messages[first_assistant:])
    values = {
        "system": estimate_tokens(system),
        "tools": estimate_tokens(_text(tools)),
        "skills": skills,
        "envelope": envelope - history,
        "history": history,
        "loop": loop,
    }
    return {"segments": values, "estimated_total": sum(values.values())}
```

### 7.2 接入网关

文件：`agent_kernel/gateway.py`，方法 `turn`。

1. 在构造 `wire` 之后（约 113 行附近）计算：

```python
from .context_budget import budget_for, segments

context_budget = {**budget_for(route), **segments(system, tools, messages)}
context_budget["over_focus"] = context_budget["estimated_total"] > context_budget["focus"]
```

2. 在成功结果的 `saved = {...}` 字典（约 262 行）里增加一项 `"context_budget": context_budget`。

**不要**把 `context_budget` 放进 `request` 字典：`request` 用于计算调用幂等键（`call_key`），放进去会让已保存的调用在恢复时对不上。

### 7.3 测试

- 新建 `tests/agent_kernel/test_context_budget.py`（纯测试）：
  - `estimate_tokens("")==0`；`estimate_tokens("abcd")==1`；`estimate_tokens("充气泵")==3`；中英混合按规则计算；
  - `budget_for` 在未配置窗口时 `window==32000`、`window_configured is False`，`focus == 32000 - (max_output_tokens + 4000)`；配置 200000 时 `focus == 64000`；
  - `segments`：构造“首条信封（含 context.conversation）+ 两条技能 user 消息 + assistant + tool”的消息列表，断言 `history>0`、`skills` 只统计两条技能、`loop` 统计 assistant 之后的消息。
- 在 `tests/agent_kernel/test_gateway.py` 找到断言保存结果的用例，仿写一个：成功调用后保存的结果含 `context_budget`，且 `segments` 有六个键。

检查：

```bash
cd pdos-next/server && uv run pytest tests/agent_kernel/test_context_budget.py tests/agent_kernel/test_gateway.py -q
```

- [ ] 每次成功的模型调用都保存了 `context_budget`；
- [ ] 调用幂等键不变（现有网关与恢复测试通过）。

---

## 8. 任务 X1-3 与 X1-4：会话历史保留规则与分层（同一函数，一起做）

**规则（P32）**：

| 上一轮的情况 | 处理 | `outcome_state` |
|---|---|---|
| 读取结果与现在一致 | 保留回答 | `current` |
| 读取结果变化，或报 `SOURCE_STALE` / `VERSION_CONFLICT` | 保留回答，加备注“资料已更新，回答中的事实需重新读取”；研究行不带 | `updated` |
| 读取报 `FORBIDDEN_SCOPE` / `NOT_FOUND` / `SOURCE_UNAVAILABLE`，或 T0 回执不可读 | 隐藏回答（`historical_outcome` 为 `None`），`sources` 置空，备注“该轮引用的资料已无权读取或已撤回，回答已隐藏” | `hidden` |
| 准备过 T1/T2 候选（调用的 `execution_binding.kind` 为 `unbound`，且该工具在注册表中 `kind == "write"`） | 保留回答，加备注“该轮准备过候选，候选以当前页面状态为准” | 不改变 |
| 调用过没有历史复核器的读工具，或复核时出现其他异常 | 保留回答，加备注“以下读取未复核：工具名列表” | 不改变 |

多种情况同时出现时：有任一 `hidden` 即 `hidden`；否则有任一 `updated` 即 `updated`；否则 `current`。备注可以叠加。

**分层（X1-4）**：`memory()` 返回的 `turns` 按从近到远排列（现状如此）。

- 最近 3 轮（`RECENT_TURNS = 3`）：`historical_outcome.summary` 超过 600 字（`RECENT_ANSWER_CHARS = 600`）时截断，末尾加“…（已截断，完整内容可用 conversation.history 读取）”，并设 `truncated: true`；
- 第 4 轮起到 `page_size`：`goal` 截为前 60 字，`summary` 截为前 60 字（`DIRECTORY_CHARS = 60`），`unfinished` 置空列表，`research` 置空列表，`truncated: true`，备注追加“仅显示目录”；
- 由 `conversation.history` 工具读取时（`layered=False`）：不分层，每轮 `summary` 上限 8000 字（`HISTORY_ANSWER_CHARS = 8000`）。

### 8.1 修改 `agent_kernel/conversation.py`

1. 在文件顶部定义常量：`RECENT_TURNS = 3`、`RECENT_ANSWER_CHARS = 600`、`DIRECTORY_CHARS = 60`、`HISTORY_ANSWER_CHARS = 8000`、`REVOKED_CODES = frozenset({"FORBIDDEN_SCOPE", "NOT_FOUND", "SOURCE_UNAVAILABLE"})`、`UPDATED_CODES = frozenset({"SOURCE_STALE", "VERSION_CONFLICT"})`。
2. 把 `cached_outcome(...)`（约 189 行）改写为 `classify_turn(session, run, readers, consumer, *, include_research_rows=False)`，返回：

```python
{
    "state": "current" | "updated" | "hidden",
    "outcome": {"summary": str, "unfinished": list, "research": list, "notes": list} | None,
}
```

逐个调用的判定按上表：

- `isolation` 不是 `None`/`"main"` 的调用：跳过（与现状相同）；
- `kind == "domain_t0"`：`receipt_id` 为空 → 记“未复核”；回执行查不到 → `hidden`；
- `kind == "unbound"`（执行绑定只有 `unbound`、`read`、`model`、`domain_t0` 四种，见 `execution_schema.py`）：用 `from .tools import default_registry` 取 `default_registry().get(call.tool)`，其 `kind == "write"` 时记“准备过候选”，否则（如 `skill.load`）忽略；`get` 抛错时记“未复核”。**不再** `return None`；
- `kind == "read"`：没有复核器或 `call.state != "completed"` → 记“未复核”（工具名）；否则调用复核器：
  - 抛 `DomainError` 且 `error.code in REVOKED_CODES` → `hidden`；
  - 抛 `DomainError` 且 `error.code in UPDATED_CODES` → `updated`；
  - 抛其他 `DomainError` 或 `KeyError/TypeError/ValueError/AttributeError` → 记“未复核”；
  - 摘要不同或工具名不一致 → `updated`；
  - 一致 → 保持；`research.fanout` 一致时照旧组装研究行（保留现有代码）。
- `updated` 时 `research` 置空列表；`hidden` 时 `outcome` 为 `None`。
3. 修改 `memory(session, run, *, readers, before=None, page_size=10, include_research_rows=False, layered=True)`：
   - 每轮调用 `classify_turn`；
   - 每轮输出保持现有键：`run_id`、`goal`、`status`、`historical_outcome`、`outcome_state`、`sources`、`original_record`；`outcome_state` 取 `current`/`updated`/`hidden`；`hidden` 时 `sources` 为 `[]`；
   - `historical_outcome` 在不为 `None` 时增加 `notes`（列表）与 `truncated`（布尔）；
   - `layered=True` 时按上面的分层规则处理；`layered=False` 时只做 8000 字上限；
   - `fact_policy` 改为：

```text
Historical answers are dated records, not current domain facts. outcome_state "updated" means sources changed after that answer; re-read exact objects before relying on its facts. "hidden" means the answer was withheld because its sources are no longer readable. Use conversation.history for full earlier answers; never infer missing constraints.
```

### 8.2 修改上下文字段合同

文件：`pdos-next/server/pdos_next/skill_packages/context-schemas.json`，`$defs.outcome`：

- 在 `properties` 中增加 `"notes": {"type": "array", "items": {"type": "string"}}` 与 `"truncated": {"type": "boolean"}`；
- **不要**把它们加进 `required`；不要改 `additionalProperties`。

`$defs.memory_turn` 不需要改（键名未变）。

### 8.3 调用方

文件：`bootstrap.py` 方法 `conversation_history`（约 337 行）：调用 `memory(...)` 时传 `layered=False`。

### 8.4 测试

文件：`tests/agent_kernel/test_run_continuation.py`（需要数据库）。

- **改写** `test_cached_read_summary_requires_actual_local_result_and_guard_rechecks_it`：
  - 第一次 `project_context` 后 `outcome_state == "current"`；
  - 把复核器换成返回不同结果（现有写法 `host._history_readers["calc.cost_subtotal"] = lambda *_: {"changed": True}`）后：`host.check_conversation(bound)` **不再抛错**；直接调用 `memory(...)` 得到 `outcome_state == "updated"`，`historical_outcome["summary"]` 仍是原文，`notes` 含“资料已更新”；
  - 用 `readers={}` 调用 `memory(...)`：`historical_outcome` 不为 `None`，`notes` 含“未复核”。
- **新增**：
  - `test_revoked_read_hides_answer`：复核器抛 `DomainError("FORBIDDEN_SCOPE", "…")` → `outcome_state == "hidden"`、`historical_outcome is None`、`sources == []`；
  - `test_prepared_candidate_turn_keeps_answer`：给上一轮插入一条 `AgentToolCall`，`tool` 为已登记的 T1 写命令（如 `work.task.assign`），`execution_binding={"kind": "unbound"}`，满足 `execution_schema.py` 的约束（仿照现有测试插入工具调用的方式）→ 回答保留，`notes` 含“准备过候选”；
  - `test_recent_turns_are_full_and_older_are_directory`：连续 5 轮，每轮 `summary` 为 1000 字 → 最近 3 轮 `summary` 长度 ≤ 600 + 截断提示长度且 `truncated is True`，第 4、5 轮 `summary` ≤ 60 字且 `notes` 含“仅显示目录”；
  - `test_history_tool_returns_full_answers`：`memory(..., layered=False)` 下每轮 `summary` 为原文（≤ 8000 字）；
  - `test_thirty_turn_history_stays_bounded`：30 轮、每轮 1000 字回答 → `estimate_tokens(json.dumps(memory_value, ensure_ascii=False))` ≤ 4000（用 X1-2 的 `estimate_tokens`）。
- 同文件 `test_registered_graph_receives_persisted_task_memory_and_replay_does_not_call_model` 中的断言 `turns[0]["historical_outcome"]["unfinished"] == ["核对适用工况"]` 应仍成立；如因新增键失败，只调整断言，不改被测行为。
- 运行 `tests/agent_kernel/test_context_projection.py`、`test_context_projection_entries.py`、`test_context_projection_pg.py`，确认字段合同修改后通过。

完成判据：

- [ ] 上一轮准备过候选、读取结果有变化、用过未登记复核器的工具时，下一轮都能看到上一轮回答；
- [ ] 撤权的那一轮回答不出现在上下文中；
- [ ] 30 轮长回答的会话历史估算 ≤ 4000 tokens。

---

## 9. 任务 X1-5：运行内冻结历史，只复核权限

**规则（P32）**：一次运行里，会话历史在第一次组装时冻结；之后每次调用模型前只检查“有没有新出现的隐藏轮次”或“会话范围是否已不可读”。内容变化不再打断运行。发现撤权时，当前运行以 partial 收尾。

### 9.1 新错误原因

文件：`pdos_next/error_catalog.py`，在 `REASONS` 中加入：

```python
"CONVERSATION_HISTORY_REVOKED": "FORBIDDEN_SCOPE",
```

### 9.2 `bootstrap.py` 的上下文组装（约 297–315 行）

现状：每次组装都重算 `memory(...)`，与已存摘要不同就抛 `SOURCE_STALE`。改为：

1. 读取 `run.versions.get("conversation_memory")`：
   - 为 `None` → 照常调用 `memory(...)`（分层），并在同一个加锁事务里写入 `run.versions["conversation_memory"] = 值` 与 `run.versions["conversation_memory_digest"] = digest(值)`；
   - 不为 `None` → 直接使用已存的值，不重算。
2. 删除“摘要不同即抛 `SOURCE_STALE`”的分支。

### 9.3 `bootstrap.py` 的 `check_conversation`（约 316 行）

改为：

```python
def check_conversation(self, scope):
    from .conversation import memory

    with self.store.transaction(scope) as (session, run):
        if run.continued_from_id is None:
            return
        frozen = run.versions.get("conversation_memory")
        if frozen is None:
            return
        try:
            current = memory(session, run, readers=getattr(self, "_history_readers", {}))
        except DomainError as error:
            if error.code == "FORBIDDEN_SCOPE":
                raise DomainError(
                    "CONVERSATION_HISTORY_REVOKED", "会话中引用的资料已无权读取或已撤回。"
                ) from None
            raise
        hidden_before = {t["run_id"] for t in frozen["turns"] if t["outcome_state"] == "hidden"}
        hidden_now = {t["run_id"] for t in current["turns"] if t["outcome_state"] == "hidden"}
        if hidden_now - hidden_before:
            raise DomainError(
                "CONVERSATION_HISTORY_REVOKED", "会话中引用的资料已无权读取或已撤回。",
                detail={"run_ids": sorted(hidden_now - hidden_before)},
            )
        # Pages read through conversation.history in this run: same rule.
        for page in run.versions.get("conversation_history_pages", {}).values():
            value = memory(session, run, readers=getattr(self, "_history_readers", {}),
                           before=UUID(page["before"]) if page["before"] else None,
                           page_size=page["page_size"],
                           include_research_rows=page["include_research_rows"],
                           layered=False)
            now = {t["run_id"] for t in value["turns"] if t["outcome_state"] == "hidden"}
            if now - set(page.get("hidden", [])):
                raise DomainError(
                    "CONVERSATION_HISTORY_REVOKED", "已读取的历史资料已无权读取或已撤回。"
                )
```

（`DomainError`、`UUID` 已在该文件中导入则直接用；未导入则按文件现有风格补导入。）

同时修改 `conversation_history`：保存页记录时增加 `"hidden": [该页中 outcome_state 为 hidden 的 run_id 列表]`。

### 9.4 `graph.py` 的 `model` 节点（约 250 行）

在现有 `except DomainError as error:` 中，`RATE_LIMITED` 判断之前加入：

```python
if error.reason == "CONVERSATION_HISTORY_REVOKED":
    return partial(
        state,
        "会话中引用的资料已无权读取或已撤回，本次处理已停止。请重新发起，小Pai会按当前权限重新整理。",
    )
```

### 9.5 测试

- `tests/agent_kernel/test_run_continuation.py::test_revoking_parent_scope_hides_memory_before_model_egress`：应仍通过（删除品类授权后 `check_conversation` 抛 `DomainError`）；补一个断言：`failure.value.reason == "CONVERSATION_HISTORY_REVOKED"`。
- 新增 `test_content_change_does_not_interrupt_running_turn`：组装上下文后改变复核器结果为“内容变化”，`check_conversation` 不抛错，再次组装上下文得到的 `conversation` 与第一次完全相同（冻结）。
- 新增 `test_newly_revoked_turn_stops_with_revoked_reason`：组装上下文后把复核器改为抛 `FORBIDDEN_SCOPE` → `check_conversation` 抛错且 `reason == "CONVERSATION_HISTORY_REVOKED"`。
- 在 `tests/agent_kernel/test_graph.py` 增加：宿主的 `model` 抛 `DomainError("CONVERSATION_HISTORY_REVOKED", "x")` 时，图输出 `status == "partial"`，`summary` 为上面的提示文字（仿照已有的 `RATE_LIMITED` 用例写法）。
- 跑 `uv run pytest tests/command_catalog -q`，确认新错误原因登记无误。

完成判据：

- [ ] 运行中他人修改上一轮读过的对象，当前运行继续；
- [ ] 撤权时当前运行以 partial 收尾并给出提示；
- [ ] 同一运行内多次组装上下文（例如 `skill.load` 后）得到同一份会话历史。

---

## 10. 任务 X1-6：跨轮延续技能

**规则**：续接对话时，上一轮实际加载过的技能（最多 2 个，按最近加载）自动加入本轮预载；未启用的跳过，不报错。

文件：`agent_kernel/requested_skills.py`，函数 `preload(store, scope, fallback=())`（约 56 行）。

改为：

```python
CONTINUED_SKILL_LIMIT = 2


def preload(store, scope, fallback=()):
    if scope.isolation != "main" or scope.trigger != "conversation":
        return tuple(fallback)
    with store.transaction(scope) as (session, run):
        event = session.scalar(select(AgentEvent).where(
            AgentEvent.run_id == run.id, AgentEvent.sequence == 1,
        ))
        raw = event.body.get("requested_skills", []) if event else []
        requested = [RequestedSkill.model_validate(item) for item in raw]
        validate(session, scope, requested)
        base = tuple(item.key for item in requested) if requested else tuple(fallback)
        return base + continued(session, scope, run, exclude=set(base))


def continued(session, scope, run, *, exclude):
    if run.continued_from_id is None:
        return ()
    catalog, keys = SkillCatalog(), []
    events = session.scalars(
        select(AgentEvent)
        .where(AgentEvent.run_id == run.continued_from_id)
        .order_by(AgentEvent.sequence.desc())
    )
    for item in events:
        body = item.body or {}
        if body.get("type") != "skill_loaded" or body.get("isolation", "main") != "main":
            continue
        key = body.get("key")
        if not key or key in exclude or key in keys:
            continue
        skill = catalog.configuration(key)
        if skill is None or not skill_enabled(session, scope, skill):
            continue
        keys.append(key)
        if len(keys) == CONTINUED_SKILL_LIMIT:
            break
    return tuple(keys)
```

说明：

- `skill_loaded` 事件由 `graph.py` 的 `load_binding` 写入，`body` 含 `key`、`version`、`digest`、`isolation`；
- 只取直接父运行（`continued_from_id`），不追溯整条历史；
- 延续的技能按**当前启用版本**加载（新运行，不要求与父运行版本一致）；
- 自动化触发的运行不受影响（函数开头的 `trigger` 判断保持）。

**测试**：在 `tests/agent_kernel/test_requested_skills_pg.py`（需要数据库）中，仿照现有用例插入父运行的 `AgentEvent`：

- 父运行加载过 `proposal_drafting` → 子运行（无 `requested_skills`）预载包含它；
- 父运行加载过 3 个技能 → 只带最近 2 个；
- 父运行加载的技能当前未启用 → 不带入，且不报错；
- 子运行显式请求了 A、父运行加载过 A 和 B → 结果为 `(A, B)`，无重复；
- 非 `conversation` 触发 → 结果等于 `fallback`。

完成判据：

- [ ] 上一轮自加载的技能，下一轮不需要再次 `skill.load`；
- [ ] 未启用的技能不会导致运行失败。

---

## 11. 任务 X1-7：Anthropic 路线增加缓存标记

文件：`providers/agent_client.py`，函数 `request_body`，Anthropic 分支（约 85–131 行，`history` 构造完成之后、`return {...}` 之前）。

加入：

```python
def _cache_mark(message):
    content = message["content"]
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    else:
        content = [dict(block) for block in content]
    if content:
        content[-1]["cache_control"] = {"type": "ephemeral"}
    message["content"] = content


if history:
    _cache_mark(history[0])          # 首条：本次运行组装的上下文信封
    if len(history) > 1:
        _cache_mark(history[-1])     # 末条：随轮次后移
```

（`_cache_mark` 定义为模块级私有函数。）连同 system 上已有的一处，共 3 个缓存断点，在 4 个上限之内。

**不要**改 OpenAI 兼容分支；用量中的缓存字段（`prompt_tokens_details.cached_tokens`）已由 `providers/client.py` 解析并保存在 `usage` 里。

**测试**：在 `tests/agent_kernel/test_native_protocols.py`（或现有断言 Anthropic 请求体的测试文件）中增加：

- 多条消息时：system、首条消息最后一个块、末条消息最后一个块都有 `cache_control`；中间消息没有；
- 只有一条消息时：该消息有且只有一处 `cache_control`；
- OpenAI 兼容请求体与改动前一致。

如果已有测试断言 Anthropic 请求体的完整内容，按新结构更新期望值。

检查：

```bash
cd pdos-next/server && uv run pytest tests/agent_kernel/test_native_protocols.py tests/agent_kernel/test_gateway.py -q
```

**真实缓存命中的实测**（两条路线）需要真实模型调用授权，**不由你执行**；在报告里列为“待用户授权后实测”。

---

## 12. 总检查（全部任务完成后）

```bash
# 后端静态检查（只检查改动文件）
cd pdos-next/server
uv run ruff check pdos_next/agent_kernel/assistant_result.py pdos_next/agent_kernel/context_budget.py \
  pdos_next/agent_kernel/bootstrap.py pdos_next/agent_kernel/conversation.py \
  pdos_next/agent_kernel/graph.py pdos_next/agent_kernel/gateway.py \
  pdos_next/agent_kernel/requested_skills.py pdos_next/providers/agent_client.py \
  pdos_next/providers/types.py pdos_next/model_configuration/host.py \
  pdos_next/schemas/model_configuration/dto.py pdos_next/error_catalog.py

# 纯测试（不需要数据库）
uv run pytest -q tests/agent_kernel/test_assistant_result.py tests/agent_kernel/test_context_budget.py \
  tests/agent_kernel/test_graph.py tests/agent_kernel/test_gateway.py \
  tests/agent_kernel/test_native_protocols.py tests/agent_kernel/test_openai_compatible.py \
  tests/agent_kernel/test_context_projection.py tests/agent_kernel/test_context_projection_entries.py \
  tests/agent_kernel/test_verification.py tests/agent_kernel/test_m3_default_preload.py tests/command_catalog

# 数据库测试（仅在已核对的独立 pdos_test 可用时；四个连接串都须显式给出）
TEST_DATABASE_URL=… DATABASE_URL=… AUTH_DATABASE_URL=… DISPATCH_DATABASE_URL=… \
uv run pytest -q tests/agent_kernel/test_run_continuation.py \
  tests/agent_kernel/test_requested_skills_pg.py tests/agent_kernel/test_context_projection_pg.py \
  tests/agent_kernel/test_model_configuration_transactions.py tests/agent_kernel/test_model_connections_pg.py

# 前端
cd ../web && npm run typecheck && npm run lint && \
  node --test src/components/model_configuration/render.test.mjs src/components/pai/*.test.mjs

# 合同（已知 events 90≠86 为既有失败，与本批无关）
cd .. && python3 tools/validate_contracts.py
```

把每条命令的结果（通过数、失败数、失败用例名）与 §2 的基线对比，只报告新增失败。

---

## 13. 收尾与报告

### 13.1 更新唯一清单

文件：`tasks/ai-native-integrated-todo.md`。找到以“**小Pai上下文设计（2026-10-28，仅文档）**”开头的段落，在该段末尾追加一句（按实际结果填写，不要写没做到的）：

```text
**切片A + X1 实施（日期）**：可用能力——……；必要证据——纯测试 N 项通过、数据库测试 N 项通过/未运行（原因）、前端类型与 lint 通过；剩余缺口——个人偏好、真实缓存命中实测（待授权）、X2/X3。
```

不新增其他段落，不改其他条目。

### 13.2 报告模板（回复给用户）

```text
完成情况：
- A1 …（改了哪些文件，结果）
- …
未完成或偏离：
- …（原因、是否触发停止条件）
测试：
- 纯测试：通过 N / 失败 N（新增失败：…）
- 数据库测试：通过 N / 未运行（原因）
- 前端：typecheck / lint / node --test 结果
需要用户决定或授权：
- 改动前已开始的运行恢复时会报 VERSION_CONFLICT（A2 系统提示变化导致），是否接受
- 真实模型缓存命中实测
在途改动：
- 开工前发现以下文件有他人未提交改动：…；处理方式：…
```

---

## 14. 常见坑

- `cached_outcome` 改名后，全仓 `grep -rn "cached_outcome" pdos-next/server` 确认没有遗漏的调用点。
- `memory()` 新增的 `layered` 参数要有默认值 `True`，避免打断其他调用方。
- `context-schemas.json` 改动后，开发与测试环境里字段被投影删除会直接报错；如果出现 `context_schema_mismatch`，检查 `notes`、`truncated` 是否加在 `$defs.outcome.properties` 里。
- `ProviderRoute.digest` 只在 `context_window_tokens` 不为 `None` 时加入，否则所有现有运行都会因路由摘要变化而 `VERSION_CONFLICT`。
- `context_budget` 只进保存结果 `saved`，不进 `request`。
- 前端 `onOpenPai` 改签名后，TypeScript 会报出所有调用点；只给“与小Pai一起创建”传参数。
- 不要为了让测试通过而放宽权限判断：凡是 `FORBIDDEN_SCOPE` 相关断言失败，先停下来报告。
