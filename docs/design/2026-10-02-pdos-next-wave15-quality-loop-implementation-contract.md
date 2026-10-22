# 第十五波：确定失败、Issue/CAPA 与双线变更施工合同

**2026-10-08：本施工合同已被[完整目标架构 v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md)整体取代，仅作只读历史对照。下方旧“当前/下一步/冻结”不再作为施工指令。** 范围根、一致性、期限与数量限制按 v1.1 和已批准的 [S0 实施计划](2026-10-08-pdos-next-s0-refactoring-plan.md)执行；[旧条款对照与 B0 基线](../reports/evidence/pdos-next-s0-20261008/baseline/baseline.md)保留取代依据。原证据、失败与当时范围不改写。

状态：2026-10-02 冻结独立施工接口。Wave14 的实际结果闭环与429项影响验证已收口，其600份历史候选保留；本波独占目录已交付，当前开始公共接线。当前完成状态只见唯一清单。

[实施草案](2026-10-02-pdos-next-wave15-quality-loop-implementation-contract-draft.md)、[复用审阅](../reports/evidence/pdos-next-wave14-20261002/quality-reuse-review.md)与[共同适配审查](../reports/evidence/pdos-next-wave14-20261002/quality-common-adapter-review.md)中的范围、原对象所有权、失败准入、共同事务、来源/资格刷新、UNKNOWN 与人工出口边界保留。以下决定覆盖草案待定项。

## 可用业务切片

确定失败 → 去重原 Issue 或建单 → 具名分诊/实际遏制 → CAPA 假设草稿 → 固定 Issue/CAPA 的 ChangeRequest → 真实工程/制造已知路径与 UNKNOWN → 既有所有者下一轮准备入口。当前工况差异 Run 保持 indeterminate，不产生 FailureRef 或失败 Issue；联验另用有实际合成原件和开测证明的确定失败。旧 Run、原值、占用、消费、专业决定不修改。

首版注册 quality.issue.create(T0)、quality.issue.merge(T1)、quality.issue.triage(T1)、quality.issue.containment.record(T1)、quality.capa.draft(T0)、change.request.create(T0)、change.impact.compute(T0)。分诊和遏制是具名人动作，T0 也必须有实际当前专业资格。其他根因/完成/有效性/关闭、Order 批准/实施/生效能力保持关闭，不提供假的完整端口返回。

## 接口与权威事实

- 共同 Command、Product 水位、一次证明、Receipt/Audit/Outbox 与调用者 Session 保持。新 Issue/Change 版本为实际回执 subject；family 分别为 quality_issue、change_request，CAPA 随 Issue 版本保存。
- create 使用原 IssueCreate 四字段加 visibility，领域目标为服务器核验的 Run、前版 0；其他品质载荷为 issue_id、expected_issue_revision、旧专用 DTO 字段与共同 confirmation_token。精确 SourceRef 的原文由服务器查验并纳入读集，客户端不能提交风险、资格、性质或图完整性。
- A 先冻结 schemas.py 的真实请求/阅读 DTO；B/C 依据这份字段实现。FixedQualityResult 绑定事件归属的精确 RunVersion、Measurement、Projection/basis、VerifiedRun、原报告/原执行证明、完整读集及 currentness。未接可信原件/端口明确 INTEGRATION_REQUIRED。
- 稳定失败跨 event/key/title 复用原单；同事件多失败分别保存 EventFailureLink。精确相同意图重放由共同入口处理；新事件对同失败的映射须同事务保存后返回原创建回执，不重复发 issue.created。原失败漂移显式 RECHECK_REQUIRED，首版不借 create 隐式追加重核版本。
- 风险及独立复验政策使用有完整 scope、版本、发布来源、期限/撤回 epoch 与源摘要的可信 PolicyFact/Current。无政策时分诊/CAPA 阻断，不能默认 low。生产可信发布接入未完成；本地演练可由主线在核对独立目标后显式启用 opaque synthetic policy issuer，导入逐字有来源的风险/独立性政策，永不授 real 性质或生产资格。无公共自授政策 endpoint，AI 无导入权。
- change.request.create 不接受任意新 change_id。服务器由完整 scope、当前具名办理人、受众及专用语义内容确定稳定逻辑 ID，领域前版 0；换客户端 key/UUID 不绕过去重。固定 roots/references 含精确 key，CAPA 引用含所属 Issue 版本及 CAPA key。
- change.impact.compute 绑定 change_id、expected_change_revision、服务器已保存 graph capture Ref 及有来源的 hypotheses。图捕获输入只有 capture_key、change_id、expected_change_revision、reason；roots 从固定 Change 取得。固定图有效期最多 10 分钟，受源/权限/资格到期进一步限制，原 exact key 可回读原候选但不能延长有效期。当前 policy/runtime/source 漂移重新阻断，不能缓存肯定资格。
- GraphSnapshot 只读取真实所有者的固定版本/字段/来源边。缺正式 Tooling/Fixture/ControlPlan/PilotRun、库存/WIP/生产切换/培训等八 facet 保持 UNKNOWN；首版不宣布任何整域 complete，不把读取子图无更多节点称全业务覆盖。
- 完整来源并集保留两类实际出处：已有 `evidence.artifact.register` 的原生不可变文本，核真实登记回执、精确版本/办理人与 run 来源、逐字摘要及当前权限/撤回；上传派生 Artifact，核实际 Original、扫描安全、原字节/摘要及 epoch。来源 basis 明示 `registered_native_text` 与 `uploaded_original`，不能把原生文本说成已上传文件或仪器报告。没有任一真实来源证明时明确阻断；原测量仍必须通过实际原报告字节桥，不能用登记文本代替。这是对现有原生录入能力的复用，禁止事后补改 Artifact.original_id。
- 下一轮为只读 FollowupNeed + 精确 Issue/CAPA/Change basis 和既有所有者入口；本波不新增持久的已创建输出或辅助 T1 回链。真实新对象及实际实施输出后续独立登记，空引用保持未创建。

## 独占并行与汇合

A：domain/quality_execution/、tests/quality_execution/，含新模型/DTO、稳定失败/事件/别名、可信政策与共同品质适配。B：domain/change_execution/、tests/change_execution/，含新模型/DTO、真实固定图捕获与 ChangeRequest/Impact 适配。C：build-quality-loop.tsx、build-quality-loop-view.ts 及同名测试，复用旧只读组件和共同命令恢复，明确选择 Run/测量/Issue/Change，未知与失败分开。

三路仅在新文件内施工，先交 typed 模型/DTO 再完成动作；只允许独占纯检查和静态检查，不运行 DB/HTTP/公共构建/浏览器或改旧纯核。主线独占只读结果桥、政策宿主启用、公共后端注册/专业角色/事件、models import、真实 head 单调迁移/RLS/不可变约束、原件保护、API/Workspace、公共验证及清单。Wave14收口后，主线另明确委派C独占BFF route.ts与纯测试，在既有公共合同内接5个入口和7个命令；不启动服务/构建/浏览器或数据库。Wave14 通过后才修改公共接线；若其验证暴露缺陷，先修复受影响候选再继续汇合。

验收范围沿草案 §8：确定失败与未知分路、精确事件/多失败映射、同失败一单/别名 CAS、末端全组回滚、private 与当前专业资格/原件撤回、政策来源与 ABA、工程制造已知路径及 UNKNOWN、原请求恢复、历史只读与亮暗窄屏。全部通过仍只代表首版本地闭环，G3、真实整改有效性、生产和人工 Exit 保持未完成。
