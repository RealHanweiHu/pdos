# 第十八波：规则、实际观察与具名复核

**2026-10-08：本施工合同已被[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)整体取代，仅作只读历史对照。下方旧“当前/下一步/冻结”不再作为施工指令。** 范围根、一致性、期限与数量限制按 v1.1 和已批准的 [S0 实施计划](2026-10-08-pdos-next-s0-refactoring-plan.md)执行；[旧条款对照与 B0 基线](../reports/evidence/pdos-next-s0-20261008/baseline/baseline.md)保留取代依据。原证据、失败与当时范围不改写。

续接第十七波已保存的候选及原完成锚。原候选、旧失败 Run、Issue Current 与未知有效性保持。唯一活动状态仍在整合清单；本文件只冻结施工接口，不授真实资格、生产启用或人工 Exit。

本轮复用 next_0026 的 RuleFact/Current、ObservationFact/Current、NamedReview 五表、冻结 body codec、实际共同 Receipt/Audit/Outbox/RequestKey 和 ConsumptionHost。公开操作仅 `quality.capa.observation.record`（T1）与 `quality.capa.verification.review`（T2）；`quality.capa.verification.rule.import` 保持服务器可信发布入口，不加入公开 PAYLOADS，也不允许表单选择 issuer。完整目标 G0～G5 与有效性/分别关闭继续未完成。

严格客户载荷见 `domain/capa_effectiveness/fact_commands.py`。客户选精确 Rule/candidate/Observation full ref、实际 Source 行、发生时间和自己的记录或结论；服务器绑定 Scope/owner/purpose/nature、Current/前版、目标、完整参与者、分类、当前专业/政策/签发者与原子组。禁止客户提供完整 FactBase、参与者名单、qualification、完整观察布尔值、未来 Receipt 或 full SHA。

服务器预览固定 13 键：operation、payload_semantic、stable_anchor、binding、inspection、raw_source_basis、required_source_read_set、sources、authority_snapshot、policy_snapshot、owner_id、visibility、current_issue_revision。未来保存 id/receivedAt 不进入确认材料。execute 恢复原确认的完整锚；每 phase 独立重读所有真实 owner，全部 IO 后重核全部来源/权限/Current/issuer/运行水位与最早 TTL。共同消费实际 False→True 后第一行动捕获时钟，writer 只在同 UOW 委托追加事实及精确 Current CAS，末端失败原子回滚。

独立归属：A 仅新 fact_commands/fact_write 与对应检查；B 仅新 participants_owner/fact_sources_owner 与对应检查；C 仅新 fact-workflow 合同/状态/组件与对应检查。Root 负责真实宿主、公共 registry/consumer/API/BFF/页面接线与统一验证，所有数据库/HTTP/浏览器由 Root 执行。共享老文件不由子任务修改。

原案例只读盘点已在 `existing-source-inventory-v1.json` 保存：两份候选，各 17 条固定读集，五事实表均 0 行，当前专业范围完整来源 union 17。这不是新操作资格或未来材料预留。最终完整闭包不得超过 20、不得截断、替换旧来源或跨请求逃避上限；客户及独立复核者分别以本人真实 Context 读取，不借私有原作者身份。

本轮实际目标是可信 Rule 发布、部分实际观察保存、独立具名 Review 与当前缺项显示的可用接口。完整观察必须符合真实目标、采样、区间和原件记录；时间到或数量够不能自证完整。paired performed/results 及独立专业核验缺失时只阻断依赖动作，缺项明确显示。测试合成材料始终标 synthetic，不宣称真实有效、关闭、G3 全完成或人工出口通过。
