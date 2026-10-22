# Wave17 paired Formal/Run 暂存协议 v1

状态：已在独占 staging 文件实现纯结构核对和宿主协议，尚未挂载真实 owner reader、公共 API 或领域 writer。现有 server/web/480 候选保持冻结。本交付不授当前访问、专业资格、原件安全或 CAPA 有效性；既有完整建设授权和真实 T2/生产/外发/人工出口分别保持。

## 导出接口

```python
verify_paired_material(
    binding: PairBinding, material: PairedMaterial, *, at: datetime
) -> PairInspection  # proof.structural_only 始终 True；missing 为明确缺项

read_paired_formal_output(
    s, ctx, product_id, output_ref: FormalRef, *, at,
    reader: PairedOutputReader | None = None, write=False, clock=server_utc_now
) -> PairedReadOutcome
```

`PairBinding` 由宿主读取真实调查/输出范围及当前 Context 后生成：`scope:Scope`、`build:BuildRef`（包括固定双配置版本）、logical `request_id/run_id`、`purpose`、server `caller_id`、`output_ref:FormalRef(kind='verification_request',id=immutable row UUID,revision)`。客户端 OutputRef 只用于选择，不授范围或读取资格。

`PairedMaterial` 必须提供真实 `request_before/request_after/origin_request`、`run_before|null/run_after`、两个精确 Current 指针、`LaunchFact|ResultAction`、共同 Receipt、唯一 Audit/Outbox、真实原 handler semantic material；结果路径另需固定 Projection 与其实际 projected Run。缺必要事实、Current、原 semantic、回执或 Projection 返回 missing；错配和漂移明确拒绝。不存在自造 fallback 或数据库写入。

`StructuralPairProof` 只表述固定引用、原子关系和原值结构：`binding/current_formal/current_run/origin_formal/fact/fact_kind/receipt_id/command_id/operation/owner_id/run_owner_id/writer_id/meaning/required_source_read_set/material_sha256`。`owner_id` 是 Formal 系列 owner；`run_owner_id` 是实际 Run 系列 owner；`writer_id` 是本次事实实际具名执行者。这三个身份可以不同。`meaning=planned|performed` 仅按已保存 Run 状态区分，不表示方法适用、独立性、观察期或放行。

## 宿主实际读取与类型映射

接口接收只读归一后的材料，不直接访问 ORM。宿主必须同一 caller Session/UOW 定向读取以下真实列与快照，保持原 UUID、版本、作用域、时钟和来源；不能从 logical ID 拼造 ref，不能用 Run 起点代替 Current。

| DTO | 真实存储映射 |
|---|---|
| `FormalRow.ref/previous` | `FormalVerificationRequest.id/revision`、`previous_request_id/previous_revision`；snapshot 为 `request_snapshot`，摘要为 `snapshot_sha256`，domain intent 为 `intent_digest` |
| `FormalRow.authority_actor_id` | 实际保存的 `authority_snapshot.subject_id`；该表没有 writer_id 列。不得用系列 owner 代替当次 actor |
| `RunRow.ref/previous` | `VerificationRunVersion.id/revision`、`previous_run_version_id/previous_revision`；writer_id 与 owner_id 分别读取 |
| `RunRow.origin_request` | `request_version_id/request_revision`；这是 immutable origin，绝不是 Formal Current。固定 plan 来自 `execution_plan/plan_sha256` |
| `LaunchFact.actor_id` | 真实 `VerificationLaunchFact.owner_id`（该事实的本次人）；`request_version_id/request_revision` 为 before，`next_request_version_id/next_request_revision` 为 next，`run_version_id/run_revision` 为固定 Run；`kernel_event/snapshot_sha256/input_snapshot/intent_digest` 原样读取 |
| `ResultAction.actor_id` | `TestResultActionFact.actor_id`；request before/next、run before/next、projection_id、event、input_snapshot 和 intent_digest 原样读取 |
| `ProjectionRow` | `TestResultProjection` 的精确 id/revision、scope/build/request/run、`run_version_id/run_revision/run_sha256`、basis/rules 摘要和 computed_results；投影 Run 可以是审核前的真实 import 版 |
| Receipt | 真实 `Receipt` 的 subject UUID+subject_revision、operation、actor_id/requester_id、visibility、command_id、request_digest、intent_digest、result、created_at；本协议只支持当前具名 human 路径，AI run_id 必须 null |
| Audit/Outbox | 精确 tenant/receipt/actor/op、事件 type、subject UUID+revision、schema_version=1、correlation_id=真实 command_id；投递状态不是重新发出事件的理由 |

所有 row/fact/projection 来源读集聚合去重后最大20，互斥版本或超限拒绝，不截断。内嵌 `SourceRef(kind='artifact')` 和 `DefinitionReference` 也必须包含于完整读集；domain/command 来源的实际 provenance 仍由真实 owner/source 门禁核对。来源安全 epoch、issuer/professional/ACL/retained 证明由独立 HostGate 负责，不能从 DTO 的 hash 或布尔值推导。

## 实际推进矩阵与原值

| operation | Formal | Run | Common Receipt subject |
|---|---|---|---|
| `test.run.plan` | 不推进，固定已接收版 | 新建 planned v1；owner=该创建人 | 新 Run |
| `verification.schedule.promise` | accepted→scheduled，+1 | 不推进 planned | 新 Formal |
| `test.run.start` | scheduled→executing，+1 | planned→running，+1 | 新 Run |
| `test.results.import` | 每次 +1；partial 保持 executing；final 只有实际覆盖完整条件才 reported | 每次 +1；partial running，final results_pending | 新 Run |
| `test.run.review` | 不推进 | results_pending→reviewed，+1 | 新 Run |
| `test.disposition.decide` | 实际完整条件成立才 reported→disposed，+1；否则不推进 | reviewed→disposed，+1 | 新 Run |

这不是通用“双方 +1”。unchanged Formal/Run 必须是同一真实保存行。changed predecessor 必须精确且连续，owner/audience/origin/plan 和原 items、sample-item coverage、实际配置、已保存原值保持。本 v1 oneRun 的 coverage 必须等于 origin 全部真实已接收范围，不接受子集冒充当前合法计划；Current 与 origin 固定调查/交样字段和受众保持。最终返回必须每个 pair 都有明确 observation，null 原值保持 unknown，不由缺行补覆盖。复用现 `compute_results` 纯规则核 deterministic 结果，不给予专业结论资格。

Plan 保持所有 actual/result/conclusion 为空。Start 固定实际执行计划的设备/校准精确引用、executor、environment/conditions；Promise 可以记录未来承诺，但 actual 时钟不得未来。原发生/接收/时区/来源分别保留。Review/Disposition 的 text/source/actor/at 必须与真实原 payload 和具名结论一致；Projection 必须是本次 final return 或其直接具名 Review 前版，不用新专业 text 替换测量依据。原值逐字符保持，`10.0000` 与 `10` 不互换。

每次 partial 必须保持全部旧 readings 与 partial_returns 完整有序前缀，只准确新增一个 return；新项 returned/pending coverage、reason、next_owner 和实际 at 精确匹配原载荷及本次新增 readings。final 只保留旧 partial history，不补造 return。Run 首次 preliminary clock 永不替换，并与此 oneRun Formal 的首次钟一致；Formal actual/final/disposition 也必须配对相应真实 Run 时钟。所有已知 observed_at 必须在真实 Start 与其本次 import event 之间，final 的全部已知观察不得晚于 actual_end；缺 observed_at 仍保留 unknown，不倒填成 Start/window/return 时钟。

## 两套 intent 独立核对

`CommonIntentMaterial` 字段为 `handler/operation/product/payload/named_actor/source_revision/private_owner`。payload 必须是**实际** `verification_launch.semantic` 或 `verification_results.semantic` 对原保存输入的输出，完整闭合且无 confirmation_token/approval_token。本包用真实六类 closed Payload DTO 检查必要字段与固定 before refs；不会把 Run 期望元数据回填为原输入，无法取得原 semantic 则 missing。

Domain intent 按其真实 `{operation,actor,payload}` material 核；common intent 按真实共同 `{operation,product,payload,named_actor,source_revision,private_owner}` material 核。两摘要无等值要求。`source_revision/private_owner` 由宿主按原共同 execute 的实际分支和 payload 类型生成，不从当前 read caller 或 DTO audience 猜测。原 `request_digest` 原样保留；它包含完整原请求序列化且可能包括确认 token，不能从去 token 的 semantic 冒充重算。本包不读取或输出秘密；宿主必须核真实保存 Receipt/RequestKey/confirmation provenance，若要重算原 request digest 需真实原请求材料，绝不补造。

## 独立 opaque HostGate 协议

```python
class PairedOutputReader(Protocol):
    def read(s, ctx, product_id, output_ref, *, at, write=False) -> ServerPairRead | None: ...
    def refresh(s, ctx, product_id, previous, *, at, write=False) -> ServerPairRead | None: ...
    def attest(s, ctx, product_id, read, structure, *, at, write=False) -> HostGateProof | None: ...
```

宿主启动配置持有真实 reader 对象；公开 payload 不能选择或序列化它。`read/refresh` 必须分别读取当前主体/Grant、真实范围、Current、全部源/原件、事实、policy/issuer/runtime、历史实际专业签核及其撤回/epoch ABA。读取实际 bytes 后再独立 fresh；当前调用者权限与原历史 writer provenance 分别处理。`write=True` 只允许宿主在已有 UOW 取必要锁，不调用 writer、commit、consume 或另建事务。

`HostGateProof` 是 opaque dataclass，绑定 reader identity、实际 Session/Transaction/NestedTransaction object identity、server caller/scope、完整结构摘要、checked_at/valid_until。stamps 必须实际执行门禁后生成，kind 为 `acl/sources/professional/original_bytes/semantic/runtime`；performed 还需 `retained`；结果还需 `numerical_rules`。每个 stamp 绑定完整 owner 事实摘要及相关 negative/安全 epoch；没有门禁时不能生成一个字符串 SHA 代替真实核对。original_bytes gate 对上传原件核真实安全读/hash/定位，原生登记文本按真实 Receipt provenance 分开核，不把 native 冒充仪器报告。

wrapper 执行 read→结构核→attest→独立 refresh→结构核→attest，始终同 UOW；两轮完整固定材料与 gate fingerprints/有效期必须相同。HostGate checked_at 必须在本轮实际 attest 时段内，读取期间到期、runtime/issuer/source/Current/资格 ABA、替换事务或不提供独立 refresh 全部拒绝。没有真实 reader 默认 `INTEGRATION_REQUIRED`；结构 positive + gate missing 仍 missing。该能力必须由宿主可信代码提供，不是防恶意宿主的加密授权机制。

公共 adapter 不得把 missing 时附带的内部 structural proof 暴露为已授权业务结果。必须同时有合法 host_gate 且 missing 空才使用结构输出；即使如此，该输出仍不证明 CAPA 方法适用、独立复核、观察事实、有效性或关闭。后续真实 owner 接线与 PG/页面验证由主线完成，本包不另建 Formal/Run/Receipt/Current 或资源/样件占用。

## 独占检查与限制

`test_paired.py` 仅合成 DTO、真实纯规则和 fake UOW/reader，覆盖六操作推进、partial/null、保留原值、Current/origin、owner/writer、缺事实/原 semantic、回执/原子组/来源错配、opaque gate/同事务/到期/ABA。调用使用 `--noconftest`，不加载仓库数据库 fixtures。准确结果及源码 SHA 单独记入 `paired-checks.json`；纯 positive 不表示真实数据库、原件资格或公共功能已验收。
