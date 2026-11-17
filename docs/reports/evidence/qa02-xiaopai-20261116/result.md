# QA-02 小 Pai 真实执行复验

2026-11-16（America/Los_Angeles）。预览运行于 `pdos-next/design-v1.1` 的 `f7425553` 加 QA-01 前端修复。复用带隔离标记的 `pdos_test`（`s0_0888`），仅在合成租户登记小 Pai 执行身份，写权限限于「轮胎充气泵（合成走查）」品类。该租户启用了提案起草技能、MiniMax-M3 和有限测试预算。小 Pai 主图经隔离 Temporal 命名空间执行；本次采用 T1，由 `walk-admin` 在页面确认。

[打开预览](http://127.0.0.1:57859/login) · [提案草稿](http://127.0.0.1:57859/categories/e6152e7b-c4d7-4795-ba86-151d8569cfa5/proposals/150cb62f-2acc-4bb7-b401-f8e76273711e) · [小 Pai 运行](http://127.0.0.1:57859/dingtalk/runs/684b366c-dc9c-417e-9a62-272a42fb990f?category=e6152e7b-c4d7-4795-ba86-151d8569cfa5)

| 模块 | 场景 | 角色 | 结果 | 执行依据 |
|---|---|---|---|---|
| 执行身份和工作流 | 从「立项提案 → 新建提案 → 与小Pai一起起草」发出合成任务 | 测试负责人、小 Pai | 通过 | 浏览器返回 202。Temporal `XiaopaiGraphWork` 已完成，历史含 `xiaopai.model`、`xiaopai.tools` 活动。运行绑定当前会话、合成品类、请求人与执行身份。[浏览器入口](01-browser-start.png) · [账本和工作流](db-and-workflow-readback.json) |
| 模型和工具 | 读取当前品类，起草提案简述 | 小 Pai | 通过 | MiniMax-M3 三次真实调用均有供应商请求、用量和计费记录。`category.read` 返回当前品类；`proposal.create` 生成一个 T1 待确认候选。简述覆盖应急补气、连续三次补气、温升、原型与暂缓两种选择，并注明暂无实测。确认前同名提案为零。[待确认候选](02-candidate-before-confirm.png) |
| 人工确认和持久化 | 查看并核对候选，点击「保存提案 → 确认保存」，刷新详情及重开运行页 | 测试负责人 | 通过 | 预览和保存均返回 200。最终仅有一条 v1 私有草稿，简述与候选一致，候选刷新后显示「已保存」。数据库只读对账确认同一次运行关联一个创建回执，人工确认已消费，提案归请求人。[确认](03-confirmation.png) · [详情刷新](04-saved-proposal-refresh.png) · [运行刷新](05-saved-candidate.png) · [接口结果](browser-result.json) |
| 结构化草稿 | 让模型生成提案条目数组并通过同一工具提交 | 小 Pai | 失败 | 同一运行的九次 `proposal.create` 参数均被结构校验拒绝。取消后候选、业务记录均为零。[参数校验](attempt2-tool-shape.json) · [取消结果](attempt2-outcome.json) |
| 运行异常处理 | 模型结果待核实后，由管理员结束等待 | 测试管理员 | 通过 | 第一次运行第三个模型调用进入 `EXTERNAL_OUTCOME_UNKNOWN`，管理员在原运行执行对账，终态为失败，业务回执零条。供应商侧是否完成仍待核实。[对账截图](attempt1-reconciliation.png) · [前后状态](attempt1-reconciliation.json) |

保存回执为 `1dca5481-324b-4475-b2ea-711f3fd1da80`。本轮只使用真实调用和合成输入，复验范围为新提案的品类上下文与简述保存。已有项目和已有提案上下文的真实调用未测试。

## 待修问题

**中等 · 结构化提案起草无法生成候选。** 从新建提案进入小 Pai，要求带「为什么值得做」等分条内容起草，预期 `proposal.create` 生成含结构化条目的待确认候选。实测工具参数中的 `groups` 或 `groups[].items` 出现字符串或对象，未通过现有结构校验。参数形状与拒绝结果已确认，模型如何生成这些形状仍待定位。影响本次 MiniMax-M3 路径下的结构化草稿；简述路径已验证。 [发起截图](attempt2-start.png) · [参数与校验](attempt2-tool-shape.json)
