# CTX-09 同绑定分页只读审计

**结论：现候选需要修订原生绑定条件并人工审阅（`needs_case_revision`）；旧证据的 `partial` 保持不变。** 固定现有九条记录、生产工具与预算合同后，不能补出同一真实句柄的“第一页完整三条、第二页累计六条、共三页且第三页失败”。自然九条结果低于单条工具上限，生产行为是一次交付九条；这不是生产续读机制故障。本次未连接数据库、网络、真实模型或 embedding；未修改题集、测试、生产代码和旧证据。

## 可复算证据

输入是既有冻结观察 [CTX-09-F48000.json](../pdos-next-context-fixture-completion-20261029/native-normalized-20261030/CTX-09-F48000.json)。读取路径：

1. `$.bindings.natural_single_binding_control.original_read_call_id` 得到自然目录的原始 READ call ID；同对象 `run_id` 是其运行。
2. 在 `$.bindings.calls` 中选择 `row.id == original_read_call_id`；核对 `row.tool == "category.knowledge.list"`。
3. `raw = row.result` 是账本中的完整原结果。重建实际交给 `tool_message` 的对象：`full = {**raw, "execution_ref": {"call_id": row.id, "read_kind": row.binding.read_kind}}`。
4. 生产 `serialized(full)` 等价于 `json.dumps(full, ensure_ascii=False, sort_keys=True, default=str)`，保留默认 JSON 空格；**不是** compact separators。`len(text)` 统计 Unicode 字符数，不是 UTF-8 字节数。
5. 用生产 `context_budget.estimate_tokens(text)` 计算：宽字符计 1，其他字符按总数除 4 向上取整；宽字符范围见源码第 14–20 行。这是确定性预算估算，不是服务商实际 token usage。

复算命令（仅 Python 标准库）：

```sh
python3 docs/reports/evidence/pdos-next-ctx09-binding-audit-20261030/recompute.py
```

[脚本](recompute.py)先核对[来源 SHA](source-sha256.json)，再从生产源码 AST 载入序列化、估算、切片函数，避免导入应用或配置；[实跑结果](recomputed.json)保存本次输出。

| 度量 | 结果 |
|---|---:|
| 完整目录对象 | 9 |
| `serialized(full)` 字符数 | **9,325** |
| 确定性估算 tokens | **2,451** |
| 生产单条工具上限 | 4,000 |
| 续读信封上限 | 3,936 |
| 每段 JSON 转义后负载预算 | 3,716 |
| 即使交给原分页函数，实际段数 | **1** |
| 前三条闭合前缀字符 / tokens | 3,341 / 881 |
| 前六条闭合前缀字符 / tokens | 6,530 / 1,723 |
| 前九条闭合前缀字符 / tokens | 9,302 / 2,445 |

当前夹具的九个独立对象估算依次为 `281,281,281,281,281,281,241,241,241` tokens。最后三条仅含 `not_provided` 目录元数据，没有未披露正文。上述值来自同一自然 READ，未拼接其他运行。夹具选择把九条业务目录建为九个 `KnowledgeEntry` 是既有实现事实，**不是两设计要求九条目录必须对应九个数据库实体**。

## 关键合同与代码

- [registry.py:86](../../../../pdos-next/server/pdos_next/agent_kernel/registry.py#L86)：`ToolSpec.max_result_tokens` 默认 4,000；[host.py:334](../../../../pdos-next/server/pdos_next/agent_kernel/host.py#L334)：不超限直接返回原值。现自然结果 2,451 小于 4,000，因此不会生成多页句柄。
- [result_continuation.py:38](../../../../pdos-next/server/pdos_next/agent_kernel/result_continuation.py#L38)：按 JSON 转义后估算 token 预算二分切字符串；[同文件:65](../../../../pdos-next/server/pdos_next/agent_kernel/result_continuation.py#L65)：分段重建原 JSON。它不按 `items` 或业务条目边界分页。
- [host.py:314](../../../../pdos-next/server/pdos_next/agent_kernel/host.py#L314)：续读再次进入原注册 READ，校验原结果摘要，再按 `min(max_result_tokens,4000)-64` 分页；[result_continuation.py:96](../../../../pdos-next/server/pdos_next/agent_kernel/result_continuation.py#L96)：句柄绑定完成的原 READ、run、isolation、来源模型调用与摘要，不能借另一运行的证据补齐。
- [domain_reads.py:30](../../../../pdos-next/server/pdos_next/agent_kernel/domain_reads.py#L30)：现有 `page_size` 控制原生 list 的对象数量；`page_size=3` 可以走原生 cursor 的 3、6 累计覆盖，但三个 list 是三个 READ，不会转成“同一九条 READ 的三个 `result.read` 片段”。
- [目录夹具:55](../../../../pdos-next/server/tests/agent_kernel/eval_v0_ctx09_directory_support.py#L55)：六个 Artifact 实际只登记代码和状态；[同文件:88](../../../../pdos-next/server/tests/agent_kernel/eval_v0_ctx09_directory_support.py#L88)：六条短目录正文、三条未知元数据。没有现成丰富业务事实可直接扩成约三页。
- [候选测试:529](../../../../pdos-next/server/tests/agent_kernel/test_eval_v0_handle_candidate_pg.py#L529)：显式把“同句柄累计完整对象 ID 为前三/前六、总三页、第三页失败”列为候选绑定条件；[同文件:545](../../../../pdos-next/server/tests/agent_kernel/test_eval_v0_handle_candidate_pg.py#L545)：明确独立 cursor 不得修复另一绑定。

## 与两份设计的完成定义区分

[上下文设计 §6.3](../../../design/2026-10-28-xiaopai-context-design.md#63-单条工具结果上限与续读)要求超限才给句柄，已有 `page_size` 沿用；X2 DoD 第 247 行要求超限句柄、续读前复核和撤权拒读。**它未规定每页三个业务对象，也未规定所有九条目录必须走 `result.read`。** 既有真实原 READ、同句柄第二页与第三页受控失败、原来源复核，以及独立自然目录/cursor 控制，分别覆盖相应机制；它们不能合并宣称 CTX-09 原题通过。

[日常问答/RAG 设计切片 B](../../../design/2026-10-27-xiaopai-daily-assistant-enterprise-rag-design.md)第 816 行要求引用可核对、部分失败如实呈现、lookup 与实际读账本一致，也没有 3→6/9 的固定片段要求。X3 仍要求人工维护评测题、两档正确率基线；两设计另有真实模型、真人审阅等尚未验证项。本审计只解决候选与实现合同是否吻合，不能宣布两设计全部正式验收完成。

## 最小下一步与恢复条件

1. 保留原 CTX-09、旧观察和 `partial`。在活动状态中登记 `needs_case_revision`，修订稿沿用当前用户委托制作候选的授权，正式基准仍需人工维护与审阅；不改原题、旧预期或正式 golden。
2. 可由人工将“原生 list/cursor 的已读六条与未知尾页”及“超长结果的同句柄续读失败”分为两个独立问题，各自引用完整真实 READ 证据。此路径符合既有两设计，不需要修改生产合同；本轮已提供[可审阅修订稿](ctx09-revision-draft.md)，未将它自动置为审阅通过或替换现行题集。
3. 如人工坚持原题的同绑定 3→6/9，则需要独立撰写/提供并审阅**业务上成立的丰富目录资料**，保留题中的九条业务条目、六条已知代码/状态、后三条正文未知，再由合法原生读取产生真实结果并观察自然边界；不额外要求九个数据库实体。`BoundaryContent` 允许真实 `criteria`、`edge_cases`、`decision_record`、`material` 等字段（[category_schemas.py:29](../../../../pdos-next/server/pdos_next/domain/preproject/category_schemas.py#L29)）；这说明技术上不排除自然出现所需边界，**不保证该边界，现有材料也不满足**。不得为了落边界追加 padding、调工具上限/预算、假造 READ、把不包含九条目录记录的长对象冒称九条目录，或把未返回的第七至九条正文写入已读证据/回答。本次不构造/调长度、不执行该路线。
4. 验收定义需明确“完整业务对象数”与“已交付片段中的部分字段”分别计数：任意 JSON 字符分页可能跨对象，`complete_prefix_items` 只证明闭合对象数，不能证明后一个对象没有任何字段被看见。这是后续人工验收定义说明，本次不改实现或现行测试。

**完成**：只读合同/源码/既有证据核对、可复算脚本、来源 SHA 与本报告。**未完成**：原题同绑定 3→6/9、候选人工修订/批准、真实模型及正式整体验收。**恢复条件**：现候选资料仅有六条短代码/状态及三条未知元数据，不足以支撑所写的精确页边界；需要人工候选决策或经审阅且自然符合的有依据资料。该不足不加严两设计 DoD，也不构成新增生产特性的理由。
