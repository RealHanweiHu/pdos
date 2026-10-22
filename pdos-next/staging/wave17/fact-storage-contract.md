# Wave17 暂存事实 body 与存储声明合同

这四个文件只声明未注册的模型和纯 codec。没有创建表、授权限、公开操作、host issuer、Rule 出版或业务事实；没有访问 DB/HTTP。原 facts v2、anchor/lineage/paired、公共 server/web/迁移保持不变。后续必须由主线迁入正式目录、安装真实原子组 reader/七类 owner gates 并完成实际验收，才能写入/使用事实。

## 冻结名字和唯一事实账

| kind | operation | tier | Receipt subject_type | Outbox effect |
|---|---|---|---|---|
| rule | `quality.capa.verification.rule.import` | host_import | `capa_verification_rule` | `CapaVerificationRulePublished` |
| observation | `quality.capa.observation.record` | T1 | `capa_observation` | `CapaObservationRecorded` |
| review | `quality.capa.verification.review` | T2 | `capa_named_verification_review` | `CapaVerificationReviewed` |

`codec.OPERATIONS` 只是一份封闭结构常量，不是 registry。Rule 由可信 host importer 及 opaque issuer 出版，不能提供 public self-grant。Observation 只记录实际事实；Review 是具名专业决定，实际 proof UUID 对应领域 `Invocation.decision_id`；同名 AI `models.Invocation` 表不是此 T2 真值。候选操作由 Root 另冻，本段不接。

五个声明复用真实 `Base/Row`、IssueVersion 与 Candidate；只在显式导入本暂存模块的进程中加入这五个 Table 的内存 metadata，不修改公共 imports，不执行 DDL：

```text
RuleFact            capa_verification_rule_facts
RuleCurrent         capa_current_verification_rules
ObservationFact     capa_observation_facts
ObservationCurrent  capa_current_observations
NamedReviewRecord   capa_named_verification_reviews
```

Rule/Observation 支持连续前版的模型声明；没有对应办理 API。两个 Current 是各自事实系列的指针，不是第二份 CAPA/Issue Current。NamedReview 每次另存不可变 rev1/previous NULL，无 Current。旧 Candidate 三 NULL/indeterminate 不改变；有效性/关闭仍应分别追加现唯一 IssueVersion/Current，不在本段实现。

## body codec 的准确输入与摘要

存储列实际名字 **`fact_body`**，它保存完整文档：

```text
FactBodyDocument {
  schema_version: literal "pdos-capa-fact-body-v1",
  body: RuleBody | ObservationBody | NamedReviewBody (discriminator=kind)
}
```

body 精确保留冻结事实的所有字段，只移除顶层 `provenance` 和自身 `ref.sha256`；自身 ref 仍须 exact `{id,revision}`。完整 previous/Rule/Observation/Candidate 子 FactRef 的 SHA、原 source/material/proofs、原 EventTime 微秒和 original IANA、opaque material 中同名的 provenance/sha256 均原样保留；无递归删键或自由忽略列表。

字段类型/Field 约束复用冻结事实；显式 BODY_FIELDS allowlist 校验冻结 DTO 全字段，新增/删除字段会要求 codec revision，不自动放行。body 不带假 provenance，因此冻结 full-fact 的跨字段/消费验证只在 `assemble_fact` 运行。单独 decode 只是合法 body schema，不是完整事实或 current/qualified/applicable 授权。

可复用接口：

```python
encode_fact_body(saved_fact) -> FactBodyDocument
decode_fact_body(document: dict | FactBodyDocument) -> FactBodyDocument
body_payload_sha256(document) -> str
assemble_fact(document, actual_atom: FactAtom, *,
              expected_payload_sha256: str,
              expected_ref: FactRef | None = None)
    -> RuleVersion | ObservationVersion | NamedReview
```

只接受明确 v1 envelope，无 legacy full-fact/JSON 字符串/未知 version/extra keys 回退。`encode` 重新核 full saved DTO，不能信 model_copy/model_construct 绕过验证。`assemble` 需要显式 typed FactAtom，重新验证其全部字段，核 frozen op/tier/subject/event、body payload、scope/ref/received_at/full来源闭包；加入真实 provenance 后计算 full FactRef SHA，再由原冻结 DTO 完整验证。提供 expected_ref 时全 id/rev/fullSHA 必须相等。初次 reader 可不提供 expected_ref 来派生本次真实组的 full ref；后续引用者必须按保存的完整 ref 核对。

`body_payload_sha256(document) == facts.fact_payload_sha256(full_fact)` 精确成立：schema envelope 不入材料摘要；body 顶层全部字段入摘要。`fact_sha256` 还含实际 FactAtom，因此 **payloadSHA 不等于 fullSHA**。Receipt.action_result 固定 `{fact_kind,payload_sha256}`，fullSHA 不进入 Receipt/result，避免它包含 Receipt/transaction 摘要而造成循环。不能拿 body digest、客户端 expected hash 或 codec 类型当完整可信事实。

## 模型列与真实 saved-group reader 接口

事实公用列：

```text
Row: id,tenant_id,created_at
product_id,project_id,issue_id,capa_id,revision
origin_issue_version_id,origin_issue_revision,owner_id,writer_id,visibility,nature,purpose
anchor_snapshot,anchor_sha256,requirement_sha256
operation,tier,fact_kind,status,command_id,actor_id,requester_id
fact_body,payload_sha256,intent_digest
sources,required_source_read_set,source_basis,read_set_sha256
input_snapshot,authority_snapshot,policy_snapshot
shared_proof_id,shared_proof_revision,proof_expires_at,proof_consumed_at
token_sha256,material_sha256
```

`intent_digest` 是宿主在 apply 前可信绑定的 **actual common semantic intent**，reader 核 exact Receipt.intent_digest；不能与领域 `_intent` 不同格式直接比较。`payload_sha256` 只指 body 材料。rule/observation/review 的 status 分别固定 published/recorded/reviewed，Receipt.result 对应实际 version row id/revision/status；action_result 只含上述两个非循环字段。

T1/T2 的 shared proof 六列必填；host_import 六列全 NULL。`shared_proof_revision` 保存当时 Confirmation.revision（Product 水位），`proof_expires_at` 保存其实际固定 expiry。`proof_consumed_at` 只能由宿主在真实 false→true 后、任何 SQL/autoflush 之前捕获并同原子组持久化；模型只保存，不自证。历史 reader 对照原 Confirmation exact 字段，不能用现在 Product revision/now 重新判断历史消费，不能由历史 consumed bool/Receipt.created_at 反推消费钟。

没有未来 `receipt_id`、`transaction_proof_id/hash` 占位列。Root 的实际 committed Receipt/Audit/Outbox/RequestKey/Confirmation reader 派生准确 FactAtom.transaction proof 身份/摘要、actual consumed evidence，再组装 full fact；不能用 xmin/top xid 或可伪造 bool/hash 证明同 UOW。body 与摘要不在 Receipt 建立后 UPDATE。

public preview 是独立 reviewed projection：新 row 的服务器保存钟/身份使用已冻 server_on_save 表达，不能将占位钟塞入要求实际 aware datetime 的 FactBodyDocument。实际 body.created_at 必须在真实消费后采样，与存储 Row.created_at 完全一致；真正 EventTime/原观察钟始终保留，不归一成服务器 now。正式 writer/consume/preview 协议尚未接线。

## 复合约束与未安装的主线守卫

`SCOPE=(tenant,product,project,logical_issue,capa)`。`BINDING` 再带 exact origin IssueVersion/rev、owner/visibility/nature/purpose、anchor/requirement SHA。

- 各事实 `UNIQUE(SCOPE,id,revision)`，原 Issue FK 带 tenant/product/project/Issue logical/ref/rev。row 列与 body scope/ref/kind/anchor、来源数组、actual clock 都有 NULL 拒绕过的 COALESCE CHECK；v1/连续前版 CHECK 显式拒绝缺 previous 的 NULL。JSON 减键前明确括号包住箭头提取，避免旧迁移运算优先级缺陷。
- Rule/Observation 前版 FK 带完整 BINDING/series；首版 series_id=id/rev1，后版 distinct immutable row/+1。同系列 Observation 的 rule id/rev/fullSHA/executor 再有准确前版 FK，不能换绑规则/本人。完整 targets/actual configs 的不变、full source/真实原件等仍需 actual owner/Root guard。
- Current FK 带完整 BINDING/series/id/rev；RuleCurrent 另把 issuer key/version/external_id 绑定 target。Current 首版/单调 epoch/准确 previous 和 Row.id/created_at 不变，需要 Root 的实际 trigger；静态 FK 不能证明换版时序。Rule external series 唯一 scope/purpose/anchor/issuer key/external_id，issuer version 更新不另 fork 指针。
- Review exact candidate FK 复用旧表完整 SCOPE/id、candidate rev1；Rule FK 全 SCOPE/id/rev。body 内有序 Observation 全 ref 的实际存在、同规则/范围、完整 failure/action mapping，需要 deferred/owner 核，不能以一个候选 UUID 或数组长度放行。
- proof FK 是 `(tenant_id,shared_proof_id) -> confirmations(tenant_id,id)`。**现父 ORM 尚未声明 UNIQUE(tenant_id,id)，Root 迁入时须同步 metadata/父约束**；本段不改公共父表。每表 proof UNIQUE 不能替跨 target 的全局一次消费。
- actual named human/角色/当前资格/issuer、消费 marker、false→true双向 target union、唯一合法 Receipt/Audit/Outbox/初始RequestKey及后续 alias、immutability、强制 RLS/agent零写、lifecycle/source闭包、Current CAS 均是主线实际接线前置，非本暂存模型已安装能力。旧三操作/merge guards 不退化；缺 owner/registry/当前闭包保持 INTEGRATION_REQUIRED/missing。

新无关 source 不改稳定锚不等于可省授权：全部原＋新增 source ≤20，每phase全 IO 后 fresh source/issuer/专业/owner闭包和实际 active Session/主子事务，最后真实clock/TTL。无跨phase positive cache、无限 pointer/系列扫描或自动 Review current。

## 本段检查边界

owned `--noconftest` 测试使用既有纯 **synthetic structural** fixture，所有 atom 都是合成输入，不是实际 committed 组。覆盖三类完整 JSON 往返与 payload/fullSHA 分离、childref/嵌套同名键保留、原 EventTime 微秒/UTC instant/IANA、错误 actual atom/组/hash、封闭 schema/naive钟、完整来源闭包以及模型 full-scope/series FK/NULL guard 的离线 DDL 编译。实际缺七 gates 仍返回 INTEGRATION_REQUIRED。

离线 CreateTable.compile 只检声明可编译，不执行 CREATE，也不验证 PG 运行时外键/trigger/RLS/审批原子性。后续 Root 至少需验证 Rule/Obs连续Current、实际消费/组reader、错父scope/epoch/原件/issuer、同key/别key重放、SAVEPOINT/Outbox回滚及 shared/private owner；未验证不得宣称业务闭环或生产资格。
