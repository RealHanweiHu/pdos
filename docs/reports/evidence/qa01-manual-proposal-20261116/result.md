# QA-01 手工提案送审复验

2026-11-16（America/Los_Angeles）。预览使用 `pdos-next/design-v1.1` 的 `f7425553` 加本次前端改动，复用了带标记的隔离 `pdos_test`（`s0_0888`）。合成提案从 Chrome 界面新建，负责人使用 `walk-admin`，独立具名评审人使用 `walk-engineer`。

## 修复

提案「提案」页签在可编辑且缺少「为什么值得做」章节时展示输入框和「保存立项理由」。沿用 `proposal.item.patch` 保存版本化的 `worth_it` 条目、保留原请求核对机制。已有章节沿用「编辑此条」和版本检查。G0 的后端校验、提交与具名决定使用原有路径。

## 浏览器与持久化

| 操作 | 实际结果 |
|---|---|
| 手工新建后尝试空白理由送审 | 仅空白不能保存。G0 预览仍返回 `409 VALIDATION_FAILED / narrative_missing`，提案留在草稿。[截图](01-missing-rejected.png) |
| 填写并保存，刷新详情 | 保存返回 `200` 和回执。刷新读到一条人工立项理由 v1。[填写](02-fill-rationale.png) · [刷新](03-saved-after-refresh.png) |
| 送审及退回 | 负责人提交，独立评审人读取固定副本后具名退回。刷新显示「已退回」和退回理由。[截图](04-returned.png) |
| 修订理由并重提 | 同一条目的 v2 刷新可读。新评审副本固化了 v2，首次评审副本仍保留 v1。 |
| 批准并进入项目，刷新提案与项目 | 提案保留「已批准」及具名回执。项目驾驶舱刷新后仍可打开，型号和封存的立项定义 v1 与批准记录一致。[立项结果](05-approved-handoff.png) · [项目刷新](06-project-after-refresh.png) |

[浏览器命令及回执](browser-result.json) · [数据库只读对账](db-readback.json)

提案详情、提案创建、规格编辑相关测试 27 项通过。TypeScript 检查及变更文件 ESLint 通过。浏览器业务写入均通过产品页面操作。
