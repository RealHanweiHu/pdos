# 试模 / 试产首版接入合同

本包是独立可调用领域实现、封闭 DTO、事实端口、计数纯核、读模型和 typed 组件。公共注册、持久模型/迁移/RLS、共同命令/T1、API/BFF和父页面未接线；没有真实资源资格、制造基线、品质结果或工厂验收。只使用新工程，不导入旧 app 或继承旧批准。

## 可调用入口与固定输入

`domain/manufacturing_trials/handlers.py` 的 `ManufacturingTrialsHandler(Ports(...))` 提供 `preview(operation, subject_id, expected_revision, payload)` 和 `execute(Invocation, payload)`。载荷必须经过 `schemas/manufacturing_trials/contracts.py` 的三个闭合 DTO 验证；未知字段（tenant、project、qualified、write_tier 等）拒绝，DTO 不可变。`semantic_digest` 是完整载荷稳定 SHA-256；数组顺序具有含义，不隐式规整不同输入。

| canonical 操作 | 载荷 | target / expected | 结果 / event | 分级 |
|---|---|---|---|---|
| npi.tooltrial.create | ToolTrialCreate | 新 trial_id / 0 | ToolTrial + verification owner 的 RequestCreate 共同事务意图 / tooltrial.created | T1 |
| npi.pilot.create | PilotCreate | 新 pilot_id / 0 | 固定 BuildLot 的 PilotRun 扩展 / pilot.created | T1 |
| npi.pilot.result.record | ResultRecord | pilot_id / 当前 PilotRun.revision | 不可变 Observation + Pilot 指针续版 / pilot.results_recorded | T1 |

这三个动作只在包内可调用，主线必须按共同 registry 的 canonical 政策注册后再暴露。没有 npi.pilot.start、正式制造放行、工装验收、T0自主写入或AI T2入口。具名验收引用仅引用已经存在的真实人类决定，由事实端口鉴别发行者、范围和效期；引用本身不产生批准。

ToolTrial 的 `trial_round` 是试次的非负整数，与固定 `write_tier=T1` 无关。Build、Tooling、材料批次、参数/单位/来源、模穴、原问题、整改、具名验收固定；品质意图复用 verification.RequestCreate 的真实完整载荷，不建第二请求/测试结果账。发生过的 sample_ready、offer、accept、promise、start 和结果回传仍由 verification 独占。

PilotCreate 固定已有 Build/BuildLot/ActualConfiguration/实际 EngineeringConfiguration/ProcessRevision/单位；制造基线另用 `kind=manufacturing_baseline` 引用，工艺草稿不能冒充基线。人员、线体、材料、治具/设备、SOP/control/risk、预约、参数、首件来源均为 typed 固定引用或明确未知。缺项仍可保存候选及真实明确观察，但所有准备读模型 `start_authorized=False`，不代表已批准开工。Pilot 的基础固定输入不能被后续结果静默改变。

## 主线端口实施清单

1. 实现 `CommandPort`，实例绑定当前调用者 Session。`atomic()` 必须使用同一 Session 的 savepoint/UoW，在异常时回滚，不提交外层事务；禁止在本包内新开连接。公共命令入口在外层承担正式 commit。锁顺序统一为 semantic intent→Build→BuildLot→Pilot→资源/原件；两个同批次请求使用同一父锁。Preview可只读；execute重新完整读取及验证。
2. `context/begin` 从服务器绑定真实 tenant/product/project、actor_kind、职责、现行能力资格与取消状态。T1不因本包政策授予AI資格。`begin` 使用持久化业务意图锁：同key异载荷冲突，同意图跨key返回原回执；历史重放仍复核当前读取权限，不重复新的副作用。新UUID不得绕过同BuildLot扩展/观察原始来源的语义去重。
3. `confirm` 复用共同 T1 实质预览/一次确认。绑定actor、scope、operation、target版本、完整payload、固定read_set、source读集、当前preparation、expiry和撤回代次。`recheck` 在写前复核当前授权、资格、取消、ACL/引用撤回、资源资格/预约及适用性，确认和撤回竞态必须共锁。结果未知时按原命令查询回执，禁止盲重发或另建意图。
4. `record` 插入不可变 Trial/Pilot快照/Observation，CAS Pilot当前指针并保留各版；before=0只能insert，不upsert旧ID。定义同scope+BuildLot活动扩展唯一键、观察ID/原来源意图唯一键、原子组回执/审计/Outbox。ToolTrial的 `verification_intent` 必须调用 verification 唯一服务同事务落账，并复核verification所有者自己的范围/职责/当前资格，不能以父T1确认绕过子服务政策；不得把异步Outbox发出当作已经建成品质请求。任一步失败回滚确认消费、领域事实、品质请求、Audit/Outbox和ActionReceipt。
5. `FactsPort.check_ref/source` 解析权威对象kind/version/scope、ACL、原始位置、有效性、撤回、用途适用性。现有 configurations.ProcessRevision 只有草稿；baseline/SOP/control/risk/Tooling等权威未齐不能返回伪造ID或以字符串认证。未知端口返回 INTEGRATION_REQUIRED 或明确缺项，不能空列表冒充全部满足。
6. `lot` 只从 build_execution.BuildLot/ActualConfiguration/SampleUnit 当前锁定记录读取实际数量、单位、nature与源。BuildLot数量是已经发生的产出范围，不再次增加库存；不读计划数量作为实际投入/产出。必须验证工程配置/工艺对应当前实际配置与同Build/项目。
7. `preparation` 返回 PreparationFacts（gaps + critical read_set + sources），通过 resource_readiness 固定资格、设备/治具适用/验收/校准、人员/线体及预约引用；通过 supply_cost 的实际物料可用/占用及品质方法/资料/样件准备读取缺项。硬阻塞优先，未知/冲突保留；不新增本包资格或资源预约账。资格/预约当前固定版本及关键来源进入实质预览摘要，并在execute重验，版本漂移导致重新预览。当前DTO保守将缺失必要引用列UNKNOWN；如真实政策允许N/A，后续需具备正式规则/依据的明示适配，不能在模型载荷填无须。
8. `verify_parameters` 对试模/试产参数数值和单位进行原来源精确核对，不能只验证参数source存在。`verify_result` 必须核对原来源里的实际数值/单位/发生时间/nature及累积范围，而非仅检查hash/ACL。返回服务器固定 YieldScope（含判据、统计窗口、minimum_sample），handler与载荷逐字段比较；模型不能改变阈值。逐件验证实际SampleUnit属于固定lot/config且未重复，批次计数必须有同等严格互斥分区证据。数量不超过该lot原观察数量，样本子范围须服务器证明，无缺数据补造。异常来源和处置来源独立验证；具名决定不得从自由文本生成。

## 计数、修正、汇总与读模型

固定分母是一次投入的唯一单位数（非返工事件数）。`output_count = input_count - unprocessed` 代表已走过首轮过程的单位数，并不是新增合格库存；它包含合格、报废、返工中和未判定单位。

- 首遍口径：first_pass + first_failed + first_unknown + unprocessed = input_count。
- 终态口径：final_good + scrap + rework_pending + undecided + unprocessed = input_count。它们是互斥当前终态；reworked_good为final_good子集，rework_cycles仅信息，不额外加入投入。
- 比率为Decimal fraction，固定28位精度。first_pass / input_count 与 final_good / input_count 分开；first_unknown未知或>0时不发布可靠首遍率。最终已知合格数可显示观察比例，未判定/返工中/未加工或局部未知始终提示不完整。
- 已知数量矛盾拒绝写入，未知分母/零分母不显示百分比，局部未知不填零。低于服务器minimum_sample标样本不足；任何数量或良率均不宣布过程能力或工厂资格。
- ResultRecord采用完整累计快照，逐件和batch互斥。追加修正必须引用当前latest_observation_id与原因；旧版保留。已知分母不能改变，范围/窗口/判据不能改变，逐件身份集合不能改变。分母原为未知时，只允许在同一服务器固定cohort中用经过原值核对的已知数量续版；历史未知比例仍保留。
- 汇总只接收已经服务器授权/核对的当前观察。`aggregate` 对同一lot重复（含修正版）拒绝，对不同actual configuration/工程配置/ProcessRevision/单位/制造基线/线体/窗口/判据/nature/阈值拒绝；兼容批次先加所有计数后计算比例。当前首版保守要求actual configuration完全相同，尚未提供跨不同actual configuration的权威适用性证明汇总。未知分量导致对应汇总项未知，不计算已知部分的假完整比例。
- `read_models.pilot_reading` 分别返回creation准备度、当前准备度（未注入为None）、latest观察、superseded历史和固定范围；当前观察未取到时拒绝使用旧结果替代。主线为每个输入记录完成ACL/范围验证后再调用纯投影。

## 持久 / API / 页面需补的具体接线

公共模型/迁移按主线真实head分配，不使用预留迁移号。新增trial/pilot/observation不可变快照及CAS指针、带tenant/product/project的外键、actor/owner引用、source读集、RLS和上述唯一键；不得向原件或golden-case写入。资源/品质/供应权威模型不在本包创建。

API/BFF把Operation+共同command id/token绑定 Invocation；payload内不得夹带服务器scope/资格。提供列表/历史读取和共同T1预览/确认/回执查询，页面只消费真实投影与动作注册状态。typed独立组件从 `components/manufacturing_trials/index.ts` 导出；`toDomainPayload(intent, newId)`生成精确snake_case封闭载荷（parent提供稳定UUID），完整12计数/逐件来源/异常事实均有映射，3个adapter输出已直接通过Python DTO验证；父区拥有预览/一次确认/回执slot。UI到封闭DTO的adapter及完全合成跨端载荷验证见本目录最终证据。禁止业务页面导入组件测试fixture。

公共PG/事务锁/RLS/来源ACL、HTTP、实际浏览器、多尺寸双主题、迁移往返/恢复和真实工厂联合验收由主线完成；本包102项合成检查和局部组件检查不能冒充这些验收或G/N/P/Q出口。

## 消费接口摘要与漂移

复用 verification 的 frozen DTO/SourceRef/Scope/EventTime/TimeFact、完整RequestCreate；它拥有图纸/特征/判据/样本/模穴/方法/资料请求字段与时间时区验证。build_execution 的BuildLot固定ActualConfiguration、observed_unit_count、unit、nature和发生/接收时间，SampleUnit拥有批次/配置/模穴身份；没有本包产出/样件写入。configurations.ProcessRevision固定工程配置和operations，目前draft，不等同ManufacturingBaseline。supply_cost端口分权威需求、实际供应快照和占用/适用性，供方承诺不当成实到。前端仅运行时复用现有Button/Phosphor/UI tokens，不导入其他业务实现。

首读和交付复核hash见 consumed-interfaces.initial.json / consumed-interfaces.final.json；首版后端消费文件复核无漂移。后续主线更改共享接口时须按摘要定向复核，不能将此固定候选检查外推为新候选已通过。
