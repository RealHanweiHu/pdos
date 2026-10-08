# Wave16 B 接线索引

状态：新独占包冻结候选，尚未公开注册或迁移。仅本包 39 pure passed（0.78s）、Ruff/AST 通过；纯测试使用明确 owner 替身，没有真实 PG/原件整链验证。见 [owner-checks.json](owner-checks.json) 和 [owner-pure.log](owner-pure.log)。Wave15 303路径/公共注册/迁移均未修改。

## 标准命令接线

- payload：`capa_verification.schemas.FollowupLinkPayload`；operation `quality.capa.followup.link` 为 T1，专业矩阵由主线冻结，默认未配置则503。
- handler：`capa_verification.commands` 的 validate/semantic/preview_view/apply/replay_subject_type/replay_subject/inputs。common preview/consume/Receipt/Audit/Outbox 由主线拥有。apply只返回模型，不add/flush/commit，不推进IssueCurrent或创建owner对象。
- `commands.configure_consumed_proof(engine, require_consumed)`；callback `(s,ctx,command,product,payload)->UUID` 须核 exact 已消费共同证明。无callback或非UUID返回503。输入保存 `{**无token semantic,shared_proof:{id,tier:'T1'}}`；subject family `capa_remediation_link`。旧回执重放核当前资格/政策/来源及**保存的authority/policy/source/readset**，撤回恢复epoch或读集漂移不得只因新资格为true而放行；不二次consume。
- 新写才核 Product.expected_revision 和 Issue当前CAS；validate历史exactbasis允许common真正旧回执分支，但不能借历史对象新增写。预览 `received_at=server_on_save`，真实保存时点取Row.created_at。

## 模型与数据库责任

两 append-only 表 `capa_remediation_links` (`RemediationLinkRecord`) 与 `capa_verification_evidence` (`CapaVerificationEvidence`)，revision=1，无Current。Issue FK精确绑定tenant/product/project/logicalIssue/版行/revision；Candidate可关联同scope/CAPA的Link，全部link refs仍需服务逐项核。Link含action、resolved outputs/hash、authority/policy snapshot及完整source/readset；Candidate只允许indeterminate/null专业/独立/观察结论。

主线统一：metadata imports、真实head单调DDL、forced RLS/app权限/Agent0、两表UPDATE/DELETE拒绝、完整生命周期引用保护、共同回执原子guard。Link INSERT需SQL再核basis内真实CAPA/action、与固定Issue身份/用途/受众/性质一致、actual proof UUID→exact T1共同Confirmation、同一次合法Receipt/Audit/Outbox及actor；不能仅以JSON UUID格式CHECK代替真实证明。Candidate没有公开写handler，不能先开放任意candidate INSERT作为有效性证据。

## 只读owner与缺口

公开Python接口及DTO详见 [typed-binding-contract.md](typed-binding-contract.md)。A可调用pure `basis_from_issue` 或 `load_exact_followup_basis`，前者不构成授权；newwrite使用strict `load_followup_basis`。

真实owner读取覆盖固定Definition/BOM/工程/制造配置、Build、Actual/Lot/Sample、Preparation/FormalRequest和Run。Runplanned保持计划无执行proof；已执行调用既有retained端口。候选逐sample/item/actualconfig精确映射，拒绝原失败Run/伪计划测量；已有测量通过既有capture私有委托/真实原件bytes/verify_measurement回读，已有投影复用compute_results和固定规则核对，不复制判定算法。所有原件IO后再核旧失败/source/retained，link新写另刷新policy/professional/有效期。

对象存在仍不能证明措施文本已完成。CAPA专业适用、独立专业复核和真实观察期owner均缺失，明确missing/503；候选applicable/independent/observation=null，result indeterminate，effective/close caps永远false。真实native文本仅经既有登记provenance核来源；不能冒充测量原报告。

GET envelope/output selection options/API/BFF仍由主线与A定义；B当前未自建route/list，以免按UUID猜候选或放宽私有scope。待真实共享事务和owner链PG/HTTP验证后才能宣称可用持久闭环，本候选不算Wave15验收。
