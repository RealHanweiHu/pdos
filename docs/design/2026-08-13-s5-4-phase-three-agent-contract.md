# S5-4 Phase 3 双 Agent 合同

日期：2026-08-13
状态：冻结，作为 S5-4 实现与验收依据。

## 1. 不变边界

- 两个 Agent 复用现有 dispatcher / executor / model gateway / Finding 人审链，不新建第二套运行时。
- tenant、触发 Project 与 run 均由服务端绑定；模型不能传入或改写作用域。
- `pdos_agent` 对业务表保持零写，只能在有效 run lease 下创建 `pending_review` Finding。
- Finding 的接受与应用仍是两次独立人工动作；Phase 3 输出不能直接更新 Supplier、Project、Risk 或其他事实。
- 动态上下文只追加在冻结 prompt 前缀之后；跨项目摘要只包含服务端预聚合的非身份、非原始载荷字段。

## 2. Supplier Intelligence v1

- `agent_key`: `supplier_intelligence`
- 唯一触发事件：`SUPPLIER_DELAY_REPORTED`
- 入口预检：Supplier 必须是同租户 active 实体；日期必须是 canonical ISO 格式且 `reported_date > expected_date`。不合格事件不入库、不触发 Agent。
- 唯一 Finding 类型：`supplier_delay_risk`
- 输出载荷：既有 `RiskSuggestionPayload`；Apply 后只在触发 Project 创建受审计 Risk。
- 证据：Finding 的 canonical evidence 仅允许本次冻结 run 中的触发事件；额外聚合上下文不能冒充 Finding 证据。
- 只读工具：`get_supplier_delay_evidence`。服务端按 run tenant 聚合最多 20 条供应商延迟摘要，包含项目代码、供应商代码/名称、计划与报告日期；不暴露联系人、凭据或任意原始 Event payload。

## 3. Executive Intelligence v1

- `agent_key`: `executive_intelligence`
- 触发事件：`PROJECT_STAGE_CHANGED`、`GATE_APPROVED`；只在里程碑变化时生成候选，避免每个业务事件都触发高成本组合。
- 唯一 Finding 类型：`executive_portfolio_brief`
- 输出载荷：既有 `RiskSuggestionPayload`，表达需要管理层关注的组合风险；Apply 后只在触发 Project 创建受审计 Risk，不创建新的“高管事实源”。
- 证据：Finding 的 canonical evidence 仅允许本次冻结 run 中的里程碑事件。
- 只读工具：`get_portfolio_brief`。服务端以 run tenant 为边界，最多返回 20 个项目的代码、名称、状态、阶段、开放 Issue/Risk、逾期 Task 与待审 Gate 计数；不返回客户、成员身份、描述正文或其他租户数据。

## 4. 数据库与降级纪律

- migration `0030_phase_three_agents` 只扩展 Agent key 与 Agent/Finding 类型配对约束；迁移号不复用。
- downgrade 遇到任何 Phase 3 subscription/run/finding/quality-control 记录必须拒绝，防止有损回退。
- `infra/postgres/security/agent-runtime.sql` 新增两个 security-barrier 投影并扩展受限 Finding 函数的精确配对；脚本继续幂等。

## 5. 验收

1. 两份版本化静态 prompt、精确路由、确定性 preflight 与 golden cases 全绿。
2. 错误 Agent/Finding 配对、跨 run evidence、模型伪造 Project scope 均 fail closed。
3. owner 与受限 `pdos_agent` 路径均证明：同租户跨项目摘要可见，跨租户与身份/原始载荷不可见。
4. 两类 Finding 均只能经历 `pending_review -> accepted/rejected -> applied`，Apply 产生受审计 Risk。
5. 完整服务端/Web/静态质量门禁无回归；所有数据库测试只连接 `pdos_test`。
