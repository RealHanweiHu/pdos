# S5-2 ERP Handoff 验收报告

日期：2026-08-13
结论：**通过计划允许的人工降级路径验收；ERP API 对接保留为外部依赖，不阻塞切换。**

## 已交付

- migration `0028_erp_handoff_executor`：把既有 durable integration outbox 扩展到 `provider=erp / operation=ebom_handoff`，增加 tenant/project/handoff 复合外键、唯一 intent、delivery mode 与 payload SHA-256。
- 服务器从生效决策时冻结的 EBOM/effectivity 行构造 delivery package v1；客户端不能覆盖租户、项目、handoff 或 payload。
- 人工主链：`ready → queued/manual → export(sent) → reconcile(confirmed)`。
- 失败恢复：`confirmed_not_delivered → failed → REPLAY_CONFIRMED → queued`，复用同一 outbox、payload 与 digest。
- 权限：Project Manager 可 execute，不可 reconcile；Owner/Admin 可 reconcile；所有动作继续经过 tenant + project access。
- 未配置 ERP API 时 `mode=api` 返回 `ERP_API_NOT_CONFIGURED`（503），不会发生外部 HTTP 调用。

## 验证证据

- 服务端全量：362 tests，退出码 0。
- 定向：migration、metadata drift、change API、DingTalk schema 回归、RBAC、single head 共 17 tests passed。
- `ruff check`、`ruff format --check`、严格 `mypy`（206 source files）、Python compileall 均通过。
- 数据库测试仅连接本机 `pdos_test`；未连接开发库、生产 RDS 或 ERP。

## 保留项

- 真实 ERP API 的 endpoint、认证、请求/响应和幂等语义尚未由 ERP Owner 冻结，因此没有启用 API worker。
- 待合同就绪后，在既有 outbox 上增加固定域名/固定协议 adapter、成功/确定失败/不确定结果测试和独立生产授权；不得把自由 HTTP 通道加入 AI runtime。
