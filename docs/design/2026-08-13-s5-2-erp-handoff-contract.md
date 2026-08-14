# S5-2 ERP Handoff 执行契约

> 状态：已冻结用于实施（2026-08-13）
> 依据：`2026-08-09-preview-execution-plan.md` S5-2、CEHub v3.2 SoR Matrix、Workflow 与 System Architecture
> 外部前提：当前没有经确认的 ERP API 合同，因此 `manual` 是默认交付模式，API 执行器只冻结端口并以测试替身验收。

## 1. 目标与边界

PVT Gate 批准后，把生效决策时已冻结的 EBOM 与 effectivity 快照组成不可变交付包，通过 durable outbox 进入 ERP 交接流程，并支持幂等、人工导出、重放和对账。

PDOS 是 Requirement、Project、Gate、Development BOM 与 Change 的事实源；ERP 继续是 Material Master、MBOM、Routing、Inventory 与 Production Version 的事实源。PDOS 不回写或镜像这些 ERP 业务对象，也不在未冻结 ERP API 合同时发起自由 HTTP 请求。

## 2. 状态与不变量

### ERP Handoff

`pending → ready → queued → sent → confirmed`

- `pending → ready`：沿用 S3-4 硬闸，只有同项目 PVT Gate 已批准才可执行。
- `ready → queued`：创建唯一 outbox intent；同时冻结 canonical JSON payload 与 SHA-256 digest。
- `queued → sent`：人工模式由显式 `export` 动作完成；API 模式由受限执行器成功返回完成。
- `sent → confirmed`：必须由有 `handoff.reconcile` 权限的人提供 ERP 外部引用并显式确认。
- `queued/sent → failed`：确定失败或人工对账确认未交付；只有 `failed` 可显式重放。
- 不允许跳过 `ready`、不允许改变冻结 payload、不允许自动把 `sent` 当作 `confirmed`。

### Outbox

- provider 固定为 `erp`，operation 固定为 `ebom_handoff`。
- 唯一键为 `(tenant_id, provider, operation, idempotency_key)`；同键不同项目、handoff 或 payload fail closed。
- `manual`：等待人工导出/对账；`pending/retry_wait/sending`：仅供后续 API 执行器；`succeeded` 表示传输完成而非 ERP 业务对账完成；`uncertain` 必须人工对账，禁止盲重试。
- 租户、项目和 handoff 关系由服务端上下文绑定，客户端不能自报范围。

## 3. 交付包 v1

交付包由服务器从 `erp_handoffs` 冻结行生成，字段为：

- `schema_version=1`
- `handoff_id / tenant_id / project_id / ecn_id`
- `source_system / target_system`
- `source_bom`：冻结的 EBOM header 与 items
- `effectivity`：冻结的生效快照

使用键排序、无多余空白的 UTF-8 JSON 计算 SHA-256。用户不能覆盖 payload；重放复用原 payload 与 digest。

## 4. HTTP 合同

- `POST .../handoffs/{id}/queue`：`{idempotency_key, mode}`，创建或幂等返回 intent。
- `POST .../handoffs/{id}/export`：人工模式显式导出并返回交付包；需要 `EXPORT_CONFIRMED`。
- `GET .../handoffs/{id}/delivery`：读取 handoff、outbox 元数据和冻结交付包。
- `POST .../handoffs/{id}/reconcile`：确认已交付/未交付；已交付必须提供外部引用与 `RECONCILE_CONFIRMED`。
- `POST .../handoffs/{id}/replay`：仅失败项，需 `REPLAY_CONFIRMED`，复用原 intent 和 digest。

`handoff.execute` 赋予 Owner/Admin/Project Manager；`handoff.reconcile` 仅 Owner/Admin。所有接口继续执行 tenant + project 成员边界。

## 5. 失败策略

- 人工模式不依赖网络，不因 ERP API 未就绪阻塞 Sprint 5 切换。
- API 执行器仅在显式配置启用时领取 `erp` intent；超时或 lease 丢失进入 `uncertain`，不自动重复可能已成功的外部写。
- 可确定的瞬时错误进入有限退避；达到上限进入 `failed`；重放必须由人显式触发。
- 每次 queue/export/reconcile/replay 均同事务写业务状态、事件与审计；事件和审计中不保存凭据。

## 6. 验收

1. PVT 未批准仍不能 ready；非 ready 不能 queue。
2. 同一幂等键重复请求返回同一 outbox；不同 payload/scope 冲突。
3. 默认 `manual` 路径完整走通：queue → export → confirmed，交付包 digest 可复算一致。
4. `confirmed_not_delivered → failed → replay` 可走通，payload/digest 不变。
5. PM 可执行但不能对账；跨租户/非成员不可见不可写。
6. API 执行器用测试替身验证成功、确定失败与不确定结果；未配置时零外部调用。
7. migration `0028_erp_handoff_executor` 单 head、metadata 零漂移；测试只连接 `pdos_test`。
