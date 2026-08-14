# S4-1 Quality / CAPA API 与错误合同 v1

> 状态：已冻结；从属 `2026-08-12-s4-1-quality-owner-contract-draft.md`，不得放宽质量 Owner 已确认的四眼、证据、角色或项目边界。

## HTTP 面

所有路径均为 `/api/projects/{project_id}/quality`，tenant、actor、Project 范围只取服务端认证上下文。

| Method / path | 用途 | 权限 |
|---|---|---|
| `GET /complaints`、`GET /complaints/{id}` | Complaint 列表/详情 | 内部 Project 成员 |
| `POST /complaints` | 创建 Complaint | Owner/Admin/PM/Engineer/Quality |
| `POST /complaints/{id}/triage` | 原子创建首个 NCR 并进入 triaged | Owner/Admin/Quality |
| `POST /complaints/{id}/transitions` | investigating/resolved/closed | Owner/Admin/Quality；closed 仅 Quality |
| `GET /complaints/{id}/ncrs` | 关联 NCR | 内部 Project 成员 |
| `GET /ncrs/{id}`、`GET /ncrs/{id}/detail` | NCR 与完整 CAPA 历史 | 内部 Project 成员 |
| `POST /ncrs/{id}/transitions` | 推进 NCR 状态与硬闸 | Owner/Admin/Quality；closed 仅 Quality |
| `POST /ncrs/{id}/root-causes` | 新建不可变根因版本 | 被指派的内部 Project 成员 |
| `POST /ncrs/{id}/root-causes/{rca_id}/approve` | 批准根因 | 仅 Quality，且不得为 analyst |
| `POST /ncrs/{id}/actions` | 新建纠正/预防措施 | 内部 Project 成员；普通成员仅可指派自己 |
| `POST /ncrs/{id}/actions/{action_id}/transitions` | 启动/完成措施 | 仅被指派 Owner |
| `POST /ncrs/{id}/preventive-not-applicable` | 批准预防措施不适用 | 仅 Quality |
| `POST /ncrs/{id}/effectiveness-reviews` | 追加不可变有效性复核 | 仅 Quality，且不得拥有任一待验措施 |

Supplier / Customer 对上述全部路径稳定返回 403；v1 不提供脱敏投影。编号由服务端生成。写路径均在业务事务内写版本化 Event 与 immutable Audit。

## 证据引用

证据对象严格为以下二选一，不接受额外字段：

```json
{"kind":"document","reference":"<same-project document UUID>"}
{"kind":"event","reference":"<same-project immutable event_id>"}
```

Action completed 与 Effectiveness Review 至少一条证据；Root Cause 可为空。跨 tenant/Project、未知类型、未知引用统一 fail-close。Complaint 附件只接受同 Project Document UUID。

## 冻结错误码

| HTTP | code | 语义 |
|---:|---|---|
| 403 | `PROJECT_ACCESS_DENIED` | 非成员、外部角色或角色动作未授权 |
| 403 | `CAPA_QUALITY_ROLE_REQUIRED` | 最终复核/关闭动作不是 Quality |
| 403 | `CAPA_ACTION_OWNER_REQUIRED` | 非措施 Owner 尝试执行 |
| 403 | `CAPA_ASSIGNMENT_DENIED` | 普通成员向他人指派措施 |
| 404 | `COMPLAINT_NOT_FOUND` / `NCR_NOT_FOUND` / `ROOT_CAUSE_NOT_FOUND` / `CAPA_ACTION_NOT_FOUND` | tenant+Project 绑定对象不可见 |
| 404 | `QUALITY_RELATED_OBJECT_NOT_FOUND` | Customer/User/Document 等关联越界 |
| 404 | `QUALITY_EVIDENCE_NOT_FOUND` | 证据未知或跨范围 |
| 409 | `QUALITY_INVALID_TRANSITION` | 状态边不在冻结图中 |
| 409 | `NCR_CONTAINMENT_NOT_READY` | 遏制措施未完成 |
| 409 | `NCR_ROOT_CAUSE_NOT_APPROVED` | 无已批准根因版本 |
| 409 | `ROOT_CAUSE_FOUR_EYES_REQUIRED` | analyst 自审 |
| 409 | `ROOT_CAUSE_IMMUTABLE` | 修改已批准/替代版本 |
| 409 | `CAPA_ACTION_GATE_NOT_READY` | corrective/preventive/完成证据不齐 |
| 409 | `CAPA_ACTION_INVALID_TRANSITION` | 措施状态边或完成载荷非法 |
| 409 | `CAPA_OBSERVATION_PLAN_INVALID` | 判定标准/观察截止日未冻结或截止日不晚于最终措施完成 |
| 409 | `EFFECTIVENESS_OBSERVATION_PENDING` | 观察期未结束 |
| 409 | `EFFECTIVENESS_FOUR_EYES_REQUIRED` | Reviewer 是任一措施 Owner |
| 409 | `CAPA_NEW_ACTION_REQUIRED` | ineffective 后未新增跟进措施 |
| 409 | `CAPA_EFFECTIVENESS_NOT_PROVEN` | 最新复核不是 effective |
| 409 | `COMPLAINT_NCR_GATE_NOT_READY` | Complaint 关联 NCR 尚未全部关闭 |
| 409 | `COMPLAINT_RESOLUTION_INVALID` | resolved/closed 结论载荷不合规 |

请求 schema 枚举、长度、必填、日期/时区错误由 FastAPI/Pydantic 返回 422；未知字段一律拒绝。
