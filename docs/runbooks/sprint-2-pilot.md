# Sprint 2 双跑试点启动清单

Sprint 2 出口只完成试点能力与安全门禁；具体选择 1–2 个真实项目属于产品/业务负责人的人工决定。试点期间老 CEHub 仍为事实源，PDOS 只体验 AI 面，不替代 ERP/MES/PLM。

## 入选条件

- 有明确项目负责人、Engineer reviewer 与两周以上的真实 Issue/Test/Stage 活动。
- 文档密级允许进入所选模型的上下文白名单；敏感原文不得出门。
- 团队同意所有建议先进入 AI Review；Accept 不等于 Apply，Apply 由有权限的人二次确认。
- 不选择正在处理紧急事故、无可用 reviewer 或需自动写业务表的项目。

## 启动步骤

1. 人工记录项目 ID、负责人、reviewer、开始/结束日期与退出条件；不得由 Agent 自行挑选。
2. 启用对应租户订阅，先验证模型已配置、golden-case 全量通过、预算与出口白名单生效。
3. 注入一条可回滚的真实业务事件，确认自动 Finding 入箱、引用可跳转、Accept 与 Apply 分离且全程留痕。
4. 执行 `make sprint2-removal-drill` 和数据库红队测试，确认移除模型时无新 Finding、Brief/Chat 可见失能、`pdos_agent` 零业务写/零跨租户读。
5. 每周只看接受率、实际 Apply 数、拒绝原因、收窄状态与 reviewer 负担；不以 Finding 产量做成功指标。

## 停止条件

- 任何越权读取/业务表直写、引用失效、降级被伪装成正常：立即暂停试点。
- 任一 Agent + Finding 类型达到最小人工样本且接受率低于阈值：系统自动停止该类型继续入箱，人工复盘 Context Builder、golden case，再决定是否恢复。
- 出现盲批或明显审核疲劳：暂停订阅，不能通过放宽阈值或自动审批解决。

## Sprint 2 Exit 人工记录

- 试点项目 1：待产品负责人填写
- 试点项目 2：可选，待产品负责人填写
- 负责人 / reviewer：待填写
- 启动日期：待填写
- 退出条件：待填写

## 现役 CEHub 候选盘点（未选中）

2026-08-12 对现役 CEHub 做只读盘点：共 4 个未归档项目。下表仅用于缩短人工决策，不代表 Agent 已替产品负责人选定项目，也未触发迁移、订阅或生产写入。

| 候选 | 生命周期 / 阶段 | 进度 | 可用于试点的数据迹象 | 建议 |
|---|---|---:|---|---|
| C4s 手持充气泵（`zGpNH0Xq`） | active / intake | 29% | 21 tasks、8 files、4 deliverable reviews、4 members | 主候选：现有材料与进度最丰富 |
| S18-01 便携户外充气泵（`aBnbEdQG`） | active / concept | 0% | 32 tasks、2 files、2 deliverable reviews、4 members | 对照候选：早期阶段，适合观察 AI 面从冷启动到持续活动 |
| D14-04 便携自行车泵（`WqWcl0wK`） | active / concept | 0% | 32 tasks、2 files、2 deliverable reviews、4 members | 备选，与 S18-01 数据量相近 |
| D15-05 便携自行车泵（`xY8-PGbc`） | active / concept | 0% | 32 tasks、2 files、2 deliverable reviews、4 members | 备选，与 S18-01 数据量相近 |

人工确认时仍需补齐负责人、Engineer reviewer、启动日期、至少两周观察窗口及退出条件；这些信息不能从对象数量推断。

两个推荐项目当前都登记董木榮为 `project_manager`，并都有艾家力（`rd_hw`）与张建营（`rd_mech`）两名工程成员；这些成员关系可作为负责人/reviewer 的人工确认候选，但不自动构成试点任命。S18-01 另登记胡瀚巍为 product owner；C4s 当前未在项目字段中登记 product owner。
