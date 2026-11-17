# QA-02 小 Pai 结构化提案复验

2026-11-16（America/Los_Angeles）。预览运行于 `pdos-next/design-v1.1` 的 `f7425553`，叠加 QA-01 前端修复及本次参数解析修复。使用已核对标记的隔离库 `pdos_test`（`s0_0888`）、合成品类「轮胎充气泵（合成走查）」和测试负责人 `walk-admin`。

## 修复与回归

MiniMax-M3 在历史真实调用中把提案条目数组返回为 `{"item": 单条对象}` 或 `{"item": 多条数组}`，使参数停在 `ProposalCreate` 的数组类型校验。现在只在 MiniMax-M3 的 `proposal.create` 协议适配中读取明确的数组外层和 JSON 容器。原始服务商消息完整保留用于续接。原 `ProposalCreate`、条目、引用和 G0 校验继续生效。 [MiniMax 协议说明](https://platform.minimax.cn/docs/api-reference/text-openai-api)

历史真实调用中 8 份不同参数原先全部校验失败。重放修复后 5 份通过，另外 3 份仍因无效条目 UUID 或空 `groups` 被拒。隔离预览对应候选的协议测试 85 项通过，提案规格与 G0 证据相关单元测试 135 项通过。当前工作树的协议测试 89 项通过，Ruff 检查通过。 [历史参数重放](prior-tool-call-replay.json)

## 真实浏览器闭环

| 步骤 | 实际结果 |
|---|---|
| 在 Chrome 从「新建提案 → 与小 Pai 一起起草」发起合成任务 | 浏览器返回 202。MiniMax-M3 三次调用均有供应商请求、实际用量和计费记录。`category.read` 读取当前品类，`proposal.create` 成功准备候选，Temporal `XiaopaiGraphWork` 已完成。此趟真实调用原生返回数组，兼容包装的回归由上面的历史调用重放及协议测试覆盖。 [入口](01-browser-start.png) · [账本和工作流](db-and-workflow-readback.json) |
| 核对候选并人工确认 | 候选有一个独立的 `section/worth_it` 条目，正文包含夜间应急场景、计划验证连续三次补气和外壳温升，并标注暂无实测。浏览器打开编辑区核对原文。保存预览和确认均返回 200，确认前同名提案为零。 [候选](02-candidate-before-confirm.png) · [编辑区](03-structured-editor.png) · [确认](04-confirmation.png) |
| 刷新提案和原运行页 | 只读对账确认一条 v1 私有草稿、一个 v1「为什么值得做」结构化条目和一个保存回执。条目标记 AI 起草，绑定小 Pai 写入身份与人工确认账户。条目、提案、已采用候选和回执关联同一运行。 [提案刷新](05-saved-proposal-refresh.png) · [运行刷新](06-saved-candidate.png) · [接口回读](browser-result.json) |

保存回执为 `4050a4dc-4189-4c8b-b87b-b8855ed6c4d4`。 [打开提案](http://127.0.0.1:57859/categories/e6152e7b-c4d7-4795-ba86-151d8569cfa5/proposals/c1c790f5-795f-486a-bdfd-9d36ae23f6a6) · [打开运行](http://127.0.0.1:57859/dingtalk/runs/dbbe2785-ef25-4323-a0c8-a49767565d99?category=e6152e7b-c4d7-4795-ba86-151d8569cfa5)

前两趟复验均无业务写入。第一趟第三次模型请求进入「结果待核实」，在原运行完成对账。第二趟模型把品类 ID 填为知识引用，保存预览以 `409 SOURCE_UNAVAILABLE` 拦截。通过场景明确限定使用合成输入且省略系统来源引用，端到端覆盖一个结构化章节和人工保存。 [第一趟对账](attempt1-reconciliation.json) · [第二趟拒绝](attempt2-save-preview.json)
