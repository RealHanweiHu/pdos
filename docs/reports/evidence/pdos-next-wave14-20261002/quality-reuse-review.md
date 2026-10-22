# Wave15 品质整改与双线变更复用审阅

状态：只读衔接建议，未启动 Wave15、未冻结实施合同。仅新增本证据；未改代码/测试/清单，未连接数据库或运行公共验证。Wave14 仍由主线验收，本文不把独立纯包或当前施工视为通过。

依据：[Wave15 草稿](../../../design/2026-10-02-pdos-next-wave15-quality-loop-draft.md)、[执行方案 G3/§13](../../../design/2026-10-02-pdos-next-execution-plan.md)、[目标设计 §13/AT](../../../design/2026-10-02-pdos-complete-target-architecture-v1.md)，并定向核对质量/变更纯包与当前配置、结果、共同命令代码。草稿的“固定失败→Issue/CAPA 草稿→双线影响/UNKNOWN”是可实施首个切片；它覆盖 G3.1 入口和 G3.2 提案，不等于 G3.1～3 全部完成。

## 直接复用与实际接缝

| 模块/函数 | 可以直接保留的规则或读取 | 必须新增的适配 |
|---|---|---|
| `domain/quality_issues/rules.py:failure_ref` | 从权威 TestRun 复算具体测量为 fail；稳定身份排除 event/title/无关 Run 修订，固定 sample/item/判据/方法/原值出处；部分返回确定 fail 可用，未知不能建失败单 | RunPort 核精确 Run 版本、原件 bytes、保存的执行/消费证明、性质与当前来源；`FailureRef.run.revision` 用 Run 版本，不能用 `MeasurementRecord.revision=1` |
| `quality_issues/handlers.py:QualityIssueHandler`、`read_models.py:QualityIssueReader` | 业务去重、归并 alias/CAS、遏制、CAPA 假设与具名根因分离；完成→待验证；独立有效性/关闭；按固定 Run 回读原值 | 持久 Issue 版本/Current、失败唯一映射、事件-失败映射；同 Session Command/Run/Evidence/Policy ports。CAPA 目前嵌入 Issue，引用 Issue 版本+CAPA key，不能伪造独立版本 |
| `domain/change_control/rules.py:compute_impact/graph_sources` | 有出处边的确定性遍历、工程/制造双栏、八 facet UNKNOWN、AI 假设分栏 | 服务端构造固定 GraphSnapshot，绑定真实对象/版本/key、受众、来源与完整性；客户端不能提交图/complete/nature |
| `change_control/handlers.py:ChangeControlHandler`、`read_models.py:ChangeControlReader` | 提案/影响状态、逐专业批准、精确生效单位、sent/accepted/effective、未知对账、独立验证与关闭保留 | 首版只接 request.create/impact.compute；没有完整真实图/政策/事实时其余动作保持失能，旧包合成 approved/effective 不可继承 |
| `verification_results/service.py`、`measurement_evidence/verifier.py`、`test_resources/retained.py` | 固定 Measurement、报告定位与核值；规则版本/basis；历史已发生 Start 及原占用/使用，不重新消费 | 主线宜导出只读 `fixed_failure_result` 一类窄端口，返回 VerifiedRun+精确事件/原件引用+readset/source_basis/currentness；不要直接把结果动作专用 `_load/_new_write` 当通用 Issue 服务 |
| `configurations/{models,schemas,service}.py`、Definition/Build/Actual/Lot/Sample | Definition→固定 Part/BOM→工程配置，以及独立 ProcessRevision→工序 key/SOP/BOM 关联；历史 Build 固定双配置；真实 Actual/Lot/Sample 反向链 | Spec 用 Definition 行 key、BOM 用 BomRevision 行 key、Operation 用 ProcessRevision 工序 key。物理设备或 `ResourceRequirement` 描述不能冒充正式 Tooling/Fixture/ControlPlan/PilotRun |
| 共同 `contracts.Command`、`service.execute/consume_material_confirmation/append_receipt` | 当前授权先于重放、Product 与聚合版本分开、单一 T1/T2 消费、Receipt/Audit/Outbox 原子写与旧意图恢复 | 新注册/模型/迁移/RLS/来源引用保护由主线统一。新工程没有同名 `CommandAction` ORM；不可据此另建重复确认/回执账本 |
| `components/quality_issues/{reading,review}.tsx`、`components/change_control/reading.tsx` | 失败/Issue/CAPA、双线影响/UNKNOWN、效果读模型 | 新 wrapper 映射实际 DTO/capabilities 与共同 prepared command；旧 workbench 的候选操作和上下文不构成授权 |

旧工程 `server/app/domain/{issues,capa_actions,change_governance,change_impact_graph}.py` 可参考四眼复核、责任/证据及显式关联经验；其可变记录、旧状态名、ECR/ECN 发布和跨 Engine 事务不直接接入新工程。新纯包已经覆盖更适合当前固定版本链的规则，优先复用它们，禁止导入旧 `app` 或迁移旧批准状态。

## 派工前四个必需合同

1. **结果事件桥接可以实现，但不能只信客户端 event UUID。** 当前 Outbox 没有业务 payload；`test.results_imported/test.run_reviewed/test.disposition_decided` 的 `subject_id` 是精确 `VerificationRunVersion.id`，`test.result_computed` 是 `TestResultProjection.id`。RunPort.delivery 应沿 Outbox→Receipt（tenant/product/operation）→归档 RunVersion，或 Projection.run_version_id，核所选 Measurement/判据与固定失败。一个事件可含多个失败：共同 Inbox 的 `(tenant,consumer,event)` 只登记一次投递，另存 `(scope,event,failure_identity)`；稳定失败映射再独立唯一。不能用一个 Inbox 键吞掉后续失败，也不能凭相似标题合并。
2. **共同事务接纯 handler，不能双执行。** 新 wrapper 的 validate/semantic/preview/apply/replay 符合主线约定。pure CommandPort.begin/replay/confirm/record 要像当前结果适配器一样绑定调用者 Session/已接受的共同证明：record 只暂存领域 mutation，确认和 Receipt 由共同服务拥有；不得在 commonexecute 内再独立消费、commit 或发业务回执。新写锁 Product→稳定 failure/Issue（归并按稳定 ID 顺序）；回放先当前 ACL/来源/专业资格，再取旧 Receipt，CAS 只用于新写，不能回退 Current。
3. **风险/独立政策是实际前置。** 具名 human 的 canonical T0 不增加人工确认，但仍需精确 operation/purpose 的当前专业授权；旧 `Authority.qualified:bool` 只能由真实 assessment `qualified is True` 映射。风险不得默认 low。需服务器固定政策版本及来源、责任人成员检查、完整原/新执行者集合；未接有效性端口必须明确 503/UNKNOWN，不能假造独立人、观察时间或根因。
4. **真实图只能声明实际覆盖。** 现工序/SOP、配置与 Build/sample/result、供应/成本快照可贡献已知边，不能证明库存/WIP/客户样件/生产切换/培训全覆盖；供应 scope_complete=false 不会因进入变更图变 complete。纯核每个可达节点核八 facet，缺正式治具/试产及覆盖出处必留 UNKNOWN，首版禁止 order approve/实施。sources union 去重超过共同 readset 上限20时清楚拒绝，不截断来源，也不以节点上限“完整遍历”掩盖未读部分。

同 Wave14，任何真实原件 I/O 后必须重新核本阶段当前专业/issuer epoch 与历史执行证明，不能仅靠 Product 锁保护服务器 runtime；正常自然窗口到期与真实撤回分开，旧失败可追溯不等于今天仍准许再次执行。

## 最小独占交付建议

| 路线 | 唯一拥有的新文件范围 | 先冻结的对象/接线 |
|---|---|---|
| A 品质持久适配 | `server/pdos_next/domain/quality_execution/{models,schemas,adapters,service}.py`、`server/tests/quality_execution/` | IssueVersion+Current、稳定 FailureMap、EventFailureLink；CAPA/alias/历史先随不可变 Issue 聚合保存。冻结 IssueRef/FailureRef/Issue版本+CAPA key、来源读集、人工能力与 Mutation 接口后 B/C 即可并行 |
| B 双线提案 | `server/pdos_next/domain/change_execution/{models,schemas,graph,adapters,service}.py`、`server/tests/change_execution/` | ChangeRequestVersion+Current、固定 GraphSnapshot+ImpactProjection；消费 A 固定 Issue/CAPA 引用，复用 compute_impact，不等 A 全部操作完成；首版无批准/生效事实 |
| C 真实界面 | `web/src/components/builds/build-quality-loop.tsx`、`web/src/lib/build-quality-loop-view.ts` 及对应测试 | 同 Run 具体失败选择→原 Issue/CAPA→Change/双栏影响；表单与只读详情按 A/B DTO 实现，完整请求失败保留、旧版本只读、失权立即清空敏感投影 |

主线独占当前结果/配置端口扩展、共同操作与专业映射、版本信封/事件、模型导入/单调迁移与全 scope FK、API/BFF/Workspace、原件生命周期引用 catalog/trigger、统一 PG/构建/浏览器及唯一清单。不能在 Wave14 公共候选运行期间修改其冻结代码。旧两个纯包先冻结；接口确需变化再明确归属。上述表名/文件是下一实施合同建议，不是已经创建或验收。

## 原目标验收仍缺的部分

- **AT-23/25、G3.1**：需真实固定 fail 入口、跨 key/事件同失败一单、同事件多失败不漏、不同失败不误并、归并 alias/CAS、原件/资格漂移与末端回滚；CAPA 草稿/措施完成不等于根因、有效性或关闭。独立有效性实际新 Run/新配置适用性、完整失败范围与真实观察期尚未接入，旧纯包缺 CAPA 无效后专用续措施/修订动作。
- **AT-24、G3.2**：首版可验已知工序/SOP影响与准确 UNKNOWN；正式治具/控制计划/试产、供应/WIP切换和培训未接，不能把提案出口登记为完整“穿透制造”或双线实施通过。
- **AT-33/35/42**：需共同预览后目标变化返回实质差异、人工维护不被静默覆盖、来源撤回与受保护下游只标重核/补偿而不级联删除。immutable append/CAS 只能支持其中部分，不能替代 AI 字段锁/补偿边界的完整验收。
- **G3.3 与 AT-07/09/10/24/25/27，相关 AT-26/29/30**：后续仍需新固定配置/Build/Run、当前方法/证据适用性、限定条件、独立 Verification、精确 Effectivity、工程/制造分别 T2、未知外部回执对账和关闭回链。旧失败 Run/局部 pass/客户承认不替代任何决定，合成材料不授真实整改效果、生产发布或外发资格。

## 读取时摘要

| 有限读取对象 | SHA-256 |
|---|---|
| Wave15 草稿 | `98378324dc131b3e8c8bf111fb4326a542d8098d28048c9a161046e133dd7fed` |
| quality_issues/rules.py | `a6504baf0f28049dc0e97313c5c93ce275b86ee0fba7c628db2f90f186f1f92a` |
| quality_issues/handlers.py | `bfa0ddd8bf0fd9013b4f99bc46fb9e42d5ce34c560a2f92c3ee810f2640825e4` |
| change_control/rules.py | `7fa3e719220827e007ba3d0c281892425759d9fae267c44b91859e48c7ec51bc` |
| change_control/handlers.py | `1906a199fa6ecbe3730539955a719434dac1fbbba8a04f141d98147ad2de5673` |
| verification_results/service.py | `c0f4e4dc465868264167c77362ed831224856b923d073e06aae7c3979b27b8d0` |

这些 hash 只描述本次定向读取，没有重新验证旧模块/全工作区；报告文件 hash 另向主线交付冻结。
