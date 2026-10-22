# Wave17：候选请求与实际 semantic owner（第六段暂存）

本段新增严格请求、结构对照与明确 semantic owner 工厂，**没有公共注册、validate/apply、真实写入 owner、七门禁或资格授予**。不修改第五段 reader 或其他冻结源码，不读取数据库/HTTP、不消费 proof、不生成原锚、Receipt、Current 或时钟。

## 精确合同

- operation：`quality.capa.verification.candidate.record`；T1。
- subject：`capa_verification_candidate`；event：`CapaVerificationCandidateRecorded`。
- Payload class：`candidate_commands.CandidateRecordPayload`，Pydantic extra forbid、frozen；新增操作名在本段不注册。

| 字段 | 规则 |
| --- | --- |
| issue_id | 逻辑 Issue UUID；不是版本行 UUID |
| expected_issue_revision | 现 `quality_execution.schemas.Revision`：strict int ≥1，用于实际 Current CAS |
| capa_id | UUID，须与宿主实际固定绑定一致 |
| remediation_link_refs | tuple[现 FixedRef]，默认空，最多20，id唯一，每个 revision严格等于1 |
| mappings | tuple[现 FailurePairMapping]，默认空，最多10000；(failure_id, Run版行id, sample_id, item_id)唯一，原字段完整保留 |
| sources | tuple[现 capa_verification.schemas.DefinitionReference]，默认空，最多20；完整 artifact_id/revision/line/quote 组合唯一 |
| reason | 现 Text，1..2000；无默认 |
| visibility | private/product，默认private；只表达请求的最大受众，不授读写权限 |
| confirmation_token | 现 Token（20..128）或None，默认None |

`DefinitionReference` 完全复用原 DTO（quote1..4000，line/revision≥1及原解析规范）；没有替换来源类型或新增 quote 规则。不同位置的同一 Artifact 来源可保持多条；本段不排序/合并 sources。冲突 Artifact 版本的真实完整读集仍由宿主核对，不在此猜当前来源。`FailurePairMapping` 仍要求 immutable verification_run 版行及既有 sample/actual configuration/version/item 元数据，nullable measurement/projection 可保持未知；不会补测量、原值或观察时钟。

拒绝 tenant/product/project/actor/owner/purpose/nature、anchor/binding/inspection/hash/source_basis/shared_proof/消费钟和 qualification/applicability/current/pass 等额外自授字段；实际 scope 只能由后续宿主从真实对象绑定。嵌套 DTO 继续沿其已有字段和验证器，不能绕过成通用 JSON。

## semantic

```python
semantic(payload) -> dict
semantic_owner() -> candidate_storage.CandidateSemanticOwner
```

`semantic` **先提取输入模型的原始属性再严格重新 parse `CandidateRecordPayload`**，最后 `model_dump(mode='json', exclude={'confirmation_token'})`。不能先用 Pydantic 序列化后再验：被 `model_construct` 绕过验证的 int 字段 True 会被序列化成1，掩盖 strict Revision 错误。原属性提取只是解析输入，不是 identity JSON semantic 或权限 adapter。它还重新核可变的原 DefinitionReference 子对象，不能因顶层 class/frozen 就接受突变的非法来源。

typed defaults（visibility、空选择及原 OutputRef.key=NULL）、所有原选择顺序、nullable measurement/projection、完整 reason/sources 均进入 material。只移除 token；不 sort、不补服务器 metadata、不删其它字段。沿原 DTO 的输入解析规则，不额外做 source/quote/时间规范化。空 mapping 可保留为未知候选，不构造 Cartesian 覆盖或正结论。token改变不改变 semantic；visibility、reason、位置/内容、映射及选择顺序改变会改变 material digest。

工厂显式把 **此模块**、此严格 Payload class 和实际 `semantic` callback 绑定第五段 reader 的 `CandidateSemanticOwner`，核 operation 精确身份。没有自动配置 engine、公共 handler、PAYLOADS 或写入资格。该真实类可以替代第五段测试协议中 TestOnlyPayload 的占位，但仍不能代替未来真正保存 owner/原子门禁。

## 只对照宿主已核的绑定

```python
check_candidate_request(payload, actual_binding, *, current_issue_revision)
    -> CandidateBinding
```

重新 parse 输入和完整现 CandidateBinding，按以下字段逐值比较：

1. 实际 binding.basis 的逻辑 issue_id/capa_id = 原 payload。
2. remediation_link_refs 与 mappings 完整 JSON 值及原顺序 = 原 payload；不替换 child ref、不取 latest、不补空字段。
3. expected_issue_revision = **宿主实际读取的 Current 严格正整数**。None/bool/字符串/float/≤0 为 `CANDIDATE_CURRENT_REVISION_REQUIRED` 503；不匹配为 `VERSION_CONFLICT` 409。

原 Binding 的 `basis.issue_revision` 是固定 origin 身份；可为9而实际 Current/payload为10，**不强制 origin=Current，不把 Current 当固定失败版**。完整 origin、有限合法谱系、真实 Current scope/epoch/CAS 仍由宿主读取并证明。该纯函数只接受传入 scalar 做对照，不能证明该 scalar 确为数据库 Current。

错误逻辑 Issue/CAPA或选择为 `CANDIDATE_REQUEST_BINDING_MISMATCH` 409；非法宿主绑定为 `CANDIDATE_ACTUAL_BINDING_REQUIRED` 503。来源、reason 的实际出处和 requested max visibility 不在此授权：即使结构相等，宿主仍必须做所有真实 Source ACL/原件、Project/private、专业资格、当前 policy/issuer/参与者/applicability/完整范围、post-all-IO closure/UOW 和确认消费。

**Root冻结的兼容v1受众规则**：候选行继承实际 origin/Basis 系列的 owner_id 和 visibility；writer_id 是独立的本次具名 actor，不能混同 owner。未来公共 writer 必须明确要求请求 visibility == 实际 origin.visibility，不满足返回 `CANDIDATE_AUDIENCE_MISMATCH`；不能将默认 private 请求悄悄保存为 product，也不改变已冻 Basis/reader。共享 origin 表单仍默认 private，只有 host 明确允许且全部所选材料均 product 时，操作者才能显式选择 product；任何私人来源不能进入共享候选。本段纯结构对照函数不执行该来源/受众授权，也不据此增加 allowed/capability。

**新写 CAS 对照只能用于已合法去重之后的新意图**。不能在通用 early validate 中拿新版 Current 拒绝已有成功旧请求回放；同/别 key 回放仍由实际 current gates＋精确成功 Receipt binding 决定，不能靠这个函数重复消费或重写。此段没有实现 replay/确认/保存流程。

## 离线检查与剩余接线

只运行本段 `test_candidate_commands.py --noconftest` 和 owned Ruff/format/内存 AST。对照了越权额外字段、严格 Current整数、Link v1/重复、mapping重复和错failure、完整顺序/NULL/default/hash、可变子对象及绕过构造、原锚9与Current10、实际 semantic owner 对第五段 reader 包装的兼容。reader兼容检查使用无连接实际 SQLAlchemy Session/ORM形状和显式 SELECT 替身；任何 connect 被拒，不能视为PG或原件/专业真实验证。

首轮63节点中62通过/1失败，准确发现 bool序列化掩盖重验的缺陷；原日志保留，修复后单独重验。未来 Root 须注册实际 public strict Payload、受控 sources/CAS writer、真实同Session消费 marker、完整原子组及七 owners，再显式注入本工厂。仅定义 Payload/semantic 不足以注册或开放操作。
