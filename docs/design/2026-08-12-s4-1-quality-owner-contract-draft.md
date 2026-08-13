# S4-1 CAPA 质量流程 Owner 确认稿

> 状态：**待公司质量流程 Owner 确认，不是实施规格**
> 日期：2026-08-12
> canonical：`docs/design/2026-08-09-preview-execution-plan.md` S4-1

## 1. 已冻结边界

- 目标链路固定为 Complaint → NCR → 根因 → 纠正/预防措施 → 有效性验证。
- 数据归属 `cehub_quality`；每个对象必须绑定 tenant，v1 同时绑定 Project，以复用现有对象权限和 AI Project Context。
- `COMPLAINT_CREATED` 必须与 Complaint 同事务写 Event + Audit；AI 只能经 Finding 提建议，不能直接修改任何质量记录。
- 本模块不替代 CRM 售后工单、ERP 批次/库存或 MES 生产执行；只保存必要引用与质量治理真值。
- 老 CEHub 只有 Issue 的 `rootCause` / `solution` / QA verification，不能作为正式 CAPA 字段真值，只作为兼容语义参考。

## 2. 推荐 v1 实体与字段

以下是待确认的最小合同；未列字段不在 v1 实现。

| 实体 | 必填字段 | 可选字段/引用 |
|---|---|---|
| Complaint | 编号、Project、标题、问题描述、来源、严重度、发生/报告时间、报告人、Owner、状态 | Customer、客户投诉编号、批次/序列号范围、附件 Document 引用 |
| NCR | 编号、Complaint、偏差/不符合描述、违反要求、严重度、Owner、状态、目标日期 | 即时遏制措施、遏制完成时间、受影响数量/范围、预防措施不适用原因 |
| Root Cause Analysis | NCR、方法、分析结论、根本原因、分析人、状态 | 证据引用；方法建议枚举 `5why / fishbone / 8d / other` |
| CAPA Action | NCR、类型、措施、Owner、到期日、状态 | 完成说明、完成时间、证据引用；类型 `corrective / preventive` |
| Effectiveness Review | NCR、判定标准、观察截止日、结果、Reviewer、复核时间 | 实际结果、证据引用、失败原因 |

统一使用 UUID、数据库时间戳、tenant/project 复合外键；用户引用必须属于当前 tenant，Project 成员引用必须属于当前 Project。编号在 tenant 内唯一并由服务端生成，不接受客户端自报真值。

## 3. 推荐状态与硬闸

### Complaint

`open → triaged → investigating → resolved → closed`

- `triaged` 必须产生至少一个 NCR；不进入“无记录处理完毕”。
- 仅当全部关联 NCR 已关闭，Complaint 才能 `resolved`。
- `closed` 记录关闭人、关闭时间与客户/内部结论；关闭后普通编辑禁止。

### NCR

`open → containment → root_cause → action → verification → closed`

- `containment → root_cause`：即时遏制措施及完成时间齐备。
- `root_cause → action`：存在一份已批准 Root Cause Analysis。
- `action → verification`：至少一条 corrective 已 completed 且有完成证据；同时至少一条 preventive completed，或由 Quality 批准“预防措施不适用”及原因。
- `verification → closed`：最新 Effectiveness Review 结果为 `effective`。
- 结果 `ineffective` 时回到 `action`，保留原措施和复核历史，不覆盖或删除失败记录。

### 子记录

- Root Cause Analysis：`draft → approved / superseded`，批准后不可原地改写；修正创建新版本并 supersede 旧版本。
- CAPA Action：`planned → in_progress → completed`；进入 verification 后不可回退改写，失败复核通过新增措施处理。
- Effectiveness Review：结果仅为 `effective / ineffective`，写入后不可修改或删除。

## 4. 推荐权限与四眼规则

| 动作 | 推荐角色 |
|---|---|
| 创建 Complaint | Owner / Admin / Project Manager / Engineer / Quality；Customer 直提留到 Sprint 5 CRM 入口 |
| Triage、建 NCR、推进质量状态 | Owner / Admin / Quality |
| 填写根因与执行措施 | 被指派的内部 Project 成员 |
| 批准根因 | Quality；批准人不得是该分析记录的分析人 |
| 有效性复核与关闭 | Quality；Reviewer 不得是任一待验措施的 Owner |
| 治理例外 | v1 不提供四眼或证据硬闸 override；Owner/Admin 可重新指派合格人员，但不能自审绕过 |

Supplier / Customer 默认无 CAPA 内部记录读取或写入权限；后续若需要外部协作，另定义脱敏投影，不开放内部根因、成本、证据对象键。

## 5. 需要质量流程 Owner 拍板的五项

1. 是否接受 v1 必须绑定 Project；若量产后投诉允许无 Project，需要指定替代的产品/批次事实源。
2. 来源枚举是否采用 `customer / field / rma / internal`，严重度是否采用 `critical / high / medium / low`。
3. 是否接受“至少一条 corrective；preventive 必须存在或由 Quality 批准不适用原因”。
4. 是否接受“根因批准人 ≠ 分析人、有效性 Reviewer ≠ 任一措施 Owner”，且 v1 不提供 Owner/Admin override。
5. 是否接受不设全局固定天数，但要求观察截止日晚于最后措施完成时间、判定标准在进入 verification 前冻结、至少一条 Document/系统事实证据，并仅由 Quality 作最终关闭。

## 6. 确认后的实施切片

1. 冻结状态机、字段、RBAC 与错误码合同；新增 migration `0021_quality_capa` 及 downgrade。
2. Complaint 创建/查询/triage 纵向切片，同事务接通 `COMPLAINT_CREATED` + Audit。
3. NCR/Root Cause/CAPA Action 状态机与服务端硬闸。
4. Effectiveness Review、失败回流、不可变历史与关闭动作。
5. Quality 的 Complaint/CAPA 页面、真实 HTTP/浏览器闭环、跨租户/外部角色/四眼负例及完整门禁。

确认方式：回复“确认采用推荐 CAPA 契约”，或逐条指出上述五项需要修改的值。
