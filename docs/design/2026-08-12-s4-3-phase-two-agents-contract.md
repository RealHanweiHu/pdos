# S4-3 Phase 2 双 Agent 实施合同

> 日期：2026-08-12  
> 状态：冻结，后续行为变化必须版本化  
> 依据：`2026-08-09-preview-execution-plan.md` S4-3、`AI_Runtime_Architecture.md`、`Event_Catalog.md`、S2 Agent/Finding 安全边界

## 1. 目标与非目标

本工作项增加同一 AI runtime 的两份订阅配置：

- **Engineering Intelligence**：对 Development BOM 与工程变更事件给出影响分析建议。
- **Quality Intelligence**：对失败测试与客诉做项目内聚类，并给出 CAPA 风险建议。

两只 Agent 的唯一写出口仍是 `cehub_ai.findings`。Agent 不得直接写 Development BOM、ECR/ECN、Complaint、NCR、Root Cause、CAPA Action 或其他业务表。本版不增加 Agent 互审、不增加自由 SQL/HTTP/shell 工具，也不提前实现 S4-4 的 Multimodal/User Context 层。

## 2. Agent、事件与 Finding 契约

| Agent key | Prompt version | 精确订阅 | 允许的 Finding type |
|---|---|---|---|
| `engineering_intelligence` | `engineering-intelligence-v1` | `DEVELOPMENT_BOM_CREATED`、`DEVELOPMENT_BOM_ITEM_ADDED`、`CHANGE_RECORD_CHANGED` | `bom_impact_suggestion`、`change_impact_suggestion` |
| `quality_intelligence` | `quality-intelligence-v1` | `TEST_FAILED`、`COMPLAINT_CREATED` | `quality_cluster_alert`、`capa_suggestion` |

`TEST_FAILED` 同时保留 Project Intelligence 订阅，因此一次事件会按各自的 project+agent+debounce window 生成两个相互独立的 run。未知事件及未登记组合必须静默忽略或在确定性预检中拒绝。

四种 Finding 均使用既有 `RiskSuggestionPayload`：

- `title` / `description`：证据支持的影响或聚类陈述；
- `likelihood` / `impact`：仅是建议评分，必须经人审；
- `mitigation_plan`：工程缓解或 CAPA corrective 建议；
- `contingency_plan`：应急或 CAPA preventive 建议；
- `target_date`：可选建议日期。

任何候选都必须引用当前冻结 run 的至少一个触发 event row id。引用其他项目、其他租户或当前 run 之外的事件时，Finding 在落库前被确定性预检拒绝。

## 3. 人审与业务应用

状态机继续使用 `pending_review → accepted/rejected → applied`，Accept 与 Apply 是两个独立人工动作并分别鉴权：

1. Reviewer 可接受原建议、编辑后接受或拒绝；
2. accepted Finding 仍不改变业务事实；
3. 另一独立 Apply 请求重新验证 tenant/project/事件引用与当前数据库真值；
4. 四种 Phase 2 Finding 的 v1 Apply 目标均为项目 `Risk`，并保留 Finding→Risk、Event、Audit 链路；
5. Apply 不修改 BOM/ECR/ECN 或任何质量记录。真实 CAPA 仍必须由有权限的人在 Quality/CAPA 工作流中创建并走四眼和有效性门禁。

这一落点避免把模型建议伪装成已批准工程分析或 CAPA 事实，同时让被采纳建议进入现有风险闭环而不是停留在聊天文本。

## 4. 只读证据与出门白名单

除既有 project/recent-event/verified-memory 三工具外，只对对应 Agent 增加一个只读工具：

- `get_engineering_evidence`：本项目 BOM 摘要、BOM item 计数及 ECR 摘要；
- `get_quality_evidence`：本项目 failed/blocked Test Case、Complaint、NCR 摘要。

`pdos_agent` 只能通过 lease-bound、security-barrier 投影视图读取这些数据。每个结果必须有 `shown_count/total_count/truncated/continuation`，默认最多 20 条，不得静默截断。

模型出口只允许以下 reference 字段：`reference_id/entity/entity_id/label/excerpt`。明确排除用户身份、Customer 标识与 reference、Document/Object Storage key、原始附件、BOM item attributes、质量 document refs 及任意未列字段。所有 tenant/project 范围来自 server-frozen run，模型参数不是政策事实。

## 5. 迁移与发布

- migration：`0024_phase_two_agents`，只扩展 append-only Agent/Finding CHECK 约束；downgrade 恢复 Phase 1 合同。
- 数据库安全模板同步更新 Agent keys、Finding types、两张只读投影视图与精确 grants；`pdos_agent` 对全部业务表继续零写。
- 两份 prompt 与 `golden/phase-two-agents-v1.json` 一并版本化。换 prompt/模型前必须完整重跑 Phase 1+2 golden cases，不得由自动化写入可信根。
- UI 复用 AI Review 收件箱，只增加 Agent/Finding 标签；编辑、证据跳转、Accept/Edit/Reject/Apply 交互不分叉。
- 生产 migration、安全模板应用及部署仍是单独的人授权动作，本工作项只完成本地隔离验收。

## 6. 验收合同

1. 四个 Agent prompt 均独立版本化；Phase 1 prompt/tool 前缀不因 Phase 2 工具而变化。
2. 精确事件路由通过：BOM create/item/change→Engineering，TEST_FAILED/COMPLAINT→Quality，TEST_FAILED 同时→Project。
3. dispatcher 对同一 TEST_FAILED 建立两个独立 run；同 Agent 同窗口继续 debounce。
4. 两个新工具只返回当前 lease 的项目数据，显式分页；越界 Project 直接拒绝。
5. 模型上下文含受控工程/质量 reference，排除全部禁止字段；无证据时只能 `no_action`。
6. 四种候选均通过确定性 schema/Agent/event/evidence 预检；跨 Agent type、跨 run evidence、未知 type 全拒绝。
7. 每类 Finding 至少一条 golden case；Phase 1 golden suite 继续全绿。
8. 人工 Accept 与独立 Apply 后创建 Risk；Risk/Event/Audit/Finding action 全链路一致，重放幂等。
9. `pdos_agent` 可读新增投影、可经受控函数写 Finding，但对 BOM/ECR/质量/Risk 等业务表直接 INSERT/UPDATE/DELETE 仍为 0 权限。
10. 真实 worker/API/UI 验收覆盖至少 Engineering 与 Quality 各一条候选、一个 no-action/越界错误路径，浏览器 console 0 error/0 warning。
11. Ruff/format/mypy、Server 全量测试、Web lint/type/test/build、migration upgrade/downgrade/metadata drift 全绿后，方可勾选 S4-3。

