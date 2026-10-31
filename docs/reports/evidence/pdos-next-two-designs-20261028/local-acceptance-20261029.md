# 小Pai与上下文改进：模型停用条件下的本地验收

当前授权内的实现、既有失败修复及适当本地验证已完成。范围为已确认的日常助手/企业RAG v0.4与上下文v0.2，逐项范围见[设计对照](task_plan.md)。独立测试库为`127.0.0.1:53502/pdos_test`，当前head `s0_0852`。

| 范围 | 验证结果 |
|---|---|
| 原六项既有失败与两项长结构回归 | 定向 **8/8通过**，[共同候选与去重记录](../pdos-next-enterprise-knowledge-authority-20261029/result.md)、[A/X1实现](../pdos-next-slice-a-x1-20261028/result.md)。 |
| A–G / X1–X3 已列能力 | 日常问答/历史与上下文预算、工作状态/续读、企业检索/比较/纠正、项目依据/受控动作、独立embedding设置、岗位来源、摘要/知识/钉钉入口均有分段证据；[此前功能和页面检查点](../pdos-next-cefg-checkpoint-20261029/result.md)保持各自候选范围。 |
| 13类正式检索性能 | 71来源、5次预热＋40次测量，search/verify13/verify59 inclusive p95 **0.966/0.515/0.675秒**，SQL **5/4/4**；[最终报告](../pdos-next-search-performance-20261029/result.md)，保留原超时。 |
| Change与标题相似历史 | 原Issue8＋新Change/标题4同轮 **12/12通过**；三入口p95 **0.558/0.450/0.419秒**。真实卡片、版本反馈、小Pai预填、两种标题防重复及320/390暗色验证通过。[报告](../pdos-next-similar-history-completion-20261029/result.md)。 |
| 本人当前项目讨论 | 实际PG覆盖本人/peer与同品类两项目、搜索/分页/游标、撤权；真实项目页打开原Run、筛选本人当前项目会话通过，24表保护快照保持。[报告](../pdos-next-project-discussion-history-20261029/result.md)。 |
| 摘要同时私发本人钉钉 | 原生交付5＋实际生命周期1同轮 **6/6通过**；真实draft→preview→一次T1→刷新、原Run四问结构及仅查询原回执通过。Mock发送恰1次，实际渠道调用0。[报告](../pdos-next-summary-dingtalk-20261029/result.md)。 |
| 最终前端与迁移 | [757输入生产构建](../pdos-next-summary-dingtalk-20261029/frontend-final-candidate1-build-result.json)含TypeScript通过；末段35项前端、10文件ESLint及18文件Ruff通过。[0851](../pdos-next-similar-history-completion-20261029/migration-0851.json)/[0852](../pdos-next-summary-dingtalk-20261029/migration-0852.json)备份与升降升、两次非空历史降级拒绝均通过。 |

最终增量在Sol xhigh并行准备，主会话统一合入和实际验证。145项整合纯测＋搜索增量26、后续B/E/摘要的纯检查分别记录；重叠项不累计，也不将不同候选声明为一次全仓回归。各原失败、修复、源码输入hash与原始XML/日志见对应报告。

剩余是v0候选题人工审阅与30–50道真实角色题、真人评审/试点，以及恢复真实模型/embedding后的同题质量、混合收益、长会话及缓存实测。按用户要求真实调用继续关闭，因此两份设计的完整质量验收仍保留。未修改golden-case，未提交推送或操作生产。临时API、Web、浏览器与本次登录文件已清理，独立测试库和Temporal保留。

题集后续增量：[52道候选题与实际关键词基线](../pdos-next-eval-v0-20261029/result.md)已交付，完整编号规则v2的定向检查与原重建/权限回归通过。上表各旧检查点保持自己的版本范围；人工审阅与真实模型质量仍待执行。
