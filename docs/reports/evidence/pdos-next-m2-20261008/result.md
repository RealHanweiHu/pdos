# M2 独立合成候选 · 2026-10-08

小Pai 内核、公开研究、预算和整次撤回技术端已完成授权内独立实现。最终统一候选 **217 passed / 1 deselected，40.40s**；唯一排除项是旧 `test_migration_matches_orm_and_test_guard`，它比较共同 ORM 与未合入完整 0400..0699 分支的 schema，须由主会话 B7/B8 公共合并验证，不计为通过。完整原始日志见 `kernel-final.log`。`candidate-manifest.json` 固定 106 个自持源文件，摘要 `978495eec62f29cfa54482909582dc716668642192f5153482e6bfb73e827379`，共同依赖仅记录检查后观察值，由主会话统一冻结。

可用能力：唯一注册小Pai六节点图、渐进技能包与固定提示/工具前缀、服务器绑定 category/run/writer/requester/taint、原生双协议工具与 strict schema/SSE、受控 T0 领域回执/T1 候选/T2 仅准备、独立 AgentSession/AgentRun/工具调用/事件/等待答案、当前权限撤销与取消、真实 PostgreSQL 检查点恢复、Temporal reference-only workflow/Activity、薄 HTTP 202/过程/SSE/答复/取消端口、真实 signed-DPA 管理入口与 MCP 当前 grant 检查。缺租户实际模型/领域适配时保持 visible unavailable，不给模型调用本地后备。

研究：search/read/fanout、只读独立子任务线程、逐字引用与实际读取定位校验、schema/子类型/字典版本绑定、覆盖/失败/未读保留、并发 4、域名限速、固定公有 IP/TLS/重定向/响应边界、容器 PDF 解析与私有 tenant/run 快照台账保存；主图不接收原始网页/MCP 指令。子任务经同一注册小Pai图/网关，引用校验后返回结构台账。69 个研究 fixture 测试包括在以上 217 项中，不能重复累加；研究子目录的独立证据见 `research/result.md`。真实外部网页和真实模型未调用。

用户新增规则：当前授权将普通 `Grant.expires_at=NULL` 解释为无到期，仍检查 active/can_write/实际范围；过期临时授权、撤权、失活和跨范围继续拒绝。品类级 NULL product 的实际 Original/Artifact 引用可读取，撤销任一来源受众后派发/消费拒绝，NULL 不能扩大已有产品 Run 的范围。证据见 `tests/agent_kernel/test_membership.py`、`test_category_sources.py` 及最终日志。

整次撤回：`prepare_run_revert` 返回完整实际回执，隐藏/缺失/错误 writer 一律整次拒绝。**当前公共业务 owner 只支持 `evidence.claim.record` 的 Claim 和 `evidence.artifact.register` 的独立 Artifact（`original_id IS NULL`）**；其他操作、已改变对象、T2 或后续消费使整次请求拒绝，不会只撤回支持的部分。公共 owner 核对完整对象集合后，在同一 UOW 撤回这些对象并写 Human T1 `ai.run.revert` 回执、Audit/Outbox，调用 `finish_run_revert` 只记录技术状态。执行终态与历史结果保留，epoch 阻断后续执行；未知发送成本全额保留。实际公共 HTTP 预览→确认→命令已验证产品级、品类级、幂等重放、公开及 RLS 隐藏的私有 Definition 消费拒绝，以及 finish/Outbox 末尾注入失败后的 Claim/Artifact/Run/Confirmation/Receipt 全回滚。`public-run-revert.log` 的 6 项已包含在最终 217 项中。HTTP 使用 FastAPI TestClient、真实公共路由/命令/UOW 和独立 PostgreSQL，历史输入明确为合成；覆盖限定为公共 Human 撤回入口，没有触发 Agent 生成或 Temporal 派发。六项逐项覆盖及出口边界见 `candidate-boundaries.md`。

计费：同一批准钱包跨 Run/子任务原子预约 USD/输入/输出/次数；当前价格卡绑定准确配置，纯文本收费上界和全部收费口径未核对时 0 HTTP；Decimal 缓存拆项，未知结果/取消/崩溃/对账保留估算，已知实际 usage 与 request-id 可持久重放，超预算返回 partial 保留结果；费用机制及实际费用资格限制见 `cost-meter.md`。

迁移：自持分支 `s0_0700`–`s0_0715`，以 `s0_0011` 为共同基线；**down s0_0011 → up s0_0715 成功**。随后最终元数据检查再次确认 **12 张自持表差异 []、共同 Receipt→AgentRun 精确品类 FK 已安装且 validated**。仅使用 M2 marked `pdos_test` / checkpoint fixture，每次数据库操作前核对实际目标，显式 TEST_DATABASE_URL，未操作主会话库或 runtime.json。按根会话授权只复制 0404/0405 最小共同字段和 0406–0409 冻结函数/约束作为真实公共测试 fixture；不把公共 Alembic 分支标为已应用，逐条摘要见 `common-fixture-sync.json`。证据为 `migrations-down-0011.log`、`migrations-up-0715.log`、`m2-owned-metadata.txt`。往返在新增公共业务原子 fixture 前完成；现在工具会拒绝删除这类回执，未为重复往返清除它们。代码 lint 通过（`kernel-lint.log`）；独立迁移 lint 仅忽略长 SQL 的 E501，其余规则通过。

剩余依赖：**B7 仍须在主库汇合 AgentRun 迁移和新执行适配**，包括共同 Context/check_run、实际公共 Agent HTTP → Temporal → Worker、旧 SourceWork 模型生成能力统一至新注册图、公共 metadata/完整回归及前端过程与恢复入口。共同 Receipt 字段由根会话提供、精确 FK 由 0714 安装；公共 Human 整次撤回 owner 已在私库合成验证，不能据此认定主库 AgentRun 已可用。M3 负责规格/知识/提案/G0/compute 领域 owner，**未来 G0 提交/批准对 Grant.product_manager 的实际消费和评审人资格拒绝由 M3 实施验证**，本候选未覆盖。逐项合同与端口见 `b7-integration.md`；这轮独立测试不冒充公共 Agent 闭环或正式阶段出口。

真实模型调用 **0**，真实 provider 资格、T0 资格、生产启用和 **M2 正式退出均未通过**。必要服务商/准确模型/隔离租户 SecretPort/仅合成出站/计费上界/USD10及次数/token授权，待 B7 可执行候选由主会话向用户申请，提案见 `real-model-validation-proposal.md`。旧 .env 的模型文本与凭据存在状态仅作非敏感只读事实，未复用为资格或许可。原工程、停用备份、golden-case 与唯一活动清单未由 M2 修改；该清单由主会话更新。
