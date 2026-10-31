# 两份小Pai设计的实施与验收对照

范围为已确认的日常助手与企业 RAG v0.4、上下文 v0.2。活动进度以[唯一清单](../../../../tasks/ai-native-integrated-todo.md#current-queue)为准；本文件只保留范围、证据和未完成验收。前轮历史见[原对照快照](../pdos-next-cefg-checkpoint-20261029/previous-two-designs-scope-map.md)。

2026-10-29 已完成当前可在模型停用条件下实施的本地功能及适当验证；独立 `127.0.0.1:53502/pdos_test` head 为 `s0_0852`。最终增量见[本地验收](local-acceptance-20261029.md)，各历史候选范围分别保留。真实模型停用继续生效。

| 设计范围 | 已实现与本地验证 | 证据 |
|---|---|---|
| A / X1 日常问答与历史 | 轻量预载、依据状态、窗口预算、历史更新保留/撤权隐藏、运行冻结、技能延续、缓存标记；原六项失败已修复，后续两项长结构合计定向 8/8 通过 | [A/X1](../pdos-next-slice-a-x1-20261028/result.md)、[共同候选与去重](../pdos-next-enterprise-knowledge-authority-20261029/result.md) |
| X2 工作状态与续读 | 版本化约束/焦点/引用、删除纠正、受控句柄分页、必需预算和 context_incomplete；四类候选当前状态来自实际原生命令回执 | [受控续读](../pdos-next-result-continuation-20261029/result.md)、[当前候选](../pdos-next-x2-candidate-state-20261029/result.md) |
| B 企业检索与当前项目 | OR/IDF 与编号、权威过滤、固定引用、隔离提取/资料比较、一跳/同品类/背景条、深入查/纠正；原生项目当前计划/门禁/具名状态自动依据与显式材料独立；本人当前项目讨论过滤与原结果回看已实际验证 | [共同候选](../pdos-next-enterprise-knowledge-authority-20261029/result.md)、[资料比较](../pdos-next-assistant-material-workflow-20261028/result.md)、[当前项目 7 项](../pdos-next-project-current-context-20261029/result.md)、[项目讨论与浏览器](../pdos-next-project-discussion-history-20261029/result.md) |
| B 首期行动故事 | 复验准备→本人请求、回答→资料跟进预填→原生创建/分派；保留原 T1 确认，完整父来源/隐私分类随动作重新核验 | [复验与页面](../pdos-next-verification-action-20261029/result.md)、[跟进任务](../pdos-next-work-followup-20261029/result.md)、[动作 taint](../pdos-next-action-taint-20261029/result.md)、[I14 实际 9 项](../pdos-next-action-footprint-20261029/result.md) |
| X3 上下文清理与可观测 | 运行内有界清理、长运行进度、原账本/回执保留、完整工具披露、两档机制及结构结果；真实长会话质量对比保留待评 | [完整披露](../pdos-next-x3-full-disclosure-20261029/result.md)、[结构结果](../pdos-next-structured-answers-20261029/result.md) |
| C 混合检索 | 独立 profile/连接/预算、后台批次与重启、Run query binding、费用未知占账、RRF、切换/停用与回退；管理页 T1 保存/启用及刷新已验证 | [后台](../pdos-next-embedding-background-20261029/result.md)、[查询](../pdos-next-embedding-query-20261029/result.md)、[设置](../pdos-next-embedding-settings-20261029/result.md)、[原生浏览器](../pdos-next-cefg-checkpoint-20261029/browser-native-ui/steps.md) |
| D 岗位来源与恢复 | 13 类实际来源；具名状态、制造草稿/正式发布分别保留、物理交接固定历史；全派生损坏重建、重复 Outbox、固定批次 Temporal worker 重启恢复 3 项通过 | [原生来源与恢复](../pdos-next-role-native-sources-20261029/result.md)、[现场反馈](../pdos-next-field-feedback-20261029/result.md) |
| E 相似历史与订阅摘要 | 相似历史反馈、短预填/原 T1 归并；确定性摘要设置、临近门禁、无技能/钱包配置、创建/启用/刷新已验证；Change详情与新建Issue/Change标题提示补齐，12项实际及浏览器通过；本人选择摘要同时私发钉钉已实现并通过原生/浏览器验证 | [相似历史](../pdos-next-similar-history-20261029/result.md)、[摘要](../pdos-next-summary-setup-20261029/result.md)、[最终页面](../pdos-next-similar-history-completion-20261029/result.md)、[摘要钉钉](../pdos-next-summary-dingtalk-20261029/result.md) |
| F 知识与缺口 | 本人明确保存目标、原分享恢复、具名知识/Review/Gap；完整实际来源足迹、原件扫描/撤回与受众复核；真实保存和刷新已验证 | [目标与恢复](../pdos-next-personal-knowledge-targets-20261029/result.md)、[完整足迹](../pdos-next-answer-footprint-20261029/result.md)、[原件与 X2 实际 11 项](../pdos-next-x2-candidate-state-20261029/pg-evidence-x2-run1.xml) |
| G 钉钉只读入口 | 绑定、服务身份、只读路由、私发/群受众复核、深链、官方协议适配、发送未知与撤权恢复；17 个唯一实际用例分段通过；另有摘要同时投递原生5项与真实设置整链通过 | [钉钉 17 项](../pdos-next-dingtalk-20261029/result.md) |

[最终检查点](../pdos-next-cefg-checkpoint-20261029/result.md)汇总冻结前端 747 输入的生产构建/浏览器、43 项前端检查、145 项整合纯测及最后搜索增量 26 项纯测/5 项实际回归；不同候选和重叠项分别记录，不相加冒充一次完整全仓验证。0843/0845/0849/0850 的非空历史降级守卫均实际拒绝并回滚，迁移往返与备份另有原始证据。

有限设计对照确认的三个本地余项均已完成：B 本人当前项目讨论过滤与原结果回看、E Change详情/新建标题提示、E/G 本人选择摘要同时投递钉钉。主会话统一迁移、实际数据库/Temporal及浏览器验证；最终757输入生产构建通过。

用户委托制作的v0候选现已交付：40道岗位题＋12道上下文题、24份合成资料，[题集](../../../evaluations/xiaopai-v0/README.md)与[基线](../pdos-next-eval-v0-20261029/result.md)。28道检索已实测，正向macro recall@5/@10均97.92%；完整编号规则v2修复及原重建/权限回归通过。QUA-04缺少一份期望报告，保留原题作为后续比较样本。此前各构建/正式性能仍对应其原候选，未以这次24资料时延替代13类正式测量。

剩余为候选题人工审阅、30–50道真实员工角色题与真人试点，以及按要求暂停的真实模型/embedding答案质量、同题混合收益、上下文两档质量/缓存实测。路由与动作题、上下文题的输入就绪不等于实际模型/业务流程验收通过。

完成审计又识别上下文正文三项本地差异：历史批量ACL、Anthropic临界精确计数与协议留存下的显式缓存控制，已进入[正文合同收口](../pdos-next-context-contract-completion-20261029/task_plan.md)，未完成前不沿用“本地余项全部完成”的广义声明。题集两档原值的完整固定前缀失败已保留，候选改为F48000/64000；仅下界准入不等于完整回放。
