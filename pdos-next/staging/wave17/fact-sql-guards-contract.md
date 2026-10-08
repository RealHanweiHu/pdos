# Wave17 SQL 守卫暂存准备合同

本段只有新 `fact_sql_guards.py` 与本文。它生成 SQL 字符串，不执行 SQL、不注册模型、不分配迁移号、不修改已应用 0024/0025 或公开候选。Rule/Observation/Review/Candidate 的业务 writer、七类真实 owner 门禁与有效性/关闭仍须主线分别接线。`SqlGuardPlan.authorized=False` 不产生资格、当前读取证明或许可。

## 实际旧函数绑定与调用

主线在明确独立目标的 READ ONLY 事务读取的六个 `pg_get_functiondef`，见 `docs/reports/evidence/pdos-next-wave17-20261003/sql-actual-functions-v1.json`。本模块硬绑定其六个完整定义 SHA256；不是假定迁移源码等于当前数据库。任何定义或签名变化均拒绝生成，需重新审阅。主线实际迁移仍须在持有迁移锁时重新读取并核对，旧观察文件不能证明未来现场未变。

```python
from fact_sql_guards import build_guard_plan

plan = build_guard_plan(actual_six_definitions)  # Mapping[signature, pg_get_functiondef]
# 只有字符串；由 Root 的单调迁移逐条执行，不能交给模型或客户端。
```

生成结果有 `preflight`、`replace_functions`、`new_functions`、`new_triggers`、`permissions`、`rollback_preflight`、`rollback_guards`、`restore_functions`、原定义摘要和五张生命周期表名。调用没有 arbitrary SQL/table/role/issuer 参数，无模块导入时 IO、DB 连接、`commit` 或自动执行入口。

恰好替换四个旧函数：

1. `assert_quality_followup_proof(uuid,uuid,uuid,text,jsonb,timestamptz)`：旧三用途原检查不变；只加新三个人工操作的精确 tier 和全目标 proof union。
2. `protect_quality_followup_confirmation()`：旧三用途与新 candidate/observation/review 同样只允许 INSERT 未消费、精确 False→True、已消费不可改/删。
3. `require_quality_followup_consumption_atom()`：保留旧 RootCause/Complete/Link 反向 union，追加新三个人工目标；每个真实 transition 恰好一个同 Product、writer、operation 的目标。
4. `assert_quality_change_receipt(uuid,uuid,uuid,integer,text,text,uuid,text)`：只扩四个 operation→Outbox event 分支，旧唯一 Receipt/Audit/Outbox/具名 actor/requester/run NULL 检查原样保留。

`assert_quality_followup_receipt` 与 **0025 修正版** `require_quality_followup_atom` 原定义逐字保留；旧 `require_quality_change_atom`、合并/失败映射/Change capture 守卫及其触发器不替换、不删除。不会重新引入 0024 JSON 箭头/减键的优先级缺陷。回退使用现场绑定的原四份定义，不能拿 0024 原始 Issue 函数覆盖已修 0025。

## 四个 target 与唯一账本

| 实际 target | operation | tier | subject_type | Outbox |
|---|---|---|---|---|
| `capa_verification_rule_facts` | `quality.capa.verification.rule.import` | host_import | `capa_verification_rule` | `CapaVerificationRulePublished` |
| `capa_observation_facts` | `quality.capa.observation.record` | T1 | `capa_observation` | `CapaObservationRecorded` |
| `capa_named_verification_reviews` | `quality.capa.verification.review` | T2 | `capa_named_verification_review` | `CapaVerificationReviewed` |
| 现有零行 `capa_verification_evidence` | `quality.capa.verification.candidate.record` | T1 | `capa_verification_candidate` | `CapaVerificationCandidateRecorded` |

前五张新表声明直接取冻结 `fact_storage_models.py`：三个不可变事实＋`capa_current_verification_rules`/`capa_current_observations` 两个系列指针。本模块不复制表 DDL；模型全部 full-scope FK/CHECK/Unique 由 Root 真实迁入。父 `confirmations` 必须先由 Root 同步 ORM 与数据库 **UNIQUE(tenant_id,id)**，供新事实 proof 复合 FK 使用；此模块预检查该精确列顺序，不自行增加父约束。

Candidate 继续保留旧不可变身份、revision=1、status=candidate、result=indeterminate 和 applicable/independently_verified/observation_complete 三个 NULL。没有改旧模型、把 candidate 变 effective、或扩 Issue 状态 CHECK。

Candidate.input_snapshot 精确四字段：

```text
{
 semantic: 真实 module.semantic 的无 token 对象,
 shared_proof: {id: 实际 Confirmation UUID, tier: "T1"},
 proof_consumed_at: 实际捕获的 aware ISO 字符串,
 stable_anchor: 完整 StableCapaAnchor
}
```

候选 `intent_digest` 为 **实际共同 intent**。Receipt.result 精确展平 `id/revision/status/candidate_binding_sha256/inspection_sha256`；三个新事实展平 `id/revision/status/fact_kind/payload_sha256`。body payload SHA、candidate binding/inspection SHA 都不替代完整 FactRef SHA。Receipt 中不装 fullCandidate/fullFact SHA，避免原子组自身产生摘要循环。主线候选 writer 须显式提供该 action_result；现旧 Candidate 模型没有这个 property，不可仅凭默认三字段回执声称新出版完成。

## 前置与安装顺序

Root 的实际单调迁移须依序：

1. 核实际 head、六定义与旧触发器；保存备份和旧证据。新增父 Confirmation 复合唯一约束，保持旧数据/函数不改。
2. 运行 `preflight`：锁 Confirmation/Receipt/Candidate；旧 Candidate 必须仍零行，新四操作无既存 Receipt、新三人工操作无既存 consumed proof。旧三操作真实 retained 行允许保留，不重写。新五表由 CREATE 建立，不能悄悄收养已存在的事实表。
3. 用冻结模型创建五表及其真实 FK/Unique/CHECK；确认对象尚未公开。
4. 执行四个 `replace_functions`、六个 `new_functions`、随后 `new_triggers` 与 `permissions`。所有函数仅普通 SECURITY INVOKER，新函数固定 `search_path=pg_catalog,public`；无 SECURITY DEFINER、可信 GUC、SQL issuer self-grant。
5. Root 加入生命周期 catalog 的 covered/guarded 五表与实际所有列；model imports/registry/用途矩阵/writer/真实消费 callback 分别完成后才考虑业务接线。旧 Candidate 的 lifecycle/RLS/retained 触发器复用，不重复建立。

新事实 INSERT 必须与准确 Receipt/Audit/Outbox/初始 RequestKey 同组；初始 key 检查沿旧 `assert_quality_followup_receipt`，恰好一条且 actual writer、receipt_id、digest=Receipt.request_digest。后来的合法 alias 不被要求 digest 相等，不能以任意 alias 证明原摘要。每个新 Receipt 也有反向 deferred trigger，不能只生成回执而无真实 target。目标与 Receipt 的 common intent 精确相等；不重算失去 token 的 request_digest，不把 domain intent 与 common intent 强行等同。

## 数据守卫与缺失可信根的区分

新六函数分别承担来源声明闭包、完成版 origin、Current CAS、目标原子组、target trigger、Receipt reverse trigger：

- 来源读集 1..20，Artifact/来源 basis 身份唯一；完整 basis 与 reads 一一匹配；当前 `artifact_versions` exact tenant/product/id/revision/hash/status/owner/visibility。原 sparse `artifact_sources` JSON 保持原样，不补 typed nullable 字段、不改变旧 inspection/basis 摘要。嵌套精确原值、native 登记回执、UploadedOriginal 的实际 bytes/hash/safety/epoch 仍由现真实 source/owner 端口核验，SQL 只检查原声明关联。
- 完成版 origin 的精确 IssueVersion/ref/revision/snapshotSHA、actual operation/actor/save clock、完整 Issue/input/authority/policy/原 persisted basis 保留；须有 root cause、全部实际 completion、awaiting_verification，无 needs_recheck/merge/effectiveness/history/closure。原失败完整 source reads 必须包含在本次读集。当前 Project actual owner/private 边界保留。SQL 不删历史来比较 Current，不把任意旧版变成 origin；有限后继链与真正失败原报告门禁仍须 owner。
- Current 首版只能 fact revision1/epoch1、series_id=事实 id；更新只能 exact predecessor/+1 revision/+1 epoch，Row id/created_at、scope/origin/owner/visibility/purpose/nature/anchor/requirement 不变。Rule issuer key/external_id 不变、version 可随实际 target 明确更新，epoch 不后退；Observation 的 fixed Rule/executor 前版关系沿 frozen FK。不可 DELETE、跳步、改 scope、回退或 ABA 用旧 epoch。
- Rule/Observation 每个新版本与同版 Current 必须同 UOW 提交；该 v1 事务形状是每 series 一次 append＋exact Current，若未来在同事务追加同 series 多版，不能假称已支持，需要另冻 lineage/原子规则。
- Observation 记录保存实际 observed interval、每 target 原时钟与本次收到时钟；未知记录或缺项不变成 complete。Review 核 exact Candidate/Rule/ordered unique Observation refs、同 scope/anchor/requirement/purpose/nature 与观察前后钟。完整子 ref SHA 仍由真实完整 saved-group reader 核，不拿 SQL body SHA 替代。
- 公共新操作 proof 固定 Product subject/actor/operation、当前 Product 水位、原 token/material/proof expiry 与实际 consumed/save clocks。c.snapshot 的 operation/完整 readset 要相等；真实共同消费仍需完整 reviewed snapshot/material 比较与 False→True marker，SQL 不猜尚未冻结的 after 展示字段。旧消费 bool 无法借作新目标：新用途零 legacy-consumed 前置＋双向 transition/单目标 union＋不可变 retained 事实共同维持该不变量，支持 SAVEPOINT 回滚，无 xmin/top-xid 伪证明。

保存时钟是全部 owner/proof IO 后实际捕获值，SQL TTL 比较用该 saved_at；**不声明 COMMIT 时刻另取时钟判 TTL**。具体 runtime 时效/源撤回/issuer/专业 ABA、seven callbacks/postIO refresh、真实 UUID→Invocation.decision_id 仍由 Root 消费与 writer 协议保障。ProductGrant 普通 can_write 检查不授专业资格；可信 Rule issuer 仍只能宿主内部持有，无公开 PAYLOAD，不造 SQL 许可。

## 权限、保留和回退

五表 ENABLE+FORCE RLS，tenant_scope 与旧模式相同。PUBLIC/agent 无新表权限；app 对不可变 facts 仅 SELECT/INSERT，零 UPDATE/DELETE。两 Current 仅 SELECT/INSERT 和字段精确 UPDATE(fact_id,fact_revision,epoch；Rule 另 issuer_version)，其余 identity 字段不可写。新函数 REVOKE PUBLIC/agent EXECUTE，仅 app 可执行普通 invoker 检查。Candidate 只在新 atom 安装后由 SELECT 扩为 SELECT/INSERT，旧 immutable/RLS/lifecycle 不动。所有受控 writer 仍须先取得共同 Product 门栓，不能把 SQL trigger 的后置锁误称任意直接写路径无死锁。

回退必须持表锁且五表/Candidate/新用途 Receipt/consumed proof 全空；有 retained 事实直接拒绝，不清数据。Root 先移除本段触发器/新函数，恢复四份准确旧定义，再删除五张空表/metadata/canonical接线与生命周期新增目录，最后移除仅供新 FK 的父 unique。Candidate 恢复 SELECT-only。旧 0025 Issue/旧 RootCause/Complete/Link/merge/change 保持。返回的 rollback 字符串没有 DROP TABLE、DROP 父约束或旧函数修改，Root负责实际依赖顺序。

## 此段明确未完成

SQL 未执行、未安装真实 constraint/trigger/RLS，离线 Python 导入/AST/plan 构造不证明 PG 语法或运行行为。主线必须做真实模型相容/往返、四个合法 atom、错 scope/current/partial group、旧 consumed proof/no-target/多 target、跨 table proof、SAVEPOINT/Outbox 回滚、同/跨 key replay、Current 回退、private/source/issuer/专业撤回与 agent 零写。

`quality.capa.effectiveness.decide` 与 `quality.issue.close` 的两个 T2 Issue append/Current/companion 还没有支持。本段不扩大旧 IssueTarget status/operation CHECK，也不把它们塞进 Confirmation scope。其 named UUID、真实七 gates、政策与有限后继共同 atom 必须另冻并由主线单调迁移。没有这两个出口，四个新出版/记录 target 的存在仍不能宣称 CAPA 有效或 Issue 关闭。
