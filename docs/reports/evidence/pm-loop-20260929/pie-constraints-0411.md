# 产品经理PIE专业约束修复

2026-09-30，按[完整设计合同§6.4](../../../design/2026-09-10-pdos-complete-design-contract.md#64-pie职责覆盖与协作)核对N1-05。合规PIE约束此前会被策略发布检查、AI候选校验与页面确认按钮判为缺少IE；专业下拉也没有PIE入口。本候选修复这处实际不一致，没有新增迁移、RBAC角色、定义协审席位或批准权限；共享源head观察为0411，D22功能步骤仍为0409。

## 可用能力与边界

- [策略领域](../../../../server/app/domain/product_strategies.py)与[候选合同](../../../../server/app/contracts/product_planning_ai.py)要求DQE、SQE及IE/PIE制造约束，使用同一制造专业集合。PIE不会代替DQE/SQE；缺关联评审/明确处置以及工作已取消仍阻断就绪。旧IE及大小写编码不重写。
- [实际策略表单](../../../../web/src/components/product-work/strategies.tsx)提供PIE专业选择，修复候选确认按钮的字面IE限制。提示分别记录导入资料/版本、工艺装配风险、工时/产能与制造成本假设，保留未知与待验证工作，不生成实测结果。候选仍不可决定正式处置或最终选择。
- 新[固定v6提示词](../../../../server/app/ai/prompts/product_planning_v6.json)覆盖PIE研究/定义职责、分项约束、来源、未知、具名待验证工作与人工接收/验证/批准边界。[加载器](../../../../server/app/ai/product_work_context.py)对策略和定义默认使用v6，显式历史v5仍读取原提示。原v5文件未修改；动态上下文仍追加到固定前缀之后，没有修改资格或golden。
- [运行恢复用例](../../../../server/tests/test_product_work_runs_api.py)保留v5、补策略/定义两项v6参数。原参数只对v1强制版本，其他标签会随默认版本变化而实际执行新版本；现所有参数都强制并断言实际GatewayInvocation版本，避免把v6结果误记为v5恢复证明。这是测试准备修复，尚未证明实库恢复或计费通过。

## 检查结果

63项后端纯检查通过，含[发布就绪回归](../../../../server/tests/test_product_strategy_manufacturing.py)、[候选合同](../../../../server/tests/test_product_planning_contracts.py)和[提示/上下文检查](../../../../server/tests/test_product_work_assessment.py)，见[原输出](../../../../output/pm-pie-constraints-0411/backend-pure.log)。只证明所列纯判据、历史提示兼容和固定前缀，不证明实际岗位授权或发布事务。子进程移除数据库变量，并以数据库/网络连接拒绝守卫运行。

7项[真实StrategyForm行为检查](../../../../web/src/components/product-work/pie-strategy-constraints.test.tsx)通过，见[输出](../../../../output/pm-pie-constraints-0411/frontend-components.log)：PIE/历史IE候选可确认，人工选择PIE保留原来源、未知与待验证工作；缺DQE/SQE/制造约束或三条路线仍不可确认，候选处置及最终选择保持不可编辑，测试未发出HTTP请求。两组共70项不同检查，没有与0409历史68项或18项地址护栏合并成整链通过数。

七份后端归属文件严格类型、lint和格式通过，见[类型](../../../../output/pm-pie-constraints-0411/owned-types.log)、[lint](../../../../output/pm-pie-constraints-0411/imports.log)、[格式](../../../../output/pm-pie-constraints-0411/format-check.log)；导入依赖保留类型但不报告其诊断。前端当前工作树类型检查及两份归属文件lint通过，见[类型](../../../../output/pm-pie-constraints-0411/frontend-types.log)、[lint](../../../../output/pm-pie-constraints-0411/frontend-lint.log)。

运行恢复16个参数仅收集，包含保留v5和新增两个v6参数；没有执行fixture或测试正文，见[收集输出](../../../../output/pm-pie-constraints-0411/run-recovery-collection.log)。此次收集同样禁止数据库/网络连接；未来执行须先分配独立临时pdos_test、显式核对实际目标与冻结候选，不能使用保留库或将收集计作实库恢复通过。

十份源与历史提示摘要、检查范围见[候选记录](../../../../output/pm-pie-constraints-0411/source-candidate.json)。独立静态边界审阅未发现具体回归，不能替代数据库、真实模型或人工出口。

## 联合验证与剩余条件

[只读协调观测](../../../../output/pm-pie-constraints-0411/coordinator-observation.json)显示协调会话正在自己的57440环境验证供应/排程，未分配PM联验库，也未收到本会话指令。其日志报告0411 metadata无新操作，但保留外键循环警告，未作为本PM冻结候选的完整证明；0411→0409→0411只恢复五个供应/计划守卫，不覆盖0409引用表回退、权限、并发或API。根会话未连接该库。

协调1055份前端快照中的七份D22源与当前源一致，但策略页面已被本次修改，该快照及[此前0409构建/HTTP](master-reference-joint-readiness-0409.md)都不覆盖当前PIE改动。本轮按影响完成纯判据、表单与类型检查，新生产构建和浏览器集中到下一联合候选，不宣称当前完整构建、合法登录或研究到矩阵整链已通过。

下一检查点在分配环境执行D22十四项、0408八项API、0407来源/父版，以及上述新旧提示版本恢复；将当前PIE源纳入构建、合法登录与真实页面办理。策略/定义v6须有当前独立人工参考与服务商原始证明，旧评测不能自动覆盖新前缀。真实研究主题/材料/搜索、有效计量与调用授权、RFQ四类原名称、实际主数据原件、具名专业协审及人工Exit仍待原条件。N1-05及整个产品经理闭环保持部分完成。

本轮无数据库、真实模型、真实搜索、外发、资格授予或生产操作；所有保留环境未由本会话操作。跨会话发送仍等待先前所问的人类明确授权，自动目标续接不是授权。
