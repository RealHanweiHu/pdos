# Wave17 暂存规则、观察与具名复核材料合同

本段是未挂载的纯 DTO、材料关系核验与宿主读取协议。没有出版事实、Current、公开操作、审批消费、Receipt、提交或资格授予；没有创建 `VerificationEvidence`，也没有复制旧品质核的有效性或独立性规则。生产宿主端口和辅助操作尚未接通。合成检查只验证结构与协议，不证明 PostgreSQL、原件、专业资格或生产可用。

实现范围仅 `facts.py`、`test_facts.py`、本文。首段 `anchor.py`、`lineage.py` 与 B 的 `paired.py` 均只读复用。技术依据是冻结 Wave17 草稿 §5/6/12 及第二段暂存施工合同。

## 1. 三类事实的准确字段

所有 DTO 都拒绝额外字段、冻结模型、重新验证传入模型实例。纯入口还将完整模型序列化后重新验证，不能靠 `model_copy` 跳过摘要核对。

共同 `FactBase`：

- `ref:{id,revision,sha256}` 指不可变版本行；`previous` 是真实前版行与摘要，首版只能 1，后继必须不同版本行且连续。真实同系列 Current/前版关联仍由宿主来源及 provenance callback 核对，本模块不另建 Current。
- `scope`、logical `issue_id`、`capa_id`、精确 `purpose`、完整 `anchor_sha256`、`requirement_sha256`、`nature`、真实 `owner_id/visibility`、服务器实际 `created_at`。
- 完整 `sources`、`required_source_read_set`、`source_basis`；来源安全 DTO 直接复用首段 `SourceSafety`。原生文本必须保留真实登记 Receipt/原作者/requester/run；上传原件必须保留 Original 身份和安全 epoch。文本不能冒充仪器报告。
- `provenance:FactAtom` 固定具名本人、实际操作/tier、原 command、版本、Receipt subject/operation/actor、payload/readset/material/token 摘要、真实 proof UUID、T2 `Invocation.decision_id`、原消费/接收时点、精确 Audit/Outbox 与原同事务证明身份/摘要。

`RuleVersion`：可信 issuer key/version/epoch/nature、实际 policy ref/摘要、**全部原 FailureRef**、**全部原 ActionBinding**、方法/判据 SourceRef、完整已出版规则/独立性材料、固定有效区间和 `SamplingRequirement`。措施摘要复用既有 `capa_verification` 的准确算法：action 排除 completion 字段，completion 另作完整摘要，实际 EventTime 原样保留。采样要求含确定 targets、最少记录、方法/接受出处、完整观察区间以及是否要求新 Run 专业 review/disposition。不会从自由文本解析数字阈值。

`ObservationVersion`：固定 Rule 版/摘要、确定 targets、具名执行者、实际 `observed_from/observed_until`、原始 `EventTime`、实际 records、采样/覆盖出处与原 owner 材料。每个 record 保留原始值材料、实际发生钟、IANA、精确原文来源和显式 `missing_fields`。无 `complete/pass/current` 输入。T1 记录本身不证明采样完整。

`NamedReview`：真实未知候选版本/摘要、Rule/Observation 精确版本、本人复核钟、逐原 Failure 的 `FailurePairMapping` 和实际方法/判据适用结论、逐措施的原 action/completion 及真实分类/履行 owner 材料、完整参与者 owner 材料、具名专业/政策原 snapshot、结论/理由与固定期限。unknown/not_applicable 可作为已保存材料读取，仍产生显式缺项。一般 Run pass 不证明措施履行；`formal_change` 字符串或 owner UUID 存在不能放行。

每条 mapping 必须对上完整实际 paired owner 输出里的不可变 Run 版行、SampleRef（包括实际配置版）、item、原 Measurement、Projection 和固定方法/判据。复用 B 的 `verify_paired_material`，保留原值、实际运行、配对 Formal、Receipt/Audit/Outbox 和确定性计算。新 logical Run 必须不同于任何原失败 Run；不得用失败 Run 的新 Current 替代原 Failure 固定版。多个原失败可经真实适用性 owner 映射到同一新 pair，不另发明一一对应的业务限制。

本模块不判断谁独立或谁具备资格。完整参与者名单是否由实际所有 owner 收齐、是否满足旧核全部风险下的独立性和高风险本人条件，留给真实 participant owner 与旧 `QualityIssueHandler`。

## 2. 结构入口与返回

```text
inspect_fact_material(FactMaterial, FactOperations|None, *, at:aware datetime)
  -> FactInspection{proof:StructuralFactProof|null, missing:[{code,detail}]}
```

`FactMaterial` 保留完整 `StableCapaAnchor`、Rule、Observation 列表、NamedReview 及完整 `SavedPair{binding,material}`，不删除原 history/失败 proof/来源。`StructuralFactProof.structural_only` 恒为 true，没有 current/qualified/result/effective 字段。

确定错绑抛 `DomainError`；缺未确认适用性、实际观察区间/记录、真实履行、规则/Review 时效或未知新结果则返回明确 missing。已保存的判据未知/null、原值未知或覆盖不足不能变成有效性通过。

观察起点不得早于最后一项真实措施完成；区间须实际递增，至少覆盖 CAPA 要求截止。新复验执行/测量不得早于措施完成，具名复核不能先于实际新结果回报。原实际时钟完整保留，不改成 now 或 `server_on_save`。发生和服务器接收是不同概念。

固定摘要覆盖事实全部材料（版本、原钟、原值、参与者、来源、安全和原 provenance）。只有自身 `ref.sha256` 被排除以避免自引用；payload 摘要另排除 provenance 外箱。当前调用者 Grant/剩余时间/实时核对钟只在实时宿主 gate 中，不混入客观事实摘要。锚的 full proof 与 stable failure material 两摘要继续原样保留；本段不新增递归删字段规则。

## 3. 操作 Registry 与真实 provenance

`FactOperations` 必须由 Root 实际注入：

```text
rule_import / rule_tier=host_import / rule_event / rule_subject_type
observation / observation_tier=T1 / observation_event / observation_subject_type
review / review_tier=T2 / review_event / review_subject_type
```

三个名字必须不同；无默认 public 名称。Rule 只走可信内部 host_import，不新增公共 T2，也不在 DTO 中自授 issuer/资格。测试使用 `synthetic.*` 假 Registry，绝不表示这些名字已注册。每个保存事实逐项核对实际 operation/tier/event/subject；不同出版、观察和 Review 必须有不同 command/Receipt，T1/T2 proof 不可复用。

`FactAtom` 的 `transaction_proof_id/sha256`、消费钟、token/material/readset 摘要只能核错配，**不能自证同 UOW 的实际消费**。真实 provenance owner 必须从宿主读取受保护事实、共同 proof、Invocation、Receipt/Audit/Outbox 及 reciprocal transaction group，核原具名人/操作/版本/来源绑定。客户端重密封 hash 或 `consumed=True` 不能代替它。本段没有 writer、confirm、commit 或审批生成路径。

## 4. 实时宿主协议

```text
load_verification_facts(s,ctx,product_id,review_ref,
                       *,operations=None,reader=None,clock=真实aware服务器钟)
  -> FactReadOutcome{structure,host_proofs,missing}

FactReader.read(s,ctx,pid,review_ref,at) -> actual FactMaterial|null
FactReader.refresh(s,ctx,pid,previous,at) -> independent actual FactMaterial|null
FactReader.registry/sources/participants/applicability/observation/provenance/authority
  (s,ctx,pid,material,operations,at) -> opaque HostFactProof|null
FactReader.refresh_proofs(s,ctx,pid,material,operations,proofs,at)
  -> independently refreshed tuple[HostFactProof,...]|null
```

真实 `HostFactProof` 是服务端对象，必须绑定**同一个 reader 实例、Session 对象、Transaction 对象、SAVEPOINT 对象**、调用者、完整 Scope、完整 material 摘要、gate 种类、nature、完整 owner 指纹、实际检查钟和固定期限。JSON、bool、hash 字典不符合这个接口，也不能凭现有结构 positive 自行组装。

wrapper 自身强制 `sqlalchemy.orm.Session` 与真实 `SessionTransaction` 类型、`Session.is_active`、活动主事务、主事务归属/无 parent，以及所有活动 nested 事务的同 Session parent 链。不是仅 duck-type/non-null identity。关闭、failed-flush partial rollback、失活 nested、换主事务/换 SAVEPOINT 均不接受；无 SAVEPOINT 的实际活动 UOW 仍可读。检查只读内存状态，不开事务/引擎/连接。

七类 callback 的事实责任分别为：

| Gate | 真实宿主必须核对 |
|---|---|
| registry | 当前实际 operation/tier/event/subject Registry；Rule 内部出版许可与 issuer/version/epoch |
| sources | 原始 bytes/hash/size/位置、完整 SourceACL、安全/lifecycle/Current/withdrawal/ABA、最窄受众与完整≤20 union |
| participants | 从原失败测试、根因、遏制、完成、新执行/测量、观察 owner 收齐实际人及来源，不能信客户端名单 |
| applicability | 当前具名专业/规则/政策、真实 actual configuration/item/method/criterion 和逐 action owner 履行依据 |
| observation | 原件实际区间、确定群体/样件/批次、真实采样/记录完整性、发生/接收钟与 issuer/nature |
| provenance | 实际保存 candidate/Rule/Observation/Review 及 Current、共同消费 UUID/Invocation/原子 Receipt/Audit/Outbox/同 UOW 证明 |
| authority | 当前读者权限与具名资格、原签发人当前身份/Grant/专业事实、相关 policy/issuer/runtime epochs 与全部负向事实 |

流程固定为初读→七个 owner→独立 refresh→七个 owner→**全部 owner IO 后 `refresh_proofs`**→精确 UOW 再核→真正 post-IO clock/TTL。两轮材料与完整 gate 指纹必须一致；末端 callback 独立读齐全部当前闭包，任何后一个 owner IO 撤销前一个证明都不能遗漏。它自己的 owner IO 完成后也须重新核最终 registry/runtime/current/source/资格闭包。不能只是重新密封已看过的 proof。

每个 callback 返回后均检查 UOW；末端所有 IO 后再次检查原 Transaction/SAVEPOINT，再取真实钟核期限。原专业自然到期和 retained 历史执行的区分只沿既有窄 owner 合同，不删除固定 Start/计划/占用/使用/源/issuer epochs。Rule 新有效期或未来资格激活边界须在 owner valid_until/指纹中覆盖；不得动态续期。

无任一 callback、实际 Registry、真实 Session/UOW 或实际 owner 材料即 missing；缺 post-all-owner 刷新同样 missing。无跨请求、inputs/preview/apply/replay 缓存，无 `Session.info` 历史 positive。真实私有 Issue 只由原 owner 可读，不代用他人 Context。

## 5. 后续接线前仍缺的事实

当前只提供纯材料/协议。Root 后续必须另冻 companion models/Current/生命周期/RLS、可信 Rule 出版宿主、Observation T1/Review T2 的实际共同操作和持久原子组，以及真正的 source/participant/applicability/observation/provenance/authority owners。现有 `VerificationEvidence` 只能由这些实际 owner 在完整事实/政策成立后装配，effectiveness/close 继续两次不同真实 T2。此交付不声明 G3、人工 Exit、生产资格或业务接通。

纯用例复用 synthetic anchor 和 paired DTO 构造明确假的 source/authority/owner 证明，但事务夹具使用**实际无 bind/无 engine/无连接**的 SQLAlchemy Session 与活动 Transaction/SAVEPOINT。额外无 bind flush 故障仅产生 SQLAlchemy `UnboundExecutionError`，没有数据库或 SQL 执行，用于核真实 partial rollback 状态。检查错配/缺项/到期/撤销/最后 IO/事务类型/活动性/SAVEPOINT 边界。没有数据库、HTTP、真实原件读取或公共测试；不修改 server/web，也不对主线当前候选作全树稳定性声明。旧 77 项初版证据保留，窄修后的新检查单独绑定 v2 文件。
