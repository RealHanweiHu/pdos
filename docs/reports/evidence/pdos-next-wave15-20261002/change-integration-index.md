# Wave15 B 当前公共接线索引

本索引对应 [change-native-freeze.json](change-native-freeze.json)，保留 [原冻结记录](change-freeze.json) 与 [原接线说明](change-integration.md)。主线已澄清并授权原生不可变文本与上传原件两类真实来源；service 当前 SHA256 为 `40448bde0b3cae0bb944e4e68ad41a4d5ec3047b137917794741c1bed04cc69f`。50 项独占纯检查通过，新三项 PG/HTTP 事务用例只静态检查、未运行/未收集。本文件不是公共集成完成证明。

## 模块与公共动作

| 接线点 | 当前精确接口 |
| --- | --- |
| 新包 | `pdos_next.domain.change_execution`，`models` / `schemas` / `service` / `graph` / `adapters` |
| canonical T0 | `change.request.create` → `ChangeCreatePayload`；`change.impact.compute` → `ImpactComputePayload` |
| 共同 handler | `validate(s,ctx,command,product,payload)`；`semantic(payload)`；`preview_view(s,ctx,command,product,payload)`；`apply(...)`；`replay_subject(s,ctx,command,product,payload)`；`replay_subject_type(payload)` |
| 共同保存结果 | `apply` 返回 `(ChangeRequestVersion, 'change_request', visibility)`；Receipt.subject_id 是不可变版本行 `id`，不是逻辑 `change_id` |
| 输入核对 | `inputs(s,ctx,product_id,Command)`；建议 `POST /v1/products/{id}/change-execution/inputs`，不落业务结果/回执 |
| 固定图捕获 | `prepare_capture(s,ctx,product_id,GraphCaptureInput)`；建议 `POST .../change-execution/captures` |
| 只读列表 | `list_changes(s,ctx,product_id,*,issue_id=None,change_id=None)`；建议 `GET .../change-execution?issue_id=&change_id=` |
| 服务器依赖 | `configure_store(engine,OriginalStore)`；固定 Issue 默认 A `get_issue(s,ctx,pid,logical_id,revision=None,write=False)`；可 `configure_issue_loader(engine,callable)` 注入同签名可信端口 |

两动作当前仅具名本人 human、Product 当前写权限及相同项目/精确用途的实际专业资格。专业角色为 quality / engineering / manufacturing；ProductGrant 不替代专业事实。没有 AI 自动执行资格、T1 第二确认或 T2 批准入口；两动作不得改写为 T1。主线应给 canonical 注册、实际专业 operation 矩阵及事件映射，保持未完成操作不在开放 payload 注册中。

## 精确输入与响应

`ChangeCreatePayload`：`title`, `reason`, `roots: Ref[]`, `references: Ref[]= []`, `sources: SourceRef[]`, `visibility: private|product='private'`。不接收 change_id、scope、project、actor、审批、图完整性。roots/references 至少固定一个真实 Issue 或其 CAPA；服务器从固定引用推出 project/purpose，并用 scope+actor+audience+排序后的专用语义稳定生成逻辑 UUID。新请求 revision=1，首前版为空；客户端换 key/UUID 不另建请求。

`Ref` 为 `{id,revision,kind,key}`。Issue 使用 `{id:logicalIssueID,revision:固定Issue聚合版,kind:'issue',key:null}`；CAPA 使用相同 logicalIssueID/聚合版、`kind:'capa'`、真实 CAPA UUID 字符串 key。没有任意 UUID 的领域证据转换。首版须当前已分诊/CAPA Issue；A 的旧版 `not_evaluated_historical` 不能作为新写依据。Issue 后来续版时旧 Change 的新计算明确 `RECHECK_REQUIRED`，不自动取最新或把历史提升成 current。

人工新 `SourceRef` 仅 `{id:ArtifactID,revision:固定Artifact版,kind:'artifact',position:'line:N;quote_sha256:<整行SHA256>'}`。GET source_options 返回 `{title,quote,source,required_source_read_set}`，可直接选择精确原文；quote 是完整实际行，不能用子串摘要替代。旧 Failure/Run 中的已核验历史 position 由 A/保存执行桥读取，不重新造定位。

`ImpactComputePayload`：`change_id`, `expected_change_revision`, `snapshot: {id:CaptureID,revision:1,kind:'graph_snapshot',key:null}`, `hypotheses: [{text,sources}] = []`。hypotheses 是有出处的假设，不授根因结论；不接收结果、完整性、作用域或批准。

`GraphCaptureInput`：`capture_key`, `change_id`, `expected_change_revision`, `reason`。捕获返回 `{capture,impact_payload,required_source_read_set}`。capture 精确字段是 `id/revision/change_id/change_revision/graph/expires_at/created_at/current/source_status/owner_id/visibility/reason/required_source_read_set/impact_payload`。exact key 回读同 ID/图/created_at/expires_at，不续期；不同载荷用同 key 返回 `IDEMPOTENCY_CONFLICT`。最长期限 10 分钟并受当次专业有效期限制；专业/来源/安全/issuer/runtime 漂移或到期阻断计算，不能覆盖旧图。

inputs 返回 `operation/change_id/purpose/allowed/authority/required_source_read_set/blockers/source_status/scope/review`。review 是 `{before,after,effect,read_basis:{source_basis,authority}}`。共同 preview_view 另有 name、server_on_save、稳定 pure_preview_digest/runtime_stamp；after 是完整纯 ChangeRequest，首次 before=null，impact before 为固定旧聚合版。T0 可直接共同 execute，不消费 Confirmation。

GET 返回 `{changes,captures,current_by_change,reference_options,source_options,capabilities,authority,unavailable_count,has_more}`。change 项是 `id`（版本行）、`change_id`、`revision/project_id/request/owner_id/visibility/status/created_at/current/source_status/required_source_read_set/authority/capabilities/blockers`。Current map 值为 `{version_id,revision}`；request 保留完整 `assessments[].graph/known/unknown/hypotheses`。top capabilities 有 `change.request.create`，只从选定 Issue 精确 scope 推出；每行 `impact_compute`；`order_approve/implementation_record/effectivity_record/verification_record/close` 全 false。不可见来源隐藏整条派生对象。

## 三表、DDL/RLS、生命周期与 Current 守卫

| 类与表 | 关键持久字段与模型约束 |
| --- | --- |
| `ChangeRequestVersion` / `change_request_versions` | tenant/product/project、逻辑change_id、版本行id/revision、previous_version_id/previous_revision、owner/visibility、operation、draft/analysis、intent_digest、request_snapshot/request_sha256、sources/readset/source_basis/authority_snapshot；project scopedFK、owner scopedFK、same tenant/product/project/change 的精确自前版 FK；逻辑版唯一；owner/op/intent 唯一；首版1前版null，继版连续；orders 强制空；完整读集1..20 |
| `ChangeCurrent` / `change_request_currents` | tenant/product/change_id/version_id/revision；同产品同逻辑身份唯一；精确 FK → `(tenant,product,change,id,revision)` |
| `ChangeGraphCapture` / `change_graph_captures` | tenant/product/project/change_id/change_version_id/change_revision、id/revision1/prepared、owner/visibility、capture_key/input_digest、graph_snapshot/graph_sha256、sources/readset/source_basis/authority_snapshot、created_at/expires_at/reason；精确 scopedFK 固定 Change 版本；owner/capture_key唯一；expires>created 且<=created+10min；readset1..20；nature 明确 real/synthetic |

主线模型注册与迁移需三表 tenant RLS；版本和捕获不可 UPDATE/DELETE，仅受控 SELECT/INSERT。Current 需要受控指针 UPDATE 和行锁，禁止 DELETE。Current 首 INSERT 只能指向 revision1/无前版，UPDATE 必须同 tenant/product/logicalChange、连续 old.revision+1，并要求新版本 previous_id/revision 恰为旧 pointer；固定 project/owner/visibility/scope，不可回退、跨链、覆盖逻辑身份或删后重建。

`change_request_versions`、`change_graph_captures` 的 sources/readset/source_basis 必须加入主线 lifecycle 受控引用目录及 Product 同门栓守卫，包含历史版和预备图；Current 是指针而不是另一份来源真值。永久保留引用不能只统计当前 Change。主线迁移按实际 head 单调分配，不由本包指定号码。

## 原生来源与原件门槛

共同 `source_for` 每次先核当前 consumer ACL、产品/租户、固定 revision 与 active 状态，两类都核实际 content_hash。无 original_id 的原生文本必须存在唯一实际 `evidence.artifact.register` Receipt：精确 tenant/product/subject_type=artifact/subject_id/revision；requester=Artifact.owner、visibility相同、Receipt.result 的 id/严格整数revision/登记active 相同。实际 Principal 必须可核；human 原登记 actor=requester/run=null，agent 则精确实际 Run 的 tenant/product/requester/writer 绑定。原登记者后来 Grant/active/资格不重写历史来源；当前 consumer 权限独立核。basis 标 `source_origin='registered_native_text'` 及 registration receipt/command/actor/requester/run/digest，不声称文件、仪器原报告或 scan clean。

有 original_id 必须沿真实 UploadedOriginal 的 ACL、parsed、安全判定与 epoch、有界 bytes/hash/size 回读；读取后重核 epoch。basis 标 `source_origin='uploaded_original'` 并保存实际 original/hash/revision/security_epoch。不能因有 native 兼容而回退绕过有 original 的拒绝。测量固定失败仍必须经 root 真实原报告/原值/retained bridge，不能借本包 native 路径造测量资格。缺任一真实 proof、实际存储或固定 owner 端口均 503；完整读集合并去重最多20，超限422、不截断。

## 图、事务及尚未开放边界

复用旧 `ChangeControlHandler` / DTO / `compute_impact`，不复制算法。实际已读 Issue失败→Build/Sample/Run、Definition/规格、BOM行/Part、工程配置、制造配置/工序/SOP字段、已登记 Build 关系；固定合法旧配置可用，不擅改为 latest。图最多250节点，每类 owner 查询最多100，超界拒绝。SOP 节点只表示固定 Process 中真实 SOP 字段，不能冒充独立正式发布。全八 facet 都 `unknown` 并有原因；已知行/边仅说明实际读到的关系，不能将空子图、完整计数或 synthetic 资料当全范围覆盖。

`prepare_capture` 在 caller Session/UOW 写可恢复图，宿主 route 正常提交该预备事务，不生成第二份 Receipt/确认。之后 canonical impact 另在共同 command 同一 UOW 原子新增 Change revision2、推进 Current、写一次 Receipt/Audit/Outbox；B 不 commit/rollback 或另 mint 回执。末端失败应整组回滚新版本/指针/共同记录，此前已经提交的捕获保持原样。重试 samekey/semantic 原回执前仍核当前人/ACL/来源/专业与捕获依据；所有 bytes I/O 后刷新 owner/source/safety/authority/runtime，专业撤回/恢复 ABA 不复用旧图。

Order/T2批准、实施、生效单位/批次/序号、后续有效性验证和关闭均不开放；纯 port 明确 `INTEGRATION_REQUIRED`。Tooling/Fixture/ControlPlan/PilotRun、全体库存/WIP/生产切换、培训、客户外发/接收与变更后证据适用性的完整 owner 端口仍缺。必须在主线报告保留这些未知，不称 G3、整改、生产启用或人工 Exit 通过。

## 主线待运行的三项事务选集

`tests/change_execution/test_transactions.py` SHA256 为 `9726106e991f402ea6d695d0b55db42ecec1e8bfed40816d7791f422e981f317`。复用 A `quality_work→publish_policy/create_issue/draft_capa`；独立 change-only 资格在 Issue 创建前导入，不另造 Start、报告或 Issue。

- `test_current_issue_capa_create_cross_key_one_receipt_exact_sources_and_private_scope`：当前固定 Issue/CAPA 与两类真实来源、canonical T0 单回执、跨 key 去重、opaque/伪CAPA引用/私有受众与他人访问拒绝、终态来源撤回/DB拒绝恢复 ABA。
- `test_graph_capture_exact_key_fixed_roots_unknown_facets_expiry_and_qualification_aba`：samekey不续期/改载荷冲突、固定根/完整读集、八facet未知、缺读集拒绝、真实qualification revoke→restore epoch3旧图拒绝；过期分支是模拟 evaluator 读取钟，不宣称实际等待10分钟。
- `test_impact_terminal_outbox_failure_rolls_back_version_pointer_receipt_but_keeps_capture`：共同末端故障全组回滚、预备捕获保留、原命令重试真实v2及一组 Receipt/Audit/Outbox、跨 key 回执复用、issuer disable 阻断原回执重放。

只通过 Ruff/format/compile 与 AST 三函数静态确认；PG/HTTP、公共迁移与全候选验证由主线执行。任何新失败按其实际原因修复，不为测试通过降低完整读集、CAS、专业资格或原件门槛。
