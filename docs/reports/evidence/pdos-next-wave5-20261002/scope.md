# 第五波施工合同 · 固定供给来源与齐套缺项

续接第四波已冻结候选；唯一活动状态仍见[清单](../../../../tasks/ai-native-integrated-todo.md#pdos-next-queue)。本闭环复用已保存BuildReadiness完整basis/demands、已交付supply_cost领域规则与覆盖算法、既有历史/短缺界面。

办理范围：固定Build需求 → 有精确出处的整份供给来源草稿 → 人工一次确认保存不可变版本与前版对账 → 确定性齐套投影 → 历史及未知缺项。来源草稿只作未应用prepare，不产生业务回执；提交由共同服务唯一拥有确认消费、Receipt/Audit/Outbox，不能复用独立包另开第二套确认事务。

辅助`supply.snapshot.record`是具名人工T1，保存外部供给来源整份快照；不替代canonical `supply.commitment.record`的T0政策。canonical `supply.kit.compute`保持确定性T0，不新增确认，不授真实AI自动写入资格。人工办理复用当前权限。私有来源不得扩大受众，快照与结果固定完整历史输入。

现阶段无权威外部库存/完整跨Build占用port，范围明确不完整；库存、承诺、在途、到货、质量限制分别保留，阶段不能相加成库存。人工输入不授品质released或availability available，未知数量保持null。缺少替代批准返回无资格，结果不授权开工。成本、完整权威库存/占用与真实资源资格仍待后续。

独占分工：领域适配`supply_execution/`；只读需求适配`builds/demand.py`与对应PG测试、供应事务测试；薄界面`build-supply.tsx`和view helper；主会话统一共同注册/迁移next_0007/API/BFF/入口/隔离数据库/联合验证。已交付供应领域与品质/安全包原目录保持。

仅已核对62513/pdos_test及唯一marker用于PG检查；迁移前私有备份，新数据写入前往返/schema；必要局部验证后闭环候选集中联合检查、生产构建及实际浏览器。57432与旧库不操作，无真实模型/出站/部署/正式资格或人工Exit。
