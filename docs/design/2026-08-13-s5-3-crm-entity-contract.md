# S5-3 CRM 需求入口与实体收尾契约

> 状态：已冻结用于实施（2026-08-13）
> 依据：执行计划 S5-3、CEHub v3.2 PostgreSQL Schema Design、API Design 与 SoR Matrix

## 1. CRM intake

新增外部事件 `CRM_REQUIREMENT_RECEIVED`，仍通过已认证的 `POST /api/events` 进入。服务端从认证上下文绑定 tenant，从请求绑定并复核 project；CRM payload 不作为已成立业务事实。

payload v1 固定为：

- `external_requirement_id: string`
- `code: string`
- `title: string`
- `description: string`（允许空字符串）
- `priority: low|medium|high|critical`
- `acceptance_criteria: string[]`
- `customer_code: string`（允许空字符串；非空时必须命中同租户 active Customer）

同一事务写入：外部 Event + Audit、`draft` Requirement、`crm_requirement_intake` 来源映射、Requirement created Event + Audit。任一步失败全部回滚。重复 `(source,event_id)` 返回同一个 Event 与 Requirement；同 id 不同 payload/scope 冲突。

CRM 不能直接建立 Requirement。只有内部 `requirement.edit` 角色可调用：

`POST /api/requirements/{requirement_id}/review-crm-intake`

- `decision=establish`：`draft → proposed`
- `decision=reject`：`draft → rejected`
- 必须携带 `REVIEW_CONFIRMED` 与有界 rationale；每个 intake 只能审一次。
- 同事务更新 intake/requirement，并写 `REQUIREMENT_UPDATED` 与不可变 Audit。

## 2. 26 实体收尾

按规格的 26 个业务/AI 实体，当前只缺 Supplier、Cost、Resource 三张一等实体表：

- `cehub_supplier.suppliers`：租户级轻量供应商名录；只存 code/name/status/reference，不实现采购流程。
- `cehub_cost.costs`：项目级成本事实/估算条目；可选关联同租户 Supplier；不实现总账、应付或结算。
- `cehub_project.resources`：项目级人员/设备/设施分配记录；不实现排产、工时或 MES。

三表必须具备 tenant-safe 复合外键、非空/枚举/数值/日期约束和唯一业务码。S5-3 仅要求实体落库与 schema 合同，业务 UI/API 在出现真实用例后增量开放。

## 3. 安全与验收

1. CRM payload 只能创建 draft，不能自报 tenant、created_by、status 或 customer_id。
2. customer_code 跨租户/停用/未知全部 fail closed，外部 Event 也不落库。
3. event 重放不重复创建 Requirement；冲突重放为 409。
4. PM 可人工 review；Engineer/Quality/Supplier/Customer 不可 review。
5. schema 中 Supplier/Cost/Resource 存在且 tenant/project/supplier 边界由数据库拒绝跨租户引用。
6. migration `0029_crm_entities` 单 head、metadata 零漂移；测试只连 `pdos_test`。
