# 第十五波：失败、问题/CAPA 与双线变更衔接草案

状态：仅下一闭环设计建议，尚未冻结实施合同或启动本波施工。第十四波结果候选已挂载，公共联验由主线进行；本文件不声明该波通过，也不更新 G3 状态。依据[执行方案 G3 与 §13](2026-10-02-pdos-next-execution-plan.md)、[目标架构“变更：同时穿透产品和制造”](2026-10-02-pdos-complete-target-architecture-v1.md)、[第十四波实施合同](2026-10-02-pdos-next-wave14-results-implementation-contract.md)。

## 第一可用闭环

先交付“固定失败 → 原问题复用或建单 → 分诊/遏制 → CAPA 草稿 → 双线变更请求与影响回读”，覆盖 G3.1 的真实入口与 G3.2 的提案入口。用户能从同一 Run 失败行进入问题，看到原值、固定配置、责任与下一步，并提出有明确来源的工程/制造变更；当前缺边显式停在 UNKNOWN。它不是完整 G3.3，也不借变更草稿宣布批准、实施、生效或整改有效。

1. 从服务器当前可读的 Run/Measurement/Projection 选择确定失败的具体测量。重验原件、方法、判据、实际样件/配置及保存的执行证明，复算所选 pair 必须为 fail，且与固定判定一致。通过、未知、无效、计划 Run 和专业文字处置均不能冒充该失败事实。
2. 复用 `quality.issue.create`：服务器从固定失败重算稳定身份；同失败换 event/key/title 仍返回原问题。同一真实结果事件可以包含多个失败，事件投递与业务去重分别保存。先采用明确选择失败的具名入口，不先接自动事件消费或 AI 自主建单资格。
3. 展示当前问题/原单历史，按当前风险政策分诊，记录实际遏制及独立发生时钟；CAPA 保存根因假设、纠正/预防措施、责任人、精确失败范围与复验/观察要求。草稿不等于已证根因，措施完成不等于有效性或关闭。
4. 从固定 Issue/CAPA 和明确规格/配置项提出 ChangeRequest。确定性影响同时展示工程与制造路径、每条出处、在制 Build、供应/库存/WIP、客户样件、证据适用性、切换与培训的覆盖缺口；AI 推测单列，缺边不当作无影响。
5. 有 UNKNOWN 时保留可读提案和下一责任；不开放 order 批准或实施。真实图、适用范围与政策完整后，才另接固定 ChangeOrder/EffectivityPlan 和工程、制造分别具名 T2 决定。
6. 后续通过原对象所有者追加新 Definition/BOM/工程配置或 ProcessRevision、新 Build/样件及新 Run，引用实际实施/生效事实，再作独立复验、CAPA 有效性及问题/变更分别关闭。旧 Run、测量、批准、占用和消费不覆盖；原失败 Run 不能自证整改有效。

## 可直接复用与必须适配的接缝

| 已有代码/实体 | 复用方式与边界 |
|---|---|
| `domain/verification_results/` 的 `MeasurementRecord`、`TestResultProjection`、`TestResultActionFact`；`domain/verification_launch/` 的 Run 版本链 | 读取精确测量 ID、原 token/位置、判据、`basis_sha256`、规则版本和真实结果事件；Issue 只存固定引用，不复制一套测量真值。Projection 是固定规则结果，T2 意见独立保留。 |
| `domain/quality_issues/rules.py`、`handlers.py`、`read_models.py` 与 `schemas/quality_issues/contracts.py` | 复用稳定失败身份、归并、遏制、CAPA、独立有效性/关闭规则。`FailureRef.run.revision` 是精确核 Run 版本，不能用新测量表的 `revision=1` 替代；CAPA 暂无独立版本，引用 Issue 聚合版本并明确 CAPA key。 |
| `domain/change_control/rules.py`、`handlers.py`、`read_models.py` 与 `schemas/change_control/contracts.py` | 复用有出处边遍历、coverage/UNKNOWN、分专业批准、精确生效单位、未知回执对账及独立关闭。现有纯包没有持久 ORM、实际端口、公共注册或页面接线，不能复制其合成 approved/effective 为当前业务事实。 |
| `DefinitionRevision`、`BomRevision`、`EngineeringConfiguration`、`ProcessRevision`；Build/ActualConfiguration/Lot/Sample | 用固定版本和 BOM/Spec/工序 key 组成服务器图。新配置仍为不可变 draft，续版按 `previous_id`/期望版本 CAS；历史 Build 固定双配置。实际配置差异是已发生观察，不等于批准差异或制造切换。 |
| 当前 `test_resources.inspect_retained_execution`、专业权威评估、原件安全/生命周期与来源读集 | 区分原发生期间的历史执行证明和当前办理人的操作资格；自然到期不伪造再次可执行，真实撤回/ACL/安全 epoch 漂移仍重核。不会再次 reserve、消费、释放或恢复样件。 |
| `components/quality_issues/` 的 `QualityIssueReading`、`FailureReading`、`QualityActionReview`；`components/change_control/` 的 `ChangeControlReading`、`ChangeImpactReading` | 优先复用只读部分及明确支持的 typed 表单。由新 wrapper 映射实际 DTO、共同预览和原请求恢复；未注册动作/缺端口禁办理，不把旧 workbench 的 capability 默认值当授权。 |
| `build-results` 的独立事件、来源选择、T1/T2/未知恢复模式与 `workspace-api` | 沿用同命令/key/返回的 prepared command；成功后刷新失败分开。当前 Request 数量/模穴与局部 Run 判定分栏，历史只读、跨用户/产品清空敏感投影。 |

具体复用合同见[问题/CAPA 接入说明](../reports/evidence/pdos-next-quality-issues-20261002/integration.md)、[双线变更接入说明](../reports/evidence/pdos-next-change-control-20261002/integration.md)及其 `ui-integration.md`。独立包历史纯检查不能相加为本波联合通过。

## 派工前需主线冻结的实际端口

- **失败与事件适配**：`RunPort.fixed/original/delivery/currentness` 消费当前持久 Run/Measurement/Projection 和权威 Outbox/Inbox。须明确结果事件怎样定位具体失败；客户端提供的任意 event UUID 不是事实。失败身份不包含无关后续 Run 修订，但精确出处/方法/判据/实际配置变化须重核。
- **共同事务适配**：两个旧包的 Invocation 是领域参数，不另建 HTTP 信封。公共 Product 版本与 Issue/Change 聚合版本分别绑定；所有 CAS、稳定失败/事件映射、归并别名、证明消费、回执、审计与 Outbox 在同一调用者 Session 提交/回滚。禁止包内 commit、等待模型/网络或凭新 UUID 绕过业务去重。
- **专业与政策适配**：服务器提供当前职责/资格、风险、独立性、用途和政策版本；能读/写 Product 不授质量、工程或制造角色。旧 `Authority.qualified` 为 bool，适配时不能把当前权威的 null/不可核对变成 true。没有风险/独立政策时阻断依赖动作，不能默认低风险。
- **固定双线图适配**：工程/制造/品质/供应对象所有者提供带版本、边出处及逐 facet 覆盖说明的 `GraphSnapshot`。当前已有工序、SOP、资源要求和供应快照，可读真实边；完整 Tooling/Fixture/ControlPlan/PilotRun、库存/WIP切换及培训事实未接时保持 UNKNOWN。不可为了通过旧完整性规则制造 complete manifest。
- **实施、生效及复验适配**：`FactPort.selection/implementation/effectivity/verification` 只读取所有者已保存的精确对象、批次/序号、条件、输出与真实时间。sent、accepted、effective 分开；unknown 核对同一原意图，不盲目重发。独立复验须新 Run/配置适用性、完整失败覆盖、真实观察窗口及全部原/新执行者集合。

建议宿主 GET 按明确 Build/Run 或 Issue/Change 选择返回历史与当前指针、失败可读投影、Issue/CAPA、双线影响/UNKNOWN、逐行 capabilities/authority/readset、当前政策、允许责任人及后续缺口；空选择不读取全产品历史。readonly inputs 接完整 Command，公共 preview/commands 继续作为唯一 T1/T2 入口。具体路径、载荷、subject_type/event 与当前源漂移语义需在实施合同冻结，本文不将建议当已上线协议。

## 三路并行独占建议

| 路线 | 建议新独占目录/文件 | 冻结输入与交付 |
|---|---|---|
| A 问题持久适配 | `server/pdos_next/domain/quality_execution/`、`server/tests/quality_execution/` | 复用旧质量纯核，连接固定失败/事件、Issue 版本/identity/alias/CAPA、风险与独立政策；先交 `IssueRef + FailureRef + CAPA key + readset/capability` 和模型约束。 |
| B 双线影响与变更适配 | `server/pdos_next/domain/change_execution/`、`server/tests/change_execution/` | 复用旧变更纯核，连接真实配置图与 Change 聚合；先交 GraphSnapshot/UNKNOWN、Issue/CAPA 固定引用及目标受众规则。A 的引用形状冻结后可并行，不等 A 全部动作完成。 |
| C 办理界面 | `web/src/components/builds/build-quality-loop.tsx`、`web/src/lib/build-quality-loop-view.ts` 及同名测试 | 同 Run 失败 → 原单/CAPA → 双线影响与变更草稿，复用两个旧只读组件和当前共同操作模式；按 A/B DTO 并行做表单/历史，缺能力显示实际原因。 |

主线独占旧共享版本链、现有结果/配置服务、共同 command/资格/事件注册、模型导入、单调迁移/RLS/外键、来源与原件引用保护、API/BFF/Workspace、公共数据库/生产构建/浏览器联验及唯一清单。旧 `quality_issues/`、`change_control/` 纯包先保持冻结；确有接口差异再单独明确文件归属，三路不同时修改公共对象。schema/models 先冻结，A/B/C 局部检查并行，公共检查在同一业务候选集中执行。

## 人工批准与验收边界

`quality.issue.create`、`quality.capa.draft`、`change.request.create`、`change.impact.compute` 沿 canonical T0，但仍须实际当前授权与具体操作资格；本波不授 AI 或生产资格。归并、遏制/实际完成、修订/实施/生效等 T1 候选须主线先明确注册，保持一次实质确认。根因结论、CAPA 有效性、Issue 关闭、工程/制造 ChangeOrder 批准、独立变更复核/关闭分别为具名 T2；AI 仅准备候选，不能合并这些决定。CAPA 假设、草稿配置、措施 done、局部 Run pass、客户承认均不能替代其中任一决定。

首版联合验证至少覆盖 AT-23/25 的确定失败/稳定去重与假设分离，AT-24 的工序/治具/SOP缺边，AT-33/35/42 的 CAS、人工维护与撤回保护：同失败跨 key、同 event 多失败、相似标题不同失败、归并 alias/CAS、private受众不扩大、政策/原件/资格漂移、重放前后重新核权、最后一步故障整组回滚、成功回执后刷新失败及原未知请求恢复。后续完整关闭还须新配置/新 Run 适用性、独立人及实际观察期、实施/生效的精确范围与未知对账证据。

当前缺口：实际质量/变更 ORM 与端口尚未接入；完整依赖图、风险/独立政策、新复验/观察证据、真实专业资格和外部生效仍依对应可信事实。CAPA 无效后的追加措施/修订专用动作在旧包尚未实现，不能覆盖原完成或无效决定。第十五波实现/验证完成前 G3 保持未完成；合成演练不代表真实整改效果、生产启用、正式发布、外发授权或人工 Exit。
