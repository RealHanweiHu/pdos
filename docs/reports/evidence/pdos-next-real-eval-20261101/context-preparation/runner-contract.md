# 主会话接口

本文件不启动执行。脚本可由 stdlib `importlib.util.spec_from_file_location` 加载；纯 CLI 只写计划。原生 helper 调用需 `PYTHONPATH` 包含 `pdos-next/server`、`pdos-next/server/tests` 及 `packages/pdos-agent-runtime/src`。

```python
spec = fixtures.prepare_case(person, case_id, focus)
previous = None
revision = None
for ordinal, step in enumerate(spec["steps"]):
    for action in step["before"]:
        control = fixtures.apply_control(person, spec, action, previous)
        revision = control.get("context_revision", revision)
        # Save the exact native control outcome before proceeding.
    payload = fixtures.run_payload(spec, ordinal, previous, context_revision=revision)
    # Root adds idempotency_key, posts normal category agent-runs HTTP,
    # awaits actual Temporal terminal state, then captures actual evidence.
    previous = actual_http_temporal_run_and_evidence(payload)
    revision = None
    for action in step["after"]:
        control = fixtures.apply_control(person, spec, action, previous)
        revision = control.get("context_revision", revision)
        # Save the exact native control outcome before proceeding.
```

`actual_http_temporal_run_and_evidence` 是接口说明中的主会话占位函数，不是生产/工具实现，不能用它伪造运行事实。`FixtureBlocked` 应保存缺少的门槛并只停止该格依赖步骤。CTX-09为原题未绑定情境，应单列 partial 控制，不混入完整原题答题率。CTX-10只统计最终服务器控制；此前真实建状态轮的用量另列，不能把最终零调用计作模型答题成功。

`person` 为主会话提供的合成身份：`tenant/human/peer/agent/category/product/ctx/engine/admin/client/tokens/headers`。`client` 可为指向正常 API 的实际 httpx Client。`prepare_case` 先核对显式 `TEST_DATABASE_URL` 为同 engine target 的本地 `pdos_test`，没有 `.env` fallback，也不自行连接、建立或选择数据库。G0 helper 对 `person.product` 的更新仅发生在本脚本局部副本。

`previous` 必需字段：

| 字段 | 来源与用途 |
| --- | --- |
| `run_id`, `session_id` | 实际 HTTP 接受结果及 Run 详情；续接与原生工作状态控制。 |
| `output` | 实际 Run 结果的 WireAgentOutput 本体，含 `result.assistant.citation_ids`；不要传整层 HTTP envelope。 |
| `read_source_ids` | 从真实 READ/carried ledger 解析的来源对象 ID，不能仅据最终引用推断；CTX-07/08前置核对。 |
| `carried_source_ids` | 实际读取并带入的来源全集；CTX-08须证明私人未引用也参与复核。 |
| `citation_source_ids` | 仅最终实际引用的来源 ID；与 carried 分开。 |
| `issued_citations` | 实际搜索/资料工具发出的 citation 行，含 `citation_id/source_id`，继承时保留 `origin_citation_id`；CTX-06和当前工作状态可见 citation 交叉核验。 |
| `candidates` | 实际 candidates HTTP GET 的 `items` 数组；CTX-11检查 state/receipt/command。 |

真实执行还应采集全部模型请求、时间/usage/cache、账本 READ 与范围/内容足迹、ContextSnapshot、context预算与缩减、实际引用 quote/locator、T0状态、业务回执差、真实最终旧新候选状态。上表只是准备脚本消费的最小输入，不能替代评分所需证据。

`apply_control` 只使用现有 Human 领域命令、工作状态 HTTP API，以及 CTX-08 原夹具已有的隔离合成 audience 删除；不写 AgentRun、ToolCall、READ、模型答案、约束或候选数据行。它不确认或采用候选、不授予 T0，不修改提示/工具/schema或题集。
