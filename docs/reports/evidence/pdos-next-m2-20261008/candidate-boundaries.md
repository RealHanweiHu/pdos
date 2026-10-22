# M2 合成候选覆盖与出口边界

本记录只整理已冻结候选，没有重跑无变化全套或新增代码。`kernel-final.log` 为 **217 passed / 1 deselected，40.40s**；研究 69 项及公共 Human 整次撤回 6 项均已包含在 217 项中，不重复累加。源文件摘要见 `candidate-manifest.json`；文档整理不改变候选源代码。

## 公共 Human 整次撤回的六项

测试文件为 `pdos-next/server/tests/agent_kernel/test_public_run_revert.py`，独立日志 `public-run-revert.log` 为 **6 passed，4.08s**。使用 FastAPI TestClient 调用实际 `/v1/categories/{category_id}/agent-runs/{run_id}/revert-preview` 和 `/v1/categories/{category_id}/commands`，经真实鉴权、确认、领域 owner、共同 UOW、Audit/Outbox 和独立 marked PostgreSQL。AgentRun、草稿及其历史回执明确为合成 fixture，没有模型调用、Agent 生成或 Temporal 派发。

| 项 | 实际覆盖 |
|---|---|
| 1 | 产品 Run 的独立 Artifact 与 Claim 全部撤回；Human T1 确认；幂等重放；原 completed 状态/结果保留；Human 回执及单份 Audit/Outbox |
| 2 | 品类 Run 的 product_id=NULL 独立 Artifact 经同一公共入口撤回 |
| 3 | 外部 Consumption 已消费 Claim 时整次返回 409，Artifact/Claim/Run 不变化 |
| 4 | finish 已执行后注入失败，业务状态、Run/epoch、确认消费、Human 回执、Audit/Outbox 全回滚 |
| 5 | 末尾 Outbox INSERT 注入失败，同一组业务与技术事实全回滚 |
| 6 | 另一 Human 通过真实 product.definition.draft 创建私有 Definition 消费 Artifact；撤回者 RLS 看不到该 Definition，仍因不透明消费守卫整次返回 409，且不泄露私有内容 |

已核对公共 `pdos_next/run_revert.py`：业务撤回分支仅接受 `evidence.claim.record` 的 Claim 和 `evidence.artifact.register` 的独立 Artifact，后者要求 `original_id IS NULL`。还须对象未变化、实际范围/所有者/版本正确、完整回执可读且无后续消费。其他操作或任何不可撤回项使整次请求拒绝；该候选没有证明 Original、知识条目、提案、G0 或其正式结果可撤回。

## 候选与正式出口的区分

| 项 | 当前证据与必要后续 |
|---|---|
| 独立内核 | 已通过注册小Pai图、协议/工具/研究/预算/权限/检查点等合成检查；真实 provider 资格与 T0 资格未授予 |
| 独立迁移 | s0_0011→s0_0715 往返已过；最终 12 自持表差异 []、共同 Receipt 精确品类 FK validated；0404/0405 最小字段及 0406–0409 共同 SQL 只是根授权的私库 fixture 复制 |
| B7 主库和执行 | 尚须主库 AgentRun 迁移汇合、共同 Context/check_run/Receipt 执行适配、公共 Agent HTTP→Temporal→Worker→LangGraph 接线、旧 SourceWork 模型能力统一与前端过程/恢复入口 |
| 公共迁移检查 | 唯一 deselected 的旧 test_migration_matches_orm_and_test_guard 留待 B7/B8 完整公共 metadata/回归，不计通过 |
| M3 领域范围 | 规格/知识/提案/G0/compute owner 及其回执/消费守卫由 M3；G0 对 product_manager 的实际消费和 reviewer_not_eligible 拒绝按 M3 合同 §9 Q1、§8.1 实施验证，本候选未覆盖 |
| 真实模型 | 调用 0 次；待主会话提供可执行 B7 候选后，取得准确服务商/模型、隔离租户 SecretPort、仅合成出站、价格计费上界和 USD10/次数/token 的对应授权；提案见 real-model-validation-proposal.md |

因此，217 项与六项公共撤回支持“授权内独立合成候选通过”，不支持“主库 Agent 已接线”“真实模型/T0 已有资格”“M3 G0 已完成”“M2 正式出口或生产启用已通过”。公共状态与后续授权仍由主会话维护；本任务未修改唯一活动清单或公共代码。
