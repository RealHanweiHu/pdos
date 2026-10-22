# Wave15 演练复用方案：新调查请求到确定失败

这是实施前的只读方案，未执行任何命令、HTTP、数据库或浏览器操作，未读取运行凭据。所列事实来自已保存的公共演练回读与当前源码；它们不证明此刻的权限、扫描、专业资格、资源窗口或实物仍有效。所有材料仍为明确的本地合成演练，真实文件上传不等于真实仪器数据或生产资格。

## 结论与必须先定的边界

可复用原 Product、固定双配置、Build 身份和 Sample A 的实物身份；新 Preparation、正式 Request、实际方法评估、Run、资源事实、事件与报告必须建立独立身份。旧 Run v6 的 `indeterminate`、旧 Request 的 1/3 与 B/C 缺项不能用于建确定失败 Issue，也不修改、关闭、释放或追加消费到旧 Run。

**当前冻结实现不能同时保证“同一 Sample A 新 Run 实际开测”和“旧 Start retained 证明仍肯定有效”。** 新 Run 即使全窗口不重叠，保存新的样件使用会增加同一 `SampleUsageSentinel.epoch`；retained 加载只减去原 Run 自身一次提交的 epoch，其他 Run 的增量仍改变原 `facts_revision`。同一执行人的 person 资源新增占用也有同样的全局资产 epoch 效应。原行、原回执与原消费不被改写，但旧证明的当前读投影可能变为待重核。依据：[sample_usage_checks 与 _load](../../../../pdos-next/server/pdos_next/domain/test_resources/service.py:663)、[epoch 指纹与自身归属](../../../../pdos-next/server/pdos_next/domain/test_resources/service.py:1000)、[retained 完整摘要比较](../../../../pdos-next/server/pdos_next/domain/test_resources/retained.py:21)。

另一个独立限制是新用途：`SampleReadinessCurrent` 按 tenant/product/sample 唯一，没有按 purpose 并存的 Current；ready 只对其精确 purpose 有效。若新调查 purpose 不等于现有 `Verify preparation`，保存新 ready 会推进 A 的当前指针，旧 Run 按旧用途核样件时可能不再 ready。不能把标题中的“内部问题调查”当成已获得新用途许可。依据：[Current 唯一性](../../../../pdos-next/server/pdos_next/domain/sample_handoff/models.py:128)、[当前用途检查](../../../../pdos-next/server/pdos_next/domain/sample_handoff/service.py:718)。

因此演练前主线需明确：保留的是旧不可变历史与占用，还是还要求旧 retained 当前肯定结论。前者可按下述守卫逐步尝试，所有当前能力允许才推进；后者在现有 v1 下没有可保证成功的同 A 路径，须先另行设计用途并存/历史使用证明规则，或选择不同实物与资源身份；本方案不授权修改这些规则。

## 已核对的可复用基线

公共 [Wave13 回读](../pdos-next-wave13-20261002/actual-preview.json)与 [Wave14 最终结果回读](../pdos-next-wave14-20261002/actual-final-results-read.json)记录：

| 对象 | 固定记录 | 可复用程度 |
|---|---|---|
| Product | `b1e23421-6c70-4fc5-a87f-96744baab2e8` | 只使用主线当前已核对的原 actor 与当前授权；旧数据 private，不改受众以便利另一人 |
| Build | `c4bd36e6-b8e6-47cd-8497-2fd8d80aa577` v1 | 原 planned 双配置身份可读复用；开工 `limited_current` 必须现场重新核实，已有实物不补造 executing |
| Sample A | `7c16ba29-4598-4240-941c-40ddc6b8348a` v1，`SYN-W12-R4-A`，cavity A | 固定实物/ActualConfiguration 身份可引用；非破坏性旧使用并不等于当前无冲突或新用途 ready |
| 旧 Request | `8ab2f1ad-716d-404b-8a69-013c2a2015d7`，purpose `Verify preparation` | 历史保留；原 `sample_count=3`、cavities A/B/C、接收仅 A 的缺项不缩改 |
| 旧 Run | `050b0f95-39b6-4c90-8131-04118dfa32e3` v6/disposed，结果 indeterminate | 只作历史基线，不再 plan/start/import/consume；原 v2 Start 独立保留 |
| 旧窗口 | `2026-10-03T01:35:40.375459Z` 至 `03:25:40.375459Z` | 原样件与 person/equipment 占用仍保留；必须按当前完整账本选择新不重叠窗口，不能根据本地日期推断已空闲 |
| 判据/工况 | dimension、mm、9.5..10.5、`23 C, dry`、non-destructive | 数字与精确出处可读复用，但新计划/实际方法需新的具名用途核对；旧计划条件是合成 20°C，不能复用其计划摘要 |

旧 TestResourceFact 绑定旧 accepted 版本、旧 Run、旧 purpose、旧 window 与旧 `conditions`，不能用于新 Run。其设备/校准原文、日历定义可以作为新可信事实的出处，只有 issuer 当前核对完整决策/全窗与物理身份后才可采用，不能复印“accepted”字符串。上述 UUID 只用于识别公共历史，执行时仍从当前服务器回读核版本和 scope。

## 最短条件序列

1. **只读基线与停止点。** 主线核对唯一授权实例 `62513/pdos_test` 的真实 marker、当前 Product/Build/A/ActualConfiguration、源 ACL 与安全、旧 Run/Request 指针、旧占用/使用及 retained。按 Build/A 和新 purpose 的精确 GET/cap 读取，不扫描全产品深历史。若原 Build 当前 `needs_recheck`、A hold/未知、来源不可读/撤回或任何资格未知，停止依赖步骤，不能用 generic 确认解除。

2. **新用途与当前专业事实。** 新 purpose 建议明确为“内部问题调查：单模穴A尺寸复测”，最多160字符，并保存真正目的出处；若要求采用旧 purpose，应明确这仅是新调查标题，不能宣称已经新增用途许可。专业事实经 host importer 与确切 scope 的 opaque 合成 issuer 办理，按对应角色同时具有 duty 和 qualification。仅导入缺少的 operation/purpose，不替换旧系列，不增旧事实版本：制造 `build.sample.readiness.record`/`verification.handoff.offer`；品质 request/method/actual_method/accept/plan/promise/start；结果 import/compute（分别 T2 review/disposition 仅在实际需要时另办）。每个 FactInput.operations 至多10，使用独立系列分组。新的独立不适用事实在 **retained** 模式可忽略，但当前非 retained 专业摘要仍收全 scope 指针；导入后须再检查原 Build 与 A 当前证明，不假定原 Start 仍 current。依据：[专业摘要与 retained 专用过滤](../../../../pdos-next/server/pdos_next/domain/professional_authority/service.py:511)、[原 Build 当前投影](../../../../pdos-next/server/pdos_next/domain/build_start/service.py:1301)。

3. **建立新准备与正式请求。** 新 Preparation logical UUID，expected revision0，固定同 Build v1；只保留一项 dimension，`sample_count=1`、`cavities=["A"]`、`destructive=false`、mm、9.5..10.5、精确 `conditions="23 C, dry"`。图纸/方法/判据/材料/必需资料都用实际可读固定出处；未知不填肯定。T1 preparation.record 后，用其真实 id/revision/sha256 作 T0 request.create，新正式 logical request UUID，绝不借旧 Preparation 指针重新缩范围。再办理新请求逐 item 的 T1 method.prepare。

4. **A 新用途就绪和逐对实际方法。** 仅当前制造专业事实与 Build limited_current 成立才保存新 ready（如既有 current 已同 purpose 且全部源/原签发人当前，则可复用，不重复写）。事件明确 A/lot/actual/build/state/purpose/真实 occurred_at。对新 Request 的 `(A,dimension)` 保存独立 T1 actual_method.prepare；实际双配置、原方法摘要、purpose 与品质 authority 必须匹配，不复用旧请求 actual-method 行。unknown/not_applicable 就停止接收路径。

5. **完整单对交接与接收。** 新请求 offer 仅 A/dimension，真实发生事件；品质 accept 全部这一个 pair，`returned_coverage=[]`。新请求由设计明确要求1件/A模穴，因此本请求可完整接收；旧请求1/3/B/C缺项原样保留。读取新 accepted 版，完整 accepted coverage 与实际 method 指针作为后续唯一 basis；不需要 schedule.propose 作为开测前置，省去非必需暂定步骤。

6. **新资源事实和新 Run Plan。** 新 Run logical UUID。服务器 `_binding` 从新 accepted 固定版/全部 accepted pair/实际 method 派生；新设备+person资源使用真实 tenant-global 身份。可复用原物理设备身份的前提是全窗容量/校准/维护/日历当前可信，新增使用会改变该资产 epoch；不能伪造新设备 UUID 来规避同一实体占用。新 fact 的完整 window、executor、environment、`conditions="23 C, dry"`、equipment/calibration refs、actual-method pair 全部精确绑定。完整可信 callback/有限合成 decision profile 必须接入正在运行的 API；旧 profile 只覆盖旧 binding，不能默认正向。资源事实有效期与全部决定覆盖整个窗口，Plan/Promise/Start 仍分别 T1 一次共同确认。

   为避免既有数分钟深校验消耗未来窗口，资源 fact 在完成接收后才创建，start 留足实测办理时间（建议约30分钟，主线可依据当前性能选择），finish/有效期覆盖后续真实演练与测量；在旧 A/person/equipment 任一使用窗之后开始。Plan 和 Promise 保存时 start 必须仍是未来，实际 Start 等真实时钟到点，UTC+IANA成对，发生事件不超服务器真实时钟。不得 monkeypatch 时钟、把未来真实事件提前声明或放宽 SQL clock gate。

7. **实际 Start→真实上传一行报告→最终返回→计算。** 实际 Start 保存新 formal occupancy 与新 sample usage，同事务只各一次；旧行保持，没有自动 release。从已保存的新 Run v2、ExecutionPlan、核 SampleRef 与核方法引用构造合成 JSONL，原报告里每个身份和元数据显式存在，`raw_value="11.0000"`、unit mm、conditions **逐字** `23 C, dry`，environment/equipment/calibration/executor/method 都精确等于新已保存计划。observed_at 为已发生的实际开始后时刻且不晚于真实 actual_end；不从旧报告移植 identity 或时间。

   使用 originals 真上传 bytes→显式 scan request/receipt→safe parse；通过服务器 report_sources 获取实际 original_line，不把派生 Artifact.content 行号当原件位置。服务器两阶段 capture+核验后，单 pair 已完整可用，最短可直接 T1 `test.results.import(final=true,capture_id,...,actual_end=真实事件)`，然后 canonical T0 `test.result.compute`。无需为了建 Issue 先做结果 T2 review/disposition；二者是独立专业决定，不能以数值 fail 代替。expected Request/Run revision/basis 均从新 current 指针取得，事件 source 与返回 original bytes/readset 必须完整。

8. **确定失败与品质闭环入口。** 回读新测量 numeric11、原值11.0000、完整元数据、固定判据9.5..10.5及 authoritative projection `fail`。选同一新 Run 的真实结果 Outbox→Receipt event，绑定精确 RunVersion/Measurement/Projection/basis；不是运行状态、前端比较或任意事件。quality.issue.create T0 后可沿 scoped host Policy→T1 triage/containment→T0 CAPA 草稿继续，根因、完成、有效性、关闭仍未知/未开放。政策/品质五 operation 的事实须在该新 Issue 初版前成立，旧 Run indeterminate 永不转 FailureRef。

每个阶段保存一份当前回读即可供该阶段多个断言，避免重复深 GET；新窗口足够长仍保留真实守卫。发生 timeout/unknown 时保存原 command_id/key/payload/prepared token，恢复同一意图；不得新 key 重发 Start/再占用或重消费。

## 可复用工具与必要适配

| 现资产 | 复用内容 | 必須调整 |
|---|---|---|
| [wave13_prepare.py](../../../../pdos-next/tools/wave13_prepare.py) | Preparation/formal/method/ready/actual_method/offer/accept payload 与共同确认格式 | 只取参考代码，不能 import 执行；顶层会读旧seed并连接。新 demo 独立 checkpoint/前缀，只1/A，新 purpose；不执行其 seed，避免再造旧 Lot/A/B |
| [wave13_verify.submit](../../../../pdos-next/tools/wave13_verify.py:91) | inputs补完整readset→共同preview→原 prepared command执行→私有恢复记录 | 新路径/前缀/Run/request/plan；不得覆盖 wave13-seed。不能照搬其20°C工况/旧资源 binding/profile |
| [verification_launch._binding](../../../../pdos-next/server/pdos_next/domain/verification_launch/service.py:246) | 服务器固定 accepted 版、实际 pair/method、Plan binding | 仅服务器受控 helper使用；public不允许任意coverage或units |
| [wave14_prepare.apply_result](../../../../pdos-next/tools/wave14_prepare.py:83) | 结果inputs、T1/T2原命令恢复、T0compute、原报告上传结构 | 不能执行其 seed：硬绑旧run/start并生成中点原值/20°C，且固定未来加分钟不适用于本次真实时序。新报告11.0000、新真实时钟与新checkpoint |
| [measurement_evidence.verifier](../../../../pdos-next/server/pdos_next/domain/measurement_evidence/verifier.py:298) | 真bytes JSONL typed提取/逐字段核值、fixedRun basis、精确行位置 | 只有真实上传original的服务器binding；native事件Artifact不能替仪器报告原件 |
| [quality_result_bridge](../../../../pdos-next/server/pdos_next/quality_result_bridge.py:50) | 确定fail的精确结果事件/版本/原值/retained可信根 | 配置byte桥与末端窄refresh两callback；完整来源/current/runtime epoch仍核对，缺任一503 |

## 执行前不能自动补齐的缺口与验收

- 当前 runtime 的服务器 clock、marker、当前 actor Grant、原 sources/security、issuer/profile、Build limited_current、A ready 与样件使用/资源全窗余额未读取或验证；公共历史不是当前权威事实。
- 真新 purpose 无已有具名 facts 可直接推断；增加相关或独立事实可能使原当前专业/开工证明需重核，不能在旧不可变行上补资格/时效，不能把 retained 只读历史许可用于新开测。
- 同 Sample A 的新用途 Current 与新使用 epoch 对旧 retained 的影响是实质限制；如要求旧 current 证明无变化，必须在写入前停下，由主线另定方案，本计划不给正向保证。
- 旧使用非破坏性只允许通过完整账本检查后的**新**不重叠 Run；它不是旧 Run 重放、重新消费或释放。新占用与旧占用均保留。绝不能为演练更新旧epoch/旧样件state或删除占用。
- 公共注册、迁移、quality/change byte/source/政策接口仍须主线冻结候选验证后启用；此文档不是这些能力通过或真实资格授予的证据。

执行后的最小证据应包含：旧12类身份/版本/原Start意图/占用/样件使用指定旧行摘要前后相等；旧 Request缺项和Run indeterminate保持；旧 retained 当前结论前后单独报告而非隐瞒；新单 pair Request完整接收，新Plan/Promise零effects，新Start唯一effects，真original/hash/security，raw11.0000与matched metadata、固定规则fail、新结果event和Issue唯一回执。任何 guard 拒绝保留原因，不通过改旧数据取得“演练成功”。
