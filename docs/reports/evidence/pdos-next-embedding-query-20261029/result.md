# Run 查询向量检查点 · 2026-10-29

查询向量已接入实际小Pai `assistant.search`、原生调用账本与 Run 费用预算。最终候选 **276 项纯测、9 项唯一实际 PG/Temporal 检查通过**；实际检查分段执行，未把重复运行累计。默认端口仍为 `None`、默认关键词，真实提供器未调用。

## 可用能力与证明

- QueryBinding 从实际已完成模型回复所产生的主图 READ 派生，冻结原父调用、输入、profile、查询 digest、取消 epoch。内部身份不注册为模型工具，不复用聊天 ModelBinding/凭据，不被 `result.read` 打开。
- 一次主检索与同品类补查复用同一查询向量；原固定来源、版本、焦点、排除、客户私有选择与范围过滤保持。查询出站由真实 Run 来源并集按 P26 判定，后台选材字段不另充当查询权限。
- 查询费用记入原 Run 钱包，后台费用仍记入独立租户索引预算。恢复从实际完成账本复用固定向量，不解析凭据、不再次调用。未知/越界计量保守记账，崩溃后的 started 调用不盲重发。
- [276 项纯测](pure-query-run1.xml)，56.31 秒；7 项实际场景在该无 DB 环境中明确跳过，不计入纯测。覆盖真实安装源码的查询机制、原 READ/绑定/Host、上下文排除与费用算术。
- [实际 PG 首轮](pg-query-run1.xml)中 **6 项通过**：完成调用的实际原账本恢复、5 个伪造证明/内部身份负例与真实钱包事务回滚。该轮 Temporal 在前置合成查询与正文标记的 `ONLY` 分词重叠处失败；仅改合成查询后，[实际 HTTP→Temporal→注册主/隔离图整链通过](pg-query-temporal-run2.xml)，17.33 秒，验证无关键词命中时经语义召回、原固定来源核对、账本扣费一次、页面原文读取不发 embedding，原始向量/凭据不进入模型消息或 Temporal 历史。
- [运行中取消/撤权最终 2/2](pg-query-boundaries-final-run3.xml)，12.00 秒；取消保留调用前实际预占，撤权后的已知用量照实结算，均不返回/保存向量，重复释放不重复扣费。测试字段名及释放后 hold 清零断言的两次夹具错误保留原始输出；未改产品账本语义。
- 原始日志分别在[首轮](../pdos-next-assistant-combined-20261029/pg-embedding-query-run1.txt)、[Temporal](../pdos-next-assistant-combined-20261029/pg-embedding-query-temporal-run2.txt)、[取消/撤权](../pdos-next-assistant-combined-20261029/pg-embedding-query-boundaries-final-run3.txt)。

## 迁移与候选

独立 `127.0.0.1:53502/pdos_test`，标记 `f117bb5b-b3d7-4286-aaec-c54d9255e96b`，本检查点 head **s0_0838**。[备份及升级/降级/升级](migration-0838.json)成功，备份 98,357,766 字节，9 张历史表计数保持；[有真实合成查询历史时降级拒绝](migration-nonempty-downgrade-refused.json)，Run、调用、费用与触发器完整保留。原 `agent_tool_calls` FORCE RLS 和普通 owner 不变。

[12 项改动输入](final-source-sha256.json)、[2718 项候选输入](candidate-query-inputs.json)、[精确合入与根差量](application-manifest.json)、[SQL 静态闭合](sql-audit.json)、[Ruff](ruff-query-final.txt)、[diff](diff-check-final.txt)。本层未增加 HTTP 路由/业务命令/模型工具，沿用后台层已导出的 128 payload 合同；前端输入未变。

## 继续范围

独立管理员设置页、知识沉淀与主动摘要/通道仍在集成。没有实际 ANN planner/规模召回或真实质量提升结论，没有更改默认混合策略。旧 `ai.model_call.reconcile` 的 reservation 对账不等于本层 AgentToolCall 费用对账，本层未虚称复用该操作。完整两份设计与正式阶段验收仍未完成。
