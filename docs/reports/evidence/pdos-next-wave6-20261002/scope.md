# 第六波施工合同 · 成本输入与确定性估算

续接第五波固定候选。唯一活动状态在[清单](../../../../tasks/ai-native-integrated-todo.md#pdos-next-queue)，不另建进度清单。本闭环：固定Build需求/制造工序 → 逐条有出处的成本输入 → 整版T1确认及不可变续版 → canonical确定性成本估算 → 已知小计、缺项与历史。

复用BuildDemand同次持久basis/demands、供应成本包cost_candidate及Decimal引擎、CostBreakdown组件、共同确认/幂等/Receipt/Audit/Outbox。领域适配只拥有成本输入/结果；不建立第二份Build或MaterialDemand。新增辅助具名人工cost.inputs.record为T1，cost.estimate.compute保留canonical T0；不改变AI资格或T2批准。

输入覆盖物料/工艺/一次费报价、原币与计价分母/单位、数量阶梯/有效期、税/运费、直接汇率实际观察时点/用途/年龄上限、工艺每合格产品用量/损耗与来源、NRE排除/单列/摊销。来源范围由服务器绑定，不能由客户端提供权威ref/hash/租户/资格事实。未知不补零，不由节拍推工艺成本；费用估算不当ERP正式成本、财务批准或已实现降本。

输入准备只保存未应用capture，确认预览绑定整份前后版及固定读集；一次确认消费与输入版本/当前指针/回执/审计/Outbox同事务。当前ACL/精确原文/原件摘要/有效性在预览、应用与重放检查，报价和汇率时间重新核对。历史结果固定当时输入，续版不覆盖旧结果。

独占分工：cost_execution领域模型/schema/service；test_cost_execution关键事务与边界；build-cost界面与view helper；主线统一注册、实际head后的迁移、API/BFF/父入口、隔离环境及公共验证。已交付供应/品质/文件安全包保持原归属；本轮不修改成本纯算法或共享展示包。

仅已核对127.0.0.1:62513/pdos_test与marker916f950f-2d2b-405d-b809-c15db75dc20c供集中PG检查。迁移前私有备份，新表写业务数据前做往返/schema；闭环候选再集中联合检查、生产构建、实际浏览器/HTTP及亮暗/多尺寸。存续57432、旧库/旧业务工作不操作；不push、部署、出站、真实模型调用、授资格或代替人工Exit。
