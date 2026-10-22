# 第十四波结果返回合同草稿

**状态：设计草稿，未开始第十四波实施或验收。** 本文只提出下一闭环的接口、复用和并行边界，不更新唯一清单，不将目录、DTO、独立纯规则或历史测试视为新闭环已交付。第十三波实际开测、资源/样件原子占用及其冻结候选联合检查仍由主线完成；只有该依赖被主线确认可用后，才能接入真实持久 Run。合成资料和本地可信签发只证明实现路径，不授予真实专业资格、生产启用或人工 Exit。

依据：[完整目标架构](2026-10-02-pdos-complete-target-architecture-v1.md)02.7、03.3/5/11/12、04.7、05.3、07.6、08.3/4及附录 A/B；[执行方案 §12](2026-10-02-pdos-next-execution-plan.md#12-已接收范围到实际开测的后续合同)；[验证核接入合同](../reports/evidence/pdos-next-verification-20261002/integration.md)。本文的新增对象/函数名均为建议，须先冻结合同再分派，不构成执行指令。

## 1. 用户结果与不变量

闭环为：选择真实 `running` Run → 选择固定版本原报告及明确原位置 → 查看服务器提取的原值、元数据和缺项 → 一次 T1 导入部分/最终结果 → 查看确定性判定与精确覆盖 → 有权品质本人分别办理 T2 专业复核和处置。页面同时展示原报告、样件标签/模穴、实际配置、固定方法/判据、执行设备与校准、发生/接收时钟和未完成责任。

- `measurement`、`computed_result`、`professional_conclusion`、后续 `ai_hypothesis` 分开保存。专业文字不能覆盖读数或确定性结果；数值通过不等于整体请求合格、工程/制造放行、客户承认或可外发。
- Run 的 `running → results_pending → reviewed → disposed` 是执行状态；`pending/pass/fail/indeterminate/invalid` 是独立结果维度。现核不会自动产生 `invalid`，不得从界面文字或处置文本暗改成该值。
- 固定 Run 的 accepted sample/item pairs、样件/实际配置版本、模穴、方法/判据、设备/环境/执行者、真实开始及既有占用/消费证明全部继承。不得补成 sample×item 笛卡尔积，不以计划数量生成测量。
- 原值字符串逐字保留，空缺保持 null/缺项；不裁剪成另一个原值、不补零、不做隐式单位或工况换算。源中缺观测时间、方法或设备引用，可以明确缺失并计算 `indeterminate`；不能把当前 Run 的理想值反填为原报告实测元数据。
- 中途固件、实际配置、方法或样件身份改变，当前 v1 阻断继续沿原 Run 解释结果，保留已有事实；后续须显式分段或新请求/新 Run。本文不宣称 AT-09 分段能力已经实现。
- 保存部分结果不会释放资源、恢复已消耗样件或重新预约。破坏性样件只允许其原 Run 返回既有测量，永远不能以结果返回、处置或时间经过授予另一个 Run 重用。

## 2. 可原样复用与必须新增的接缝

下表是对当前新工程已交付代码的定向复用，不导入旧 `server/app`、旧表或旧状态。

| 当前具体实现 | 可直接复用 | 接线限制/新增责任 |
|---|---|---|
| `pdos-next/server/pdos_next/schemas/verification/contracts.py` 的 `Measurement/ResultsSubmit/ComputedResult/ProfessionalConclusion/RunReview/RunDisposition/TestRun/EventTime/TimeFact` | 原值、缺项、原 IANA 时区、部分责任、独立专业结论 DTO | 新 HTTP wrapper 加 Request/Run CAS、来源读集、capture/projection 引用、T1 `confirmation_token` / T2 `approval_token`；不让客户端提交 Authority、结果或资格 |
| `domain/verification/rules.py::compute_results` | Decimal 数值判定、精确 pair、缺值/不匹配保留未知、部分先失败与未最终整体通过 | 直接调用原函数，不复制算法；固定规则版本/hash和全部判据出处，单独区分部分与最终计算 |
| 同文件 `pairs/check_coverage/accepted_coverage/coverage_gaps/document_gaps` | 数量/模穴/资料与实际覆盖规则 | 完整请求聚合读取真实当前 Run 集合；局部 final pass 不替代请求未接收/缺量/缺模穴 |
| `domain/verification/handlers.py::_run_action/_request_complete/_run` | 部分追加、最终结束、专业复核/处置顺序、重验已有测量和固定方法/样件 | 通过同事务端口调用 `VerificationHandler`；不另开 begin/确认/回执，不伪造样件或 Authority |
| `domain/verification_front/adapters.py::FixedBuilds/TransactionCommands/authority_dto`、`verification_launch/adapters.py` | 当前服务器权限评估到核、共同事务 record 的方式 | 当前 `BoundEvidence.verify_measurement` 明确拒绝；必须新增真实值/位置核验器。`LaunchCommands.confirm` 仅允许当前三开测动作，不可直接拿来绕过结果 T1/T2 |
| `domain/verification_launch/models.py` 的 `VerificationRunIdentity/VerificationRunVersion/VerificationRunCurrent` | 同一 Run 身份、不可变版本、Current、固定计划/来源/历史 | 当前 RunVersion CHECK 只接受 planned/running、rev1/2、plan/start；主线须在新的真实 head 扩此同一链，不另建第二个 Run 状态指针、不修改已应用历史迁移 |
| `domain/test_resources` 的共享 `ResourceOccupancy/TestResourceReservation/SampleRunUsage` | 精确原 Run 占用和消费证明、固定 binding、同租户共享资源身份 | 现 `recheck_running` 同时评估当前执行窗口，不能未经调整充当窗口结束后的历史结果接收端口；新增只读证明接口，禁止重复 stage/reserve |
| `originals.py::require_original/read_registered_bytes`、`evidence_processing/types.py::SourceLocation/ParseResult`、`object_storage`、`security_runtime` | 不可变原件/派生文本分离、line/page/cell 定位、扫描/访问隔离、受控解析 | 原件 bytes 必须走现有 ACL、扫描/访问门禁。页或单元格定位不等于已经证明原值；PDF `PARTIAL_TEXT`、OCR 未接或歧义保持未知 |
| 共同 `service.preview_command/consume_material_confirmation/execute`、`professional_authority.assess/recheck_snapshot`、Receipt/Audit/Outbox | 当前权限先重放、T1/T2 分层、稳定意图、同事务回执、专业 epoch | 新专业操作需主线明确注册；Product writer 与 AI Qualification 均不替代品质/测试专业资格，AI 不执行 T2 |

现核每个 `(run,sample,item)` 只有一条原测量，不覆盖已记录 pair；重复采样、纠正、重复试验需单独版本化合同。首波不得以数据库 UPDATE 或换 measurement UUID 绕过。定性判据保留原文和专业结论，确定性数值核保持 `indeterminate`，不新增 AI 判定器。

## 3. 原值与原报告核验合同（建议）

新增 `domain/measurement_evidence/`，仅负责来源提取/核验与 typed 定位，不拥有 Run 状态、资源、确认或业务回执。公开接口建议：

```python
extract_observations(report_binding, parsed_source, mapping) -> ObservationCandidates
verify_measurement(source_bundle, measurement, fixed_run) -> VerifiedObservation
```

`report_binding` 由服务器绑定 tenant/product/project、当前可读原件/Artifact 固定版本/hash、原件安全 epoch、parser 版本与定位映射。`mapping` 只选择原位置及已存在 Run 的 sample/item，不能携带 current/approved、伪造 hash/设备资格或直接把拟填数值当原件值。`VerifiedObservation` 保存原字符/值种类、全部元数据的原位置、映射依据、实际来源性质和缺项；其精确引用必须能回到原报告，不仅是某个恰好可读 Artifact UUID。

最小可验收入口优先有界原生结构化 UTF-8 报告（例如固定 schema 的 JSONL），显式包含 sample/item 对应、原值字符串、单位/工况/设备原标签/方法与来源、观测时间及 IANA 时区；重复 JSON key、多个候选、非法时区、越 Run 范围拒绝，不让 LLM提取成为计量事实。缺失字段可以原样留空。字段/设备/方法外部标识如未能映射到固定合法引用，保留标签与缺项，而非从 Run 回填成匹配引用。

PDF/XLSX 仍复用既有原件与隔离解析；新增映射必须逐字段校验原位置和原值。PDF 页文本的模糊命中不能证明独立测量；XLSX 数值若经过浮点转写、公式计算缓存不可信或原始字面值不可保真，应明确不支持/待核对，不能声称得到原始读数。OCR、图片读数、宏执行、任意脚本解析和真实仪器连接不在首版已验收范围，缺端口保留等待。

建议 `prepare_capture(s,ctx,product_id,request_id,run_id,input,...)` 只保存可恢复、具名私有的映射候选：capture_key 与完整固定材料幂等绑定，id/revision、Run 基准版/hash、原件/报告来源、提取结果、读集/source_basis、expiry。它不推进 Run、不产生正式测量、不授扫描 clean，不额外造一次领域确认。已有报告解析在事务外完成；读 bytes 时按当前原件门禁，保存候选及执行导入前再次核对固定来源。事务内不等待解析容器、LLM、ERP或仪器网络。

## 4. 持久对象与命令/API 草案

复用同一 `VerificationRunVersion/Current` 与 `FormalVerificationRequest/Current`；新版本保存核的 `Mutation`，旧 planned/running、请求准备/接收、样件、原 Start/占用/消费全保留。建议新增对象如下，最终 DDL 数量和字段由主线冻结：

| 对象 | 最少固定内容与约束 |
|---|---|
| `MeasurementImportCapture` | scope/owner/visibility、capture_key+input_digest、Run version/hash、报告/映射候选、来源与安全 epoch、created/expiry、已应用引用；可恢复草稿不当 Measurement |
| `MeasurementRecord` | scoped Run identity、首次写入的 RunVersion、sample id/rev/actual configuration/item、`Measurement` 原值/元数据、原报告/每字段定位、发生时钟/服务器接收时钟、verified basis/hash；immutable；unique `(tenant,run,sample,item)` 及测量身份 |
| `TestResultProjection`（canonical compute） | 固定 RunVersion/hash、全部 Measurement identity/hash、criteria/method ref、规则版本、final 模式、每 pair/Run 判定和 reasons、basis digest；相同完整输入一个结果，不改变原始数据/时钟/专业结论 |
| `TestResultActionFact` | import/review/disposition 的不可变输入、前后 Request/Run version、专业 authority snapshot、事件/source/readset、稳定意图、共同 Receipt 引用；具名审阅/处置绑定判定和全部证据摘要 |

共享 Row/RLS、同 scope 复合 FK、不可变触发器与连续版本/CAS 指针继承；Current 不允许退回、换 Run 或换受众。新增对象及保存于 JSON 的全部精确原件引用须纳入生命周期 reference fence，未知登记/引用仍受保护。

| 操作 / 等级 | 草案 payload 与结果 |
|---|---|
| `test.results.import` / T1 | `request_id/expected_request_revision/run_id/expected_run_revision/capture_id/expected_capture_revision/final/at/actual_end/incomplete_reason/next_owner_id/sources/reason/confirmation_token`。服务器从 capture 生成 `ResultsSubmit`，不接受客户端 computed_result。一次确认包括本批精确 pairs、保留原值/缺项、新增/已存范围、部分责任或真实结束与影响；共同事务写 Measurement、核判定、Request/Run 新版及 Receipt/Audit/Outbox |
| `test.result.compute` / canonical T0 | `run_id/expected_run_revision/expected_basis_sha256/reason`；固定规则直接调用 `compute_results`，复核当前 source/权限后返回或保存固定投影。导入命令内现有自动计算复用同函数；独立操作不另要 T1、不改 final/专业状态，也不因此授 AI 资格 |
| `test.run.review` / T2 辅助 | 固定 Request/Run version、结果投影/basis 摘要、`text/at/sources/reason/approval_token`；具名品质复核，核 `RunReview` 保存独立专业结论。结果、原件、范围变更后旧批准失效 |
| `test.disposition.decide` / canonical T2 | 同样固定已 reviewed 版本、专业结论与判定证据摘要；`text/at/sources/reason/approval_token`。核 `RunDisposition` 只记录该 Run 的具名处置，不批准工程/制造/外发，不清消费或恢复执行许可 |

首版专业无效/复测/hold 等意见可准确保存在独立具名结论；若增加 typed disposition enum 或使 evidence_invalid 影响后续有效性，须先明确规则和版本化适用范围，不能把自由文字转成自动 `run.result=invalid` 或放行。失败 Issue/CAPA 自动建单留下一明确闭环；本波可以提供有稳定 causation 的失败事实，不伪造空 Issue 或声称 AT-23 完成。

建议 API：`POST /v1/products/{id}/test-result-captures` 准备候选；`POST .../test-results/inputs` 只读取得完整服务器读集与缺项；正式操作继续 `/v1/commands/preview` 与 `/v1/commands`；`GET .../test-results?build_id=...&run_id=...` 返回 `runs/captures/measurements/projections/actions/current_by_run/capabilities`。读取历史允许显示 stale/historical，私有派生内容全隐藏；执行按当前身份、原件/source、资格与完整读集复核。

主线 wrapper 沿 `validate/semantic/preview_view/apply`。版本 CAS 放新写的 preview/apply；合法旧意图回放先复核当前权限与来源，返回原 Receipt，不回退 pointer、不再调用资源 stage。实质预览中的接收/保存时钟仅显示 server_on_save，不能用变化的 now 或动态 expiry 参与业务确认摘要。

## 5. 部分覆盖、时钟及历史执行证明

每次部分返回只追加本批新 pair，Run 继续 `running`，保存 returned/pending coverage、原因/下一责任人及该范围返回时钟。责任人须是当前可承担责任的真实人员，不因 UUID 提名授予权限；不自动建工作或承诺。已有测量不得重导替换。最终提交必须明确全部 Run pairs 均有记录（可为真实缺项/未知），并提供真实 `actual_end`；若之前部分记录已齐，可空 measurements 只确认最终结束/返回。

`actual_start ≤ observed_at ≤ actual_end ≤ result_returned_at`（有相应时钟才作比较）；服务器保存 aware UTC，同时保留原 IANA 时区，`received_at` 只取保存时点。最终结束、返回、专业复核、处置依次核来源真实原值；报告上传/收到时刻不替代测量或结束时刻。暂定/承诺不补 Actual。最终 Run 的局部 pass 或 disposed 不满足请求缺数量/模穴、未接受 offered 范围时，Request 保持未完成并显示缺项。

**必须先补历史证明端口。** 当前 `test_resources.recheck_running` 内的资源 `evaluate` 会在执行窗口结束后阻断，不能把正常迟到报告都当再次执行请求。建议增加 `inspect_retained_execution(s,ctx,product_id,fixed_run,*,at,write=False)`：只读核 exact Run/计划/实际 Start/资源预约/样件使用/intent、原始 scope/设备版本/消费归属和当前 ACL、来源安全、撤回与失效事实，不 reserve、不改 occupancy epoch、不重消耗、不从已过窗口推可再次执行。当前办理人的专业资格仍须有效；历史保存证据和“当前可继续执行”分开展示。

实际发生期间的设备/资格与配置依据须固定，不能拿今天的新资源版本替换历史；如果真实撤回/配置差异等使证据适用性无法核对，报告原件和候选仍可保留，但正式导入/有效判定/复核按明确规则阻断或待重核，不自动从当前未知恢复有效。窗口结束本身不代表原测量虚假，也不恢复消耗；缺历史证明则 `INTEGRATION_REQUIRED`，不设置乐观 stub。

共享制造/测试 asset 的 v1 限制继续可见：其他 owner 新占用即使容量够或窗口不重叠，也可能改变原固定 epoch/fingerprint，导致原执行需要重核；已有消费归属不得因避开该守卫而被忽略。后续 release/重授权/resume 不由结果处置顺带实现。资源核的真能力和本地测试性质分栏，不能因一次合成通过声称生产资格。

## 6. 三路独占并行建议

主线先冻结 measurement locator/verified observation、capture DTO、同一 RunVersion append 与历史执行证明合同，再真正并行；没有合同的共享模型不能三方同时改。

| 工作包（建议归属，尚未分派） | 独占文件 | 输出 / 前置 |
|---|---|---|
| A 原报告/原值适配 | 新 `server/pdos_next/domain/measurement_evidence/**`、`server/tests/measurement_evidence/**` | 有界来源格式/定位提取、完整原值核对、缺项与失败分类、`EvidencePort.verify_measurement` 实现。只读原件门禁由主线传入；先给 frozen DTO/函数，B/C 不等完整实现 |
| B 结果领域接线 | 新 `server/pdos_next/domain/verification_results/**`、`server/tests/verification_results/**` | captures/measurements/projection/action 持久服务与核 adapter、部分/最终/T2 事务测试；复用 A verifier，使用同一 Request/Run Current 与既有占用历史证明，不另造确认/回执 |
| C 用户办理 | 新 `web/src/components/builds/build-results.tsx`、`web/src/lib/build-results-view.ts` 及对应辅助测试 | 按 frozen GET/preview DTO 展示原件位置、pair/实际配置、缺项、局部/整体判定；一次 T1、分别具名 T2，精确请求重试/未知回执恢复、双主题/320px；不猜资格或发生时钟 |

主线独占公共 PAYLOADS/等级/专业操作注册、事件/API/BFF/页面挂载、已有 RunVersion/FK/CHECK/Current 触发器与真实 head 单调迁移、原件生命周期引用 catalog、历史执行证明接线、公共验证和唯一清单。独立包及 `verification/resource_readiness` 核冻结复用；若确需扩核，先说明规则缺口并重新确定唯一归属，不能悄然覆盖复用结论。

性能先按影响验证：复用同一显式领域 phase 内已经核验的来源/样件证明，绑定 Session/transaction/ctx/full scope/固定版本及 expiry/issuer/safety epoch；每次 hit 仍查当前权限、Current 和时效。不得直接把 GET-only ReadContext 放进命令，不跨 inputs/preview/execute 共享资格，不因性能删掉原件/hash/原值核对。正式消费早已完成，结果路径不再承担新资源分配开销；同时准确记录 SQL/锁等待和真实时钟等待，不能把全部时长称为计算成本。

## 7. 依赖关口与最小验收

DoR：主线确认第十三波同候选实际 running Run/完整资源与样件归属闭环；冻结同一版本链的扩展方式；可信 measurement verifier 和历史执行证明无 stub；当前品质/测试操作专业矩阵、T2 binding、原件读取与引用保护已经接通。缺真实仪器/工厂材料只阻塞真实资格出口，人工本地合成可继续建设；不能据此放宽原值/范围守卫。

最小验收选集由主线统一执行，独立包只执行获授权纯检查，不自行连接或清理数据库：

1. 正向真实 API/页面：已有 running Run 导入一批真实来源原值 → 部分结果/未完责任 → 最终结束与判定 → 具名 review → disposition；刷新回到同一 Run/请求历史和共同回执。合成数据明确标明，原样件/计划/实际配置/占用/消费前后保留。
2. 原值反例：同 hash 的错误 locator/错误数值/错误单位/工况/设备/方法、越 sample/item、不同实际配置/模穴、重复 pair/id、隐式换算、NaN/非有限值、缺日期/时区、未核对公式/歧义 PDF均按拒绝或明确未知办理；原字符串不变，未知不变 pass。
3. 部分范围：先失败有效只对所选 pair；局部 Run final pass 不让缺量/缺模穴/未接收请求整体 reported/disposed；最终空测量仅允许先前已全 Run 覆盖。重复采样/纠正不以换 id 偷写。
4. 原子性与重放：同意图不同 key 只一套 Measurement/Run/Request/action/Receipt；同 key 改载荷冲突；双并发提交 CAS、T1/T2 消费、Audit/Outbox末端失败全回滚；结果重放与迟到返回不增资源占用、sample consumption 或 epoch。
5. 安全与适用性：当前操作者/原审核者资格撤回→恢复 ABA、issuer 关闭、source/原件撤回或隔离、private 受众、过期预览、T2内容/结果basis漂移、Agent 零直接写/T2拒绝；历史内容和专业决定可按ACL查看，当前能力明确阻断。
6. 时钟与历史：aware UTC/IANA 保存，测量/结束/返回/审核/处置顺序；真实执行窗口结束后原证明仍能核对的迟到报告；失效证明保持待核，不重开测。破坏性原 Run 结果可以读取已有消费证明，另 Run 永不重用。
7. 集中出口：新真实 head up/down/up/schema、原件 reference fence/RLS/Agent 权限、同候选后端/前端选择集与亮暗/窄宽/键盘/错误恢复实际页面。失败、test-only 修正和候选 hash 差异保留；历史独立通过不能拼成新联合全通过。

适用 AT 子范围：AT-07/08 固定实际配置，AT-11 消费归属，AT-15 部分返回，AT-16 分母与范围，AT-25 专业判断/假设分离，AT-27 失效/期限，以及适用安全/恢复场景。AT-09 分段、AT-23 失败建单、完整 Issue/CAPA/变更复验、生产仪器资格、自动资源释放、正式放行/外发和人工 Exit 仍是明确后续，不在本文登记完成。

## 8. 草稿交付说明

本文来自定向源码/合同审阅；没有运行数据库、公共测试、浏览器、迁移或第十四波实现，也未改变第十三波生产/测试候选。文件路径/接口建议用于主线后续冻结合同和划定独占归属，需以实际实现与同候选证据验收。
