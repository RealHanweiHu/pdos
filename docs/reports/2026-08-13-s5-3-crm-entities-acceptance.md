# S5-3 CRM 需求入口与 26 实体验收报告

日期：2026-08-13
结论：**通过。**

## CRM 入口

- `CRM_REQUIREMENT_RECEIVED` 通过现有已认证 `POST /api/events` 进入；Web 同源公网路由已支持外部 bearer，内部 API 地址不暴露。
- tenant/project 由服务端身份和对象权限绑定；payload 只包含外部业务字段，不能自报 tenant、状态、creator 或 customer UUID。
- 外部 Event、Audit、CRM intake、Requirement draft、Requirement Event/Audit 同事务提交；未知/停用客户整批回滚。
- `(source,event_id)` 重放返回同一 Requirement，不重复建草稿；不同 scope/payload 冲突。
- CRM 只能创建 `draft`。Owner/Admin/PM 在需求池执行独立“成立/拒绝”人审；普通 PATCH 不能绕过硬闸。

## 实体收尾

- migration `0029_crm_entities` 增加 `cehub_supplier.suppliers`、`cehub_cost.costs`、`cehub_project.resources` 与 CRM intake 映射。
- 逐项测试确认规格 26 个业务/AI 实体均有 canonical table；`cehub_event.events` 仍是独立基础设施实体。
- Supplier/Cost/Resource 的 tenant/project/supplier/user 复合外键均以真实跨租户负例验证 fail closed。

## 门禁

- 服务端全量：368 tests passed。
- Web 全量：36 files / 125 tests passed。
- Ruff、format、严格 mypy（207 source files）、ESLint、Next typegen/TypeScript 均通过。
- 所有数据库测试仅连接本机 `pdos_test`；未迁移或写入生产。
