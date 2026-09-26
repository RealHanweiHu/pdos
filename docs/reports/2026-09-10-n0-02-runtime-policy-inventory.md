# N0-02 运行与授权合同初始盘点

日期2026-09-10。前置N0-01已由用户明确批准，以[共同合同1.0.0](../contracts/pdos-v1/freeze-record.md)生效。N0-02开始，仍为部分完成；本轮是按实际代码准备政策差异，未实施运行权限、模型预算或数据库变更，未冻结DC-06/07/08。

## 现有实现与必须收口的差异

[静态清单](../contracts/pdos-v1/n0-02-initial-runtime-inventory.json)从当前capability/tool/Role定义导出，并绑定13份源文件摘要。当前6个AgentKey席位、10种唯一工具声明；设计新增PM职责是目标，不能算作已有第7席位接线。只有声明和静态事实，不表示运行可用或生产已配置。

| 项 | 当前代码事实 | N0-02政策收口 / 实际接线归属 |
|---|---|---|
| 能力注册 | 13个key，11 hard_gate / 2 confirm；11 live / 2 shadow。`CapabilityContract`含prompt、finding_types、projection、tools和quality_control | 补scope、入口、明确读/模型候选/确定性业务/人工应用分类，预算/保留/过期和policy版本；不得把live登记当模型已通过本能力资格 |
| 风险建议API | 注册为confirm，quality_control为human_accept_per_call；实际RiskSuggestionService已创建Finding并有preflight/事件/audit | 修正登记语义，与已批准双动作一致；不要误改成模型写Risk或把真实Finding路径降为单动作 |
| 报告导入 | 同列confirm；实际服务模型仅提议未知表头映射，原值由确定性解析读取；已有确认映射复用可零模型；人工确认是专用导入流程 | 模型映射建议和原值导入分合同；`reports.preview_import`只读已有批次，不能让模型工具隐式新建导入草稿。旧专用人工导入不机械改为两次Finding |
| 工具声明 | ToolDefinition只有name/description/input_example；共用reach与领域证据工具已声明 | 补真实input/output schema、handler、side effect、超时/权限/观察/失败合同；有输入例子不等于有模型可调用的完整工具规范 |
| 执行环 | Executor图固定project context→events→memory→domain evidence→invoke_model结束；AgentReadTools有受限查询实现 | N0-03接真实模型tool request→handler→追加Observation→有界继续。reach服务存在不等于此图会实际调用；不能把声明数量当接线完成 |
| 范围授权 | ProjectAccess按当前租户用户Role、成员及代理membership判断；代理借成员范围后仅检查代理人的Role | 按已批准DC-03细化双方有效权限交集、NULL项目角色兼容、非项目typed scope与转换；persona仅职责，不能产生权限 |
| 预算 | Gateway调用前读取当日累计token判断exhausted，之后记录模型token；有结构尝试1–3上限 | 原子预留tenant+lineage+attempt、全部重试/席位/恢复累计；读一次累计后调用不能证明并发不会超预算，N0-03实现账本与对账 |
| 金额 | Application Gateway为每个provider传ProviderRateCard(0,0)，Gateway缺省也落0价；记录normalized_cost_microusd | DC-07价目未知为null/unknown，具名版本费率；token保护独立有效，超时未知预留不得释放。不能称现有0价为真实免费或金额硬闸 |
| reach | default-allow+blocklist，GET、无凭据、每跳解析IP、原文untrusted_external；2MiB/3 redirects | 继承已批准D25，无首次访问审批；handler接线、当前ACL、快照复用/保留/可见失能在N0-03/N1-02联合验证 |
| 新profile/保留 | 完整设计§18/20已有具体候选值，尚未DC-06/08冻结 | 逐能力选择profile/覆盖、lease/并发/期限/未知费率状态；purge初始关闭，正式引用保护/撤权重新验证；不能读取实际密钥来填配置模板 |

这里指出的是具体读取路径的差异，未声称已审计所有API的漏洞或做过生产攻击验证。工具/模型/来源权限和业务Finding路径应独立验证，不能统一按zone一个标签决定写入资格。

## 原27项能力的接线起点

下表是语义复用建议，不是完整度声明；“尚无对应key”仅针对当前13项注册。既有服务可能提供部分素材，仍要逐字段/入口/评测核实。N0-03公共基础不等待全部新领域完成。

| 原能力 | 现有登记或可复用素材 | 领域归属 |
|---|---|---|
| requirement_readiness | risk_suggestion/blocker_alert只提供部分缺项语义，需专用合同 | N1-07/N2-03 |
| schedule_control | risk_suggestion/blocker_alert，无正式日期引擎 | N2-03/06 |
| execution_followup | blocker_alert与确定性提醒素材 | N2-07/N3-02 |
| gate_readiness | gate_readiness_anomaly；保留真实Gate规则 | N0-04/N4-07 |
| meeting_minutes | knowledge_draft仅知识出口，不覆盖纪要流程 | N3-06 |
| document_extract | test_report_import只覆盖部分报告；其他文档需独立输入/出口 | N1-02/N3-08/10/N4-01 |
| project_memory | knowledge_draft及search_memory | N3-03/N6-05 |
| spec_bom | engineering_intelligence.bom_impact_suggestion | N4-03 |
| material_substitution | 无专用key，可复用BOM证据素材 | N4-03/N5-05/06 |
| change_impact | engineering_intelligence.change_impact_suggestion | N4-04/06 |
| test_quality | quality_cluster_alert、test_plan_change与质量证据素材 | N4-01/02 |
| issue_verification | 无专用key，质量证据不代独立Verifier | N0-04/N4-05 |
| capa_recurrence | quality_intelligence.capa_suggestion | N4-05/N6-05 |
| material_readiness | 无专用key，供应延迟摘要不等于齐套计算 | N5-02/03 |
| supplier_delay | supplier_intelligence.supplier_delay_risk | N5-03/05 |
| sourcing_risk | 无专用key | N5-04/05 |
| portfolio_schedule | executive_portfolio_brief仅简报素材，无组合排程引擎 | N6-02/03 |
| resource_conflict | 无专用key，组合简报不证明容量冲突求解 | N6-01/02 |
| decision_brief | executive_portfolio_brief部分复用 | N3-07/N6-03 |
| research_planning | 尚无PM专用key，reach只提供采集基础 | N1-02 |
| competitor_analysis | 尚无专用key | N1-03 |
| market_analysis | 尚无专用key | N1-04 |
| opportunity_mapping | 尚无专用key | N1-04 |
| experiment_design | 尚无专用key | N1-04 |
| product_strategy | 尚无专用key | N1-05 |
| product_definition | 尚无专用key | N1-06/07 |
| product_matrix | 尚无专用key | N6-04 |

## 下一片交付与验证

按活动清单继续N0-02：把上述13项现存能力和27项目标语义填成范围/触发/上下文/工具/出口/zone及rollout/幂等/过期/预算/保留矩阵；四类合同Capability/Tool/Engine/HumanAction分别具有可验证字段；整理DC-06/07/08的具体推荐与兼容边界后集中裁决。不重新询问已冻结DC-01～05/09，也不等待真实生产身份或全部领域资料才继续。

本次盘点未运行模型、数据库、网络或业务变更测试。N0-01生效元数据更新后已验证：获批manifest SHA-256匹配，88组件正文、15操作与97表盘点与批准快照相同，根产物仅版本/状态/批准说明增量；导出`--check`通过。此前120项纯合同与兼容回归证据仍有效，不能转述为N0-02运行接线验收。
