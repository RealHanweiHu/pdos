# Wave17 有效性草案独立实施前审阅

审阅对象：[Wave17 draft](../../../design/2026-10-03-pdos-next-wave17-effectiveness-contract-draft.md)，SHA256 `58d4403518e656032518085f481fe2877289e4f23ac12b03692ff44f772f6c39`。

本审阅只新增此文档；未改草案、源码、唯一清单或当前冻结候选，未执行 DB/HTTP/pytest/构建，未授予真实资格。结论是**可以作为下一波冻结基础，但以下接线关口尚未闭合，不能据草案先开放 effective/close**。

## 原边界一致、可直接复用的部分

- 已读 `pdos-next/contracts/operations.json.items` 共 66 项；`quality.capa.effectiveness.decide` 是 canonical **T2**，事件 `capa.effectiveness_decided`。`quality.issue.close` 不在 66 项中；纯核已有它的 **T2** 与 `issue.closed`，但新公共注册/政策仍需冻结。候选/观察/Review 三个建议辅助名称不自动成为既有公共操作。
- 纯 [`QualityIssueHandler._verification`](../../../../pdos-next/server/pdos_next/domain/quality_issues/handlers.py) 已核根因/全完成状态、观察期、原失败精确覆盖、禁止原 logical Run、nature、独立参与者、effective/ineffective；close 要求原 effective 决定人本人，并复算相同 `read_digest` 与 policy ref。保持“一次有效性 T2、另一次关闭 T2”，不合并按钮、不授 AI T2。
- `FollowupBasis`、固定 Failure/新 Run/sample/item/实际配置映射、原报告 verifier、Projection/rules、retained Start/占用/消费、当前来源及 issuer 刷新可以复用。`CandidateInspect` 的 `applicable/independently_verified/observation_complete=null`、result=indeterminate、两项 capability=false 和旧表 CHECK 应继续保留，不能把原 unknown 候选修改为肯定事实。
- `PolicyPort.verification(authority,evidence_id,issue)` 正是需要接的窄 owner 口；返回当前真实 `VerificationEvidence`，其 id 应是保存的 companion Review/证据身份。不需要另写 CAPA 判定状态机或“effective compute”同义 canonical。

## 冻结前的具体阻断

### 1. 有效性追加来源会使旧 Candidate basis 自失效

现 [`capa_verification.service._basis_material`](../../../../pdos-next/server/pdos_next/domain/capa_verification/service.py) 仅排除 `issue_version_id/issue_revision/basis_sha256`，仍比较 `sources`、完整 `required_source_read_set` 与 `source_basis_sha256`。新 effective 版会新增 Review/规则/当前办理资格来源；即使 actions/root/requirement/failures 没变，其 Current basis 也可能与原候选不同。close 再读该候选会 `RECHECK_REQUIRED`。

草案 §6 已正确指出风险，但还需**具体实现合同**：固定 CAPA 语义锚点与该锚点原来源闭包，另存/核完整当前证据与权限读集。固定锚点至少含 scope/purpose/owner/visibility/nature、全部精确 Failure、CAPA/actions/completions/requirement/root/containment、原材料来源版本及安全 basis。完整当前闭包仍核新增 Review、rule、观察、当前专业/政策及 private；不能为了稳定把所有 source/readset/安全字段从摘要删除。

必须按实际持久 operation、精确前后 Mutation 和已消费 proof/Receipt 辨认合法 effectiveness/close 追加；不能接受客户端“仅版本变化”。旧完成/要求/失败/根因/来源改变仍拒绝。尤其，外层验证新锚点后直接调用旧 `inspect_verification → inspect_candidate → recheck_followup_basis`，以及旧 saved-Link `_link`，仍会再次执行整体比较；**仅包装新 VerificationEvidence 无法修复**。冻结时须列清新 owner 复用哪些固定原件/Run/mapping 检查，或明确最小既有 basis-recheck 接口扩展的授权归属，不能全局改松 Wave16。

必需对照：真实 effective 追加→同一固定证据重新核→本人单独 close 成功；新源撤回/ABA或 actions/requirement/root/参与者变化→close 拒绝且保留 effective 历史。只做“核的 digest 已排除 effectiveness”纯测试不足以覆盖宿主整链。

### 2. 当前私有单不能让独立人靠 ProductGrant 办理

现 Issue/source/owner guard 对 private 要求当前 requester 是系列 owner。纯核则在所有风险下排除原失败执行者、措施/遏制执行者、根因决定者、新测试/测量执行者自证；高/critical 或 independent policy 还要求证据 verifier 是本次决定者本人。

因此当前 Wave15/16 原 actor 私有调查单即使完成、结果 pass，也不能靠 peer product writer/quality role 完成独立性正向验收。草案已禁止扩大受众和克隆失败，应继续保持。最小正向材料须从最初就有真实共享原件/来源与共享 Issue 的独立新失败场景，并给真实独立人当前读取权/专业资格；原私有单保留 blocked。未来若建设具名私有协作 ACL，须另冻权限能力，不能用原 owner 的内部 Context 代独立人读取或决定，也不能复制同一失败成共享单。

### 3. append/proof/SQL 不是直接可用的通用口

[`quality_followup_host.append_issue`](../../../../pdos-next/server/pdos_next/quality_followup_host.py) 目前只允根因/本人完成；host `_module/OP_TIERS` 和同 UOW consumed marker 只覆盖本波三操作。首版 `quality_execution.TransactionCommands.confirm` 亦不支持新的 effectiveness/close。其 CAS/来源 union/一次回执方法可复用，实际函数不能无扩展直接调用。

需 Root 明确冻结：新操作 handler/payload/subject/event/tier、真实 `approval_token` 与 T2 UUID→`Invocation.decision_id`、同 Session consume 后 marker、精确前后 Issue mutation/Current、Review/Observation/Candidate companion 与 Receipt 的原子组。不得用 `accepted=True` 或历史 consumed bool 代替真实本次 T2。预览新增具名结论/History 时钟为 `server_on_save`；旧实际时钟和 observation 源时点保留，不能使 material confirmation 因 now 自漂移。

## 需要单独冻结的 companion 合同

范围以草案的最小四类事实为足，不建议增加第二套 CAPA Current 或新的计算状态机：

| 事实/操作 | 公共合同至少要明确 |
| --- | --- |
| RuleFact + Current，内部可信发布 | exact scope/project/purpose/requirement、接受/观察/独立规则、issuer/version/epoch/nature/期限、原出处/readset；内部 operation/event/Receipt、撤回/CAS、不能公开自授 |
| Candidate T1（拟 `quality.capa.verification.candidate.record`） | 原 null/indeterminate candidate、完整固定 mapping/Link/锚点、保存人及同 UOW proof/Receipt；不取得专业通过 |
| Observation T1（拟 `quality.capa.observation.record`） | 谁记录什么真实范围、实际 observed_from/until/IANA、采样完整性出处与 bytes/来源门禁；事件/subject/版本链。T1不是 observation_complete=true 的授权输入 |
| Verification Review T2（拟 `quality.capa.verification.review`） | 逐 action 履行、方法/判据/配置适用、全部 failure/newRun/report/projection/观察/rule、实际 verifier/完整 executors、unknown/not_applicable/applicable、真实 T2 proof/原签发资格 epoch、当前来源/受众与稳定 evidence digest |
| canonical effectiveness T2 + 辅助 close T2 | 每次具名人/当前精确用途资格、对应 Issue Current CAS、独立 consumed proof/事件/Receipt；close 与 effective 的固定 evidence/policy read_digest 一致 |

新增 helper 的 `domain SourceRef` 若指 companion Review/Observation，必须有精确 row/version/hash/scope/owner/current 原签发资格的 source checker，不能让任意 domain UUID 或普通原文 `SourceRef` existence 解锁旧核 `applicable/current`。

操作名目前只是建议；先冻 payload、角色/AI边界、event/Receipt family、source-readset、安全 epoch、FK/immutable/RLS/Agent 零写/lifecycle 与 deferred atom，才能统一公开导出。当前辅助 JSON 读到 18 项，不能宣称这些新动作已经注册或改变 canonical 66。

## 独立性、实际观察与合成限制

草案要求真实时点在措施完成后、观察覆盖真实截止、未来/无源/不完整保持未知，方向正确。`observation_until` 是要求；计时器触发、T1保存时间、一次短测试 pass 或已经到日期都不是观察完整性。完整 participant 集合必须由旧 Failure/Containment/RootCause/完成与新 Run/报告 owner 获得；不能由 client 删除同名执行者来证明独立。

局部 synthetic profile 只证明明确标记的合成联验，必须 same nature、exact host scope/issuer/epoch/source、fixed validity；真实观察和生产专业资格缺失时相关 positive 仍阻断。调查分类的现成合成 callback 不证明 CAPA action fulfilled、正式 Change 实施或真实产品有效性。新 Run retained 证明旧已发生执行，不为新观察/当前 T2 重新授予许可或重新消耗。

核的 ineffective 条件是至少一个确定 fail；不确定单独不能 ineffective。草案“其余完整适用”要在冻结的 rule/owner 明确含义，勿把纯核描述成已经拒绝所有 fail+indeterminate 组合，也勿为通过验收更改原核规则。

## 最小派工建议与结束判断

A 先交可信 rule/观察/Review 的 typed owner proof 与完整来源/参与者合同；B 在新决定包复用纯核并实现稳定锚点、unknown 路径/实际 T2；C 只用服务器 DTO 显示固定材料、缺项及两次具名决定；Root独占公共注册/proof/append/迁移/生命周期/导出与统一真实验收。稳定锚点/受众正向材料/host T2 三关未闭合前，可并行候选/缺项和负向守卫，不开放 effective/close。

本审阅未发现需要修改 canonical tier 或免除原批准关卡的理由；不建议因本波扩大到正式 ChangeOrder/制造放行/真实外发。现草案可保留，冻结实施合同时把上述三个关口转为具体字段与端口。

## 只读底稿

| 文件 | SHA256 |
| --- | --- |
| `pdos-next/contracts/operations.json` | `9e0e3ae79fa17e0391d4a73af27db92f89cbf7de440978d079e2beee5b4432fb` |
| `pdos-next/contracts/auxiliary-operations.json` | `20e769030cb7927457394c36c17d5202d9e72852d22df94fd7fa65d8c60acf02` |
| `domain/quality_issues/handlers.py` | `bfa0ddd8bf0fd9013b4f99bc46fb9e42d5ce34c560a2f92c3ee810f2640825e4` |
| `domain/quality_issues/ports.py` | `e4c614577b0483c2123e8dcaadaa8f55a53a0fb8d60290152198ed43afe43857` |
| `domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `domain/capa_verification/schemas.py` | `d97373d13d9bcf3a0087ac301885dd649a92537d9d61e7f16fc69d88a0a2745f` |
| `quality_followup_host.py` | `6b67f2d9d20bfbd48d869aa2028ba92d84e85660e7a27d3e4fc8c049035470de` |

代码路径均在 `pdos-next/server/pdos_next/`；只读取文本与标准库 JSON/文件 SHA，不导入执行业务模块。本文件不是新波施工、真实资格或人工 Exit 的通过证据。
