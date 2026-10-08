# Wave16 B 两表公共接线只读审阅

状态：静态接线建议，不是迁移或数据库验收。仅定向读取当前声明、共同命令服务、生命周期目录及已冻结 `migrations/schema_0023.py` / `versions/0023_quality_and_change_execution.py`；沿主线已确认的真实 head23 设计后续单调迁移，**未查询数据库、未分配迁移号、未改任何源码或冻结候选**。B 39 项纯检查仅支持包内逻辑，不能替代以下公共约束验证。

## 1. 精确模型、字段和现有父约束

主线 metadata 必须导入 `pdos_next.domain.capa_verification.models.RemediationLinkRecord` 与 `CapaVerificationEvidence`。先建 `capa_remediation_links`，再建 `capa_verification_evidence`。这两张表都是 revision=1 的追加记录，**无 Current、无前版链、无 Issue/CAPA 新账本**；回链接线不得写 `quality_current_issues`。

两表共有列如下；`created_at` 即服务器 received_at 的持久来源，不另建客户端接收时钟：

| 组 | 精确列 |
| --- | --- |
| Row | `id UUID PK, tenant_id UUID NOT NULL, created_at timestamptz NOT NULL` |
| 固定范围 | `product_id, project_id, issue_id, issue_version_id, capa_id` UUID；`issue_revision integer` |
| 责任及语义 | `owner_id, writer_id` UUID；`visibility varchar(16), purpose text, nature varchar(16), revision integer, reason text` |
| 完整固定证明 | `basis_snapshot JSONB, basis_sha256 varchar(64), sources JSONB, required_source_read_set JSONB, source_basis JSONB, input_snapshot JSONB, intent_digest varchar(64)` |

`capa_remediation_links` 另有：`action_id UUID, output_snapshot JSONB, resolution_sha256 varchar(64), authority_snapshot JSONB, policy_snapshot JSONB, status varchar(16)`。status 只能 `recorded`。

`capa_verification_evidence` 另有：`remediation_link_id UUID NULL, candidate_binding JSONB, binding_sha256 varchar(64), candidate_snapshot JSONB, inspection_sha256 varchar(64), status varchar(16), result varchar(24), applicable/independently_verified/observation_complete boolean NULL`。status/result 只能 `candidate` / `indeterminate`，三项专业结论必须 SQL NULL，snapshot 对应三项必须 JSON null。

### 已声明的 PK / Unique / FK / index

两表均有：

- PK `(id)`。
- Unique `(tenant_id,product_id,id)`。
- Unique `(tenant_id,product_id,project_id,issue_id,capa_id,id)`。
- Unique `(tenant_id,product_id,owner_id,intent_digest)`；不要把这个 B 专用意图摘要误当共同 Receipt.intent_digest，二者算法形状不同。
- FK `(tenant_id,product_id,project_id,issue_id,issue_version_id,issue_revision)` → `quality_issue_versions(tenant_id,product_id,project_id,issue_id,id,revision)`。
- FK `(tenant_id,owner_id)`、`(tenant_id,writer_id)` → `principals(tenant_id,id)`。
- Row 的显式索引分别为 `ix_capa_remediation_links_tenant_id` 和 `ix_capa_verification_evidence_tenant_id`；模型未声明其他独立 Index，Unique 已提供唯一索引。

Candidate 另有 FK `(tenant_id,product_id,project_id,issue_id,capa_id,remediation_link_id)` → `capa_remediation_links(tenant_id,product_id,project_id,issue_id,capa_id,id)`。允许 NULL，因为 CandidateBinding 可含多个精确 link refs，或没有单个主链接；服务仍逐项核绑定里的全部链接。**不要为了便于 SQL 再要求 Link.issue_revision == Candidate.issue_revision**：真实 owner 契约允许固定语义未变的 Issue 聚合追加，服务对 action/requirement/failure/completion/来源重新核；Scope/Issue/CAPA 不能变化。

head23 的 `quality_issue_versions` 已有被上述 FK 引用的六列 Unique，不需要重复添加父唯一键；Issue 自身 `project_fk()` 已把产品/项目绑定到 `projects(tenant_id,product_id,id)`，两表通过精确非空 Issue FK 继承该范围。

模型没有给这些 FK/Unique/Check 显式约束名，Base 也没有 naming_convention。本报告不捏造 PostgreSQL 已生成名字；Root 冻结 DDL时以实际生成语句为准，不把新手写约束或索引加进迁移而漏出 metadata。

### 不能遗漏的 CHECK

两表共有 `revision=1 / issue_revision>0 / visibility∈private,product / nature∈real,synthetic`，完整读集必须 array 且长度 1..20。basis_snapshot 的 tenant/product/project、Issue logical/版行/revision、CAPA、purpose、nature必须与列逐项一致，缺 key 使用 COALESCE false。

Link 还检查 `input_snapshot.shared_proof.tier='T1'`、id 为 UUID 文本且 snapshot 不含 confirmation_token/approval_token；output_snapshot.action_id/resolution_sha256 匹配列。**UUID 格式和 JSON摘要对应仅检查形状，不证明实际签核、对象真实或一次原子提交**；由下节补齐。

## 2. Link 的共同原子组与具名 actor

已冻结命令为 `quality.capa.followup.link`，Receipt subject family 精确为 `capa_remediation_link`，subject_id=`capa_remediation_links.id`，subject_revision=1，result 应保留共同 `append_receipt` 的 `{id,revision,status}`。回链不生成第二个 Issue Receipt。

建议主线新建独立的 Link guard，而不修改已应用 schema23。可采用新函数名 `require_capa_link_atom()`、新 constraint trigger 名 `capa_link_required`，在 Link `AFTER INSERT DEFERRABLE INITIALLY DEFERRED FOR EACH ROW` 执行。名字是**新增建议**，尚未注册。不可用普通 BEFORE INSERT 检查尚未 flush 的 Receipt/Audit/Outbox，合法共同 flush 顺序是 Link → Receipt → Audit/Outbox → RequestKey。

延迟 guard 至少核以下真实组，缺行、JSON 缺 key 与 NULL 都拒绝，不能只使用 nullable `<>`：

1. 通过精确六列 FK 对应的 IssueVersion，检查其 `issue_snapshot.capa.id` 为本 CAPA，CAPA actions 中恰有本 action_id；basis.actions 的 action/固定 executor/action_sha/completion 引用不能换成另一个 action。Issue logical ID 与版行 ID 不可混用。
2. Link 的 basis/输出/input 均绑定同一个 Issue/CAPA/action；input.expected_issue_revision 与 issue_revision 一致，input.output_refs 与真实 resolved outputs 的 ref 集/顺序语义一致；output_snapshot.basis 等于 basis_snapshot；action_fulfilled 必须 JSON null，不允许输入输出把缺项改成已满足。来源和完整读集固定保存，不能使用只含 positive facts 的子集。SQL可检查保存组的一致性，但不能代替 owner API 的当前资格/原件 bytes/hash/实际适用核验。
3. 新写时固定 Issue 当前CAS：末端 `quality_current_issues` 精确指本 IssueVersion/revision；这是 INSERT 当次约束，**后续 Issue 合法追加不反向否认历史 Link，也不允许重放回退指针**。不要对所有历史 Link 每次扫描要求最新 Issue。
4. 唯一共同 Receipt：tenant/product/op=`quality.capa.followup.link`/subject_type=`capa_remediation_link`/subject_id=本 Link.id/rev1；actor_id=requester_id=Link.writer_id=Link.owner_id，run_id IS NULL，visibility 相同，result.id/revision/status 与 Link 一致。authority_snapshot.subject_id 应为该真实 actor；不能取 Issue 原 owner 充当本次批准人。scope/project/op/purpose必须与实际 Link 相同。
5. 同一 Receipt 恰好一个 Audit，actor/op一致；恰好一个 Outbox，receipt_id、actor、subject/revision、correlation_id=Receipt.command_id、schema_version=1均一致。事件必须来自共同 EVENTS 的**一个固定已注册值**。建议新事件 `capa.followup_linked`，目前尚未冻结；Root决定后 Python EVENTS 与 SQL期望同步。不能借已有 `capa.drafted` 或 `issue.*` 事件声称聚合推进。
6. `input_snapshot.shared_proof.id` 对应真实 `confirmations.id`：tenant/product/actor/operation 精确相等，subject_id 为 Product.id（不是 Link.id），revision 匹配本次确认的 product expected_revision，consumed=true、payload_digest/实质snapshot 与本命令实际消费证明一致，证明有合法有效期。不要把 Confirmation.revision 误当 Issue revision 或 Link revision。新公开 payload 不收 proofID；B callback `(s,ctx,command,product,payload)->UUID` 返回实际行 UUID；缺 callback503、bool/None/string 不合格。
7. 同一 proof 不可用于另一 Link/另一 operation/intent：延迟组按 proofID 绑定唯一消费目标。形状检查不够，须真实行对照与跨Link重用否定。Proof.token_hash可用于主线内部核验，原 token 不入 Link、日志或证据。主线 common 消费与末端 callback/SQL必须在同 Session；Outbox失败一起回滚 Link/Receipt/Audit/RequestKey/Confirmation.consumed。

Root 可复用 head23 `assert_quality_change_receipt` 的**核对模式**，但该冻结函数 op→event CASE 尚无本 op，直接调用会因 expected_event NULL 拒绝所有合法 Link。新 helper或单调迁移替换函数需保留原八项映射，不能让新分支不匹配就静默成功。

Link 不需要新独立 receipt_id 列；延迟 guard 通过 canonical subject 选唯一 Receipt即可。Confirmation目前也没有 `(tenant_id,id)` Unique供新组合 FK，本最小接线使用SQL精确tenant查询与同事务callback，不凭空假设已有可引用父键。

## 3. Registry、专业和 runtime 接线

| 接点 | 精确接线 |
| --- | --- |
| contracts.PAYLOADS | `quality.capa.followup.link` → `capa_verification.schemas.FollowupLinkPayload` |
| command_handlers.T1_OPERATIONS | 增加上述 op；不放 T2、不另开第二次确认 |
| command_handlers.handler | 上述 op → `capa_verification.commands` |
| service.EVENTS | 上述 op → Root 冻结的新固定事件；Python/SQL保持一致 |
| 当前专业 operation matrix | 明确职责矩阵 + exact purpose。矩阵缺配置返回503；ProductGrant.can_write/AI资格不替代专业权限 |
| runtime | `commands.configure_consumed_proof(engine, require_consumed)`；callback核实际已经被common消费的 exact T1 proof，返回真实UUID |
| replay family | `commands.replay_subject_type(payload) == 'capa_remediation_link'`；`replay_subject`返回原 immutable Link |
| API/BFF | 共用命令preview/execute；`quality-followup/inputs` 分派该op，不另开直接save Link接口 |

Common execute 现在先当前产品/Grant/source/专业 validate，再 RequestKey/semantic/subject replay，最后仅新写 consume proof+apply。须保留这一顺序：旧 intent只有当前全部门禁合法且保存的 authority/policy/source/readset 精确重核后返回原Receipt，**不二次消费，不覆盖旧 Link，不回退Current**。B `_intent` 与 common `intent_digest` 不同，使用各自实际字段，不写SQL等值假设。

B的 `commands.apply`仅返回 `(RemediationLinkRecord,'capa_remediation_link',visibility)`；不自行add/flush/Receipt/commit。Root 不要另调用独立纯handler的确认/Receipt层。旧输出状态只是 owner 固定事实；回链不授 formal发布/量产切换、effectiveness 或 close。

### Candidate 暂无 canonical 写入配对

`CapaVerificationEvidence`目前只有读模型与 `inspect_candidate/inspect_verification`，**没有 public payload/operation/writer/shared proof/Receipt family**；其声明不能视为允许插入或有效性证据。

建议本波为 Candidate 仅授 app SELECT，尚不授 INSERT；若 Root 要实际保存候选，须先冻结独立具名写合同、同一次proof/Receipt/Audit/Outbox和候选完整 owner/failure/pair证明，再增加写入与原子guard。不能套 Link 的 Receipt，也不能为使两表看起来对称而注册 `quality.capa.effectiveness.decide` 或 `quality.issue.close`。任意 SQL候选被现有CHECK锁成 indeterminate仍不等于来源可验证。

## 4. RLS、immutable、生命周期门栓

两表均应 ENABLE+FORCE ROW LEVEL SECURITY，policy 名沿现有每表 `tenant_scope`：USING/WITH CHECK tenant_id=`nullif(current_setting('pdos.tenant_id',true),'')::uuid`。无会话tenant应拒；FORCE RLS不是私有范围授权，产品/项目/owner/private ACL仍由当前服务独立核。

- Link app权限 SELECT,INSERT；Candidate上述保守SELECT；不授UPDATE/DELETE，不以SELECT FOR UPDATE锁 immutable行。具名 human写，pdos_agent仍业务表零直接写。
- 两表 trigger `retained_record BEFORE UPDATE OR DELETE` → 既有 `protect_next_snapshot()`；权限与trigger双保留，admin正常历史UPDATE也拒。
- 两表 trigger `lifecycle_reference BEFORE INSERT OR UPDATE OR DELETE` → 既有 `lifecycle_reference_gate()`，形成 same Product gate下引用写入与原件生命周期互斥；不可只保护Link而漏候选的固定来源/measurement/report。
- `lifecycle_catalog.COVERED_COLUMNS`须登记这两表全部实际列；`GUARDED`增加两表，保证 `schema_covered`核真实enabled trigger/function名字。metadata导入与catalog更新必须一致；漏表时应 UNKNOWN，不能把新增表排除成“无引用”。
- 两表不得加入 `NON_CONSUMING`；basis/output/candidate嵌套UUID、完整Artifact读集与保存的历史Receipt均是正式引用闭包。现References通过受核全部metadata表递归UUID，不另建只查当前Link的孤儿判定。
- 无 physical purge/原件改写；文件恢复不恢复withdrawn Artifact、不授专业或候选有效性。Native登记文本与uploaded original来源proof保持现有不同路线，测量仍实际原报告bytes。

## 5. 与 A 的 Issue追加迁移衔接

虽然B只增加两表，Root还需以新单调迁移扩现有 `quality_issue_versions` operation CHECK，加入 `quality.issue.root_cause.decide` 和 `quality.capa.actions.complete`；旧status CHECK只有 open/triaged/actioning，kernel全部完成进入 awaiting 时亦需真实允许。保留原scope/前版/owner/visibility/CAS/Current epoch和merge完整原子约束。

Rootcause为T2，ActionsComplete为T1；两者 canonical Receipt subject仍 `quality_issue`。A实际 shared_proof存于新IssueVersion.source_basis.shared_proof，B存于Link.input_snapshot.shared_proof，**公共guard不可读错JSON路径**。T2 kernel根因 `decision_id`须等于实际已消费proofID；Rootcause实际actor不是原Issue.owner。A append_issue同Session一次IssueVersion+Current+Receipt/Audit/Outbox，不能创建第二账。不得在新函数扩展时遗漏head23 merge/FaultAlias/EventFailureLink原子分支。

## 6. 主线检查最小范围与回退纪律

实际执行前再核真实head；本报告不预留编号。冻结DDL与model完全一致、升级/降级顺序依赖正确（先撤Candidate后Link，相关新函数在trigger移除后撤）；有留存新表历史拒破坏性downgrade，不能为通过往返删数据。

Root公共验证至少覆盖：两表scoped FK/forcedRLS/Agent0/immutable；正确T1 Link一次完整原子组；缺Receipt、缺Audit/Outbox、假proof/跨op重用proof、JSON缺key、错CAPA/action、错actor/project/受众、伪action_fulfilled、CurrentCAS漂移拒绝；Outbox尾部故障回滚证明和全部组；同key/跨key历史重放不再确认；来源/专业/政策withdraw→restore epoch拒；合法Issue非实质追加不无故让固定Link历史不可读。候选未开放写入，capability保持null/indeterminate/effective=false/close=false。旧八facet UNKNOWN无本波清零权限。

结论：模型可直接由Root接入，精确父Unique已具备；真正新增的公共责任是 Link 的具名T1实际proof→canonical Receipt/Audit/Outbox延迟原子guard、两表lifecycle coverage、及Candidate写入保持失能。以上均尚待主线真实迁移/事务验证，不能以模型声明或39纯检查宣称已经通过。
