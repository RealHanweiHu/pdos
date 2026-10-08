# Wave18 事实写入适配合同

本文件绑定 A 新增 `fact_commands.py`、`fact_write.py` 与两个独占纯测试文件。没有改旧事实协议、模型、codec、消费 Host、公共注册、迁移或服务；没有执行数据库、HTTP、浏览器。下述 owner 返回值必须由 Root 实际受控宿主产生，离线替身通过不是资格、原件真实性或七门禁通过。

## 操作与入口

| kind | operation | tier | Receipt subject | event |
|---|---|---|---|---|
| rule | `quality.capa.verification.rule.import` | host_import | `capa_verification_rule` | `CapaVerificationRulePublished` |
| observation | `quality.capa.observation.record` | T1 | `capa_observation` | `CapaObservationRecorded` |
| review | `quality.capa.verification.review` | T2 | `capa_named_verification_review` | `CapaVerificationReviewed` |

Rule 只有可信宿主入口，不加入公共 PAYLOADS、不产生 T2 proof。Observation 与 Review 当前请求的办理人必须是当前真实具名人；`ProductGrant` 只证明当前写权限，不能转成专业资格。

## 严格客户材料

三类共同材料为 `issue_id`、严格正整数 `expected_issue_revision`、`capa_id`、`sources: SourceRef[1..20]`、`reason`、`visibility: private|product=private`。修订不得接受 bool。SourceRef 保留 `id/revision/kind/position`，精确重复拒绝，原 JSON null、选择顺序和微秒时钟保留。载荷全部 extra forbid。

Observation 另有完整真实 `rule: FactRef`、`previous: FactRef|null`、`target_keys[1..10000]`、`observed_from/until`、实际 `at: EventTime`、`records[1..10000]`、`coverage_sources[1..20]`、`confirmation_token|null`。每个 record 只含 `target_key/occurred_at/original_timezone/sources/raw_material`。原始未知/null 可以保存；服务端核真实来源并派生 `missing_fields`，客户不能补 coverage/complete/pass/参与者/issuer。发生区间递增，记录落在选定目标与区间内，事件不得带拟议 effective clock。相同原记录不能通过重排 JSON 键重复计数。

NamedReview 另有 `candidate: FactRef(v1)`、`rule: FactRef`、有序 `observations: FactRef[1..64]`、实际 `at`、`pair_applicability[1..10000]`、`action_fulfillment[1..10000]`、`conclusion: applicable|not_applicable|unknown`、`approval_token|null`。pair 输入为完整 `FailurePairMapping`、method/criterion SourceRef 或 null、结论/reason/sources；action 输入仅 action_id/结论/reason/sources。完整参与者与措施 owner 材料由宿主读取；Review 客户不发送参与者、独立 bool、scope、资格、provenance 或完整 FactBase/body。

RulePublicationInput 是服务器内部材料，不是公共客户命令：真实 origin VersionRef、previous、external_id、policy_ref/method/criterion、完整 SamplingRequirement、rule/independence 原材料与固定有效期。issuer 与 publisher 准入仍由实际 owner 提供，不能由输入字符串自授。

`semantic(payload)` 再作严格 native 属性验证，完整 canonical JSON dump，只移除本操作对应 token；不排序选择、不移除 null、不插入时钟或 UUID。UTC 等价 offset 会按 Pydantic 的真实微秒 instant 规范化，原提交 Command、key 和 SourceRead 原序不被 writer 改写。

## 实际 owner 协议

`FactMaterialOwner.read(s,ctx,product_id,kind,payload,*,new_write)` 与独立 `refresh(...,previous,*,new_write)` 返回 `FactWriteMaterial`；`runtime_stamp(s)` 返回当前完整受控 registry/profile/callback 的 SHA256。

`FactWriteMaterial` 精确字段：`body_material`（RuleDraft/ObservationDraft/NamedReviewDraft）、`anchor`、`current_issue_version_id`、`current_issue_revision`、`series`、`authority_snapshot`、`policy_snapshot`、`inspection`、`valid_until`。Draft 是既有严格 body 去掉自己的 `ref`、`created_at`，没有 provenance，不预造 FactAtom/full SHA。`CurrentSeries` 为实际 SQL 读取的 `id/series_id/fact:完整FactRef/epoch`。Review 没有 Current。

owner 必须核当前原件 bytes/精确原值/所有来源 ACL、原件安全/issuer、原 origin 与实际有限谱系、Rule/候选/Observation 完整 full ref、实际专业与 policy、所有参与者及其 owner 真值；`valid_until` 必须是完整当前 scope 的最早有效期或未来 activation 边界。缺实际 owner、专业矩阵、政策或参与者端口，须明确 503，不返回假肯定。

原完整 anchor 从可信候选或已存 Rule 获取并保留。fresh owner 只按既有三条精确路径比较稳定失败材料：`result.retained.checked_at`、`result.retained.execution_window_elapsed`、`result.source_basis.runtime_stamp`；不重新封印原 full proofs/full anchor，不递归删除其他字段。这个比较由实际 owner 完成，writer 不替代七门禁或有限谱系 owner。

Observation visibility/owner/purpose 必须严格继承 original closure/Rule；payload visibility 必须一致，private 只原 owner，product 材料不得混入 private Source。Review 的 caller 仍独立核当前资格，且不得是宿主完整实际参与者之一。

## 准备与共同消费

- `prepare_fact(s,ctx,pid,payload,*,host,new_write=False)`：默认用于 replay/current gate；新 preview/apply 显式 True 才检查 expected Issue Current CAS。旧 expected revision 不放行新意图。
- `FactWriteHost(owner)` 登记只属于实际 Session/完整活动 UOW/ctx 的 opaque PreparedFact；复制 dataclass、改材料、换 UOW 或 owner/runtime 均拒绝。登记不是缓存专业许可。
- `reviewed_fact(phase,*,host)` 返回严格 13 键：`operation,payload_semantic,stable_anchor,binding,inspection,raw_source_basis,required_source_read_set,sources,authority_snapshot,policy_snapshot,owner_id,visibility,current_issue_revision`。`binding={kind,body_material,current_issue_version_id,series}`。没有未来保存钟/未来 fact UUID/伪造 provenance。
- Root 在实际 common 模块消费之前调用真实 ConsumptionHost.bind；真实 persistent Confirmation false→true 赋值后第一行捕获消费钟。preview/replay 不产生 marker。
- `apply_prepared_fact(s,ctx,command,product,payload,phase,*,host,consumption_host,module,proof,consumption_binding,consumption_marker)` 比较真实 proof.snapshot 全 13 键、Command/module semantic/完整 SourceRead，随后独立 owner.refresh。实际 Current/Project/private/Principal/Grant/runtime/UOW 在全部 owner、series SQL 后重新核对，最终真实 UTC clock与 proof exclusive expiry/最早 activation 边界核到保存时点。body 序列化后再次核期限与 live marker。
- `append_prepared_rule(...,host,module,common_intent_digest)` 仅可信 host 流程；publisher 独立当前操作准入，proof 所有字段为 NULL。common intent 仍须按真实共同公式精确匹配，不拿 body payload SHA 或领域摘要替换。

## 保存与系列

writer 只构造既有 Fact row、`s.add` 与现有 Rule/Observation Current 推进，不 flush/commit/Receipt/Audit/Outbox/consume/reserve。Root 同 UOW 共同尾部负责真实原子组与错误回滚。body 使用现 schema `pdos-capa-fact-body-v1`，payload SHA 与 frozen codec 完全一致；完整 child FactRef 摘要保留。未来 full FactRef 只能从 actual committed common group reader 重组，不以 UUID、payload SHA 或未来 FactAtom 代替。

新 Rule 必须先核 exact scope/anchor/issuer_key/external_id 的真实 Current；新 Observation 核 exact scope/anchor/Rule/executor 的实际 series。已有系列时不能通过新 UUID+previous=null 另建版本。后继锁精确 Current，核 scope/purpose/owner/受众/series/full previous ref/epoch，revision+1 与 epoch+1，只推进同一 Current。Review 是独立不可变 row，不引入 ReviewCurrent。

SQL 全部有界 limit2/populate_existing/autoflush=False；Product 统一先锁，immutable Fact 不 FOR UPDATE。保存 FactBody、snapshot、raw basis、sources 与读集是完整 JSON 数组/字典，不将 Pydantic tuple 默认字符串化。stored body 仍是材料，实际原件/资格/七门禁由真实 host/reader 证明。

## 本段验证边界

最终 owned pure 59 项，真实 ORM Session/活动 UOW/loaded persistent Confirmation 与 False→True history，source/SQL/专业 owner明确替身；SQLite engine 不连接且连接钩子失败。覆盖严格越权字段/布尔 revision、原 JSON 重复与 null、微秒/IANA、完整 T1/T2消费绑定、未知保存、独立本人、私有 Project/来源、复制 phase/无事务、旧请求 replay vs新 Current CAS、系列初版绕过/精确后继、末端 runtime/权限/Current/expiry 漂移、body 序列化跨 activation 期限。59 项不代表 PostgreSQL FK/RLS/commit/公开 HTTP/生产资格或完整业务闭环通过。初始导入错误、离线 clock 替身错误及修订日志保留；Root 统一真实集成验证。
