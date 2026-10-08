# 资源资格与预约 · 主线接入合同

日期 2026-10-02。独占 `domain/resource_readiness/`、`schemas/resource_readiness/`、`tests/resource_readiness/`、`components/resource_readiness/` 及本证据目录。只建设 pdos-next；没有旧 app、SampleUnit/库存第二权威、公共注册/迁移/API/页面修改或独立数据库事务。本包是可调用领域实现，实际持久适配与共同命令接线由主线完成。

## 入口与事实绑定

- `ResourceReservationHandler(facts, store).preview(request, expected_revision=0, target_state="formal", reason=None)`：只读固定资格、日历、占用和来源，返回封闭 `ReservationPreview`；五分钟上限、读集摘要、版本、状态、原因和有效期绑定。共同预览可采用更短有效期。不生成确认token。
- `stage_formal(request, preview, expected_revision=0)`：调用者UOW内锁定并重读，核对共同证明，暂存正式占用。返回 `StagedReservation(disposition="staged_in_caller_uow")`，不是已提交回执。
- `stage_tentative`：仅保存暂定时段；资格/资源证据不明仍明确UNKNOWN，可继续准备，正式占用为零。租户/项目、真实授权、服务器要求的资源集合/units、用途/工序、动作政策必须真实绑定。
- `stage_terminal`：仅 `released/cancelled`，须原正式/暂定记录、CAS和具名原因。追加历史，保留原固定事实与原资格报告；清理占用不要求重新接受已撤回资格，也不恢复任何已破坏样件。终态不能静默重新激活。
- `recheck_execution`：锁内校验现行权限、证据、人员资格、维护、版本、日历、容量及本run的完整正式占用，且当前时点在半开执行区间内。不会记录Actual。
- `ResourceReservationPort`：主线 `SampleAvailabilityPort.reserve` 可消费的资源子协议。`ResourceFactsPort`/`ReservationStorePort` 全部绑定调用者Session，不自行连接数据库、commit/rollback或等待外部服务。

`ReservationRequest` 拒绝额外字段，无租户/项目/actor/资格/授权字段。仅固定预约ID、真实run、意图key、用途/工序、资源ID/版本/kind/units、半开区间与原IANA时区。服务器 `context` 绑定 `Scope`、actor、run、executor/crew、现行资格/授权/取消、政策注册、批准方法要求的全部资源与units、来源及权限epoch。请求不得降低units、删治具/人员或换用途逃逸。

`ResourceSnapshot` 为当前授权项目适用性投影：租户/产品/项目、不可变物理身份及资源版本、用途/工序、验收/校准/人员资格具名事实、有效区间、当前维护、固定CalendarSnapshot/TZif摘要、容量及occupancy_revision。适配器必须证明每项资格属于**当前固定资源版本及本run两条实际配置**；模型传来的source、角色、政策或“合格”字样都不是事实。共享物理资源跨项目保持同一租户级ID/sentinel；不能每项目克隆成不同资源。

验收/校准/资格事实含用途、工序、来源和已有具名决定ID/actor；没有签发/验收写入口。本规则不授真实资格。人员可为服务器固定executor或明确分派crew，每人独立检查。缺维护记录用 `None`，服务器核实无维护为 `()`；未知有效期不当永久有效。

## 规则、四时间与复用边界

硬阻塞优先，仍展示并存未知；缺必需证据/日历/TZif/容量为UNKNOWN；明确拒绝/撤销/失效、资源版本或用途不适用、维护/日历/容量冲突为BLOCKED；所有限定条件由服务器证明本用途当前可执行时为READY_WITH_CONDITIONS；全部满足才READY。验收/校准/资格覆盖**整个** `[start,finish)`，valid_until等于finish可以覆盖；早一秒则不能覆盖。非可豁免失效不被条件或高分抵消。

复用规划 `CalendarSnapshot` 和冻结 `WorkingTime.intervals`，直接使用UTC真实端点，不以分钟取整放宽预约边界；保留日历版、IANA与TZif摘要。跨23/25小时DST日按真实UTC连续时段检查。容量为有界精度Decimal扫线，区间边界不重叠、同边界净变化后比较，分离时段不简单累加。`capacity_status=checked` 不等于资格或预约，规划ResourceSnapshot/Forecast只算候选，不会创建占用。

正式预约一般面向未开始的固定区间。若接入既有RunStart同事务预约，`context.verified_actual_start` 只能来自主线已核验的真实EventTime/来源，时间不晚于服务器now且在该固定区间；允许资源子协议随真实开测动作暂存。缺真实Actual证据时不能用预计时间补造/回填，也不能回溯造预约。暂定时段、正式预约、实物接收和Actual开测仍为四个独立事实；本包不拥有后两项。

## 资源 + 样件原子办理（必须）

既有接口原样保持：

`SampleAvailabilityPort.reserve(scope, run_id, samples, coverage, destructive, execution) -> None`。

主线在该适配器内从已批准方法、完整执行区间、`execution.equipment/calibration/executor_id` 与实际run解析资源子请求，核对每个SourceRef到固定资源/资格事实。`ExecutionConditions` 未包含结束时间/治具/crew，不能从duration默认值推断；这些需读取主线受控方法/预约上下文，缺项保持UNKNOWN，禁止开测。

建议调用顺序：

1. 一个共同命令 + 一个调用者Session/UOW；固定服务器scope/权限与父Request，再锁Run与稳定run意图。统一锁序为父Request→Run→稳定意图→全部物理资源UUID.bytes→全部SampleUnit UUID.bytes。来源/权限epoch锁序沿主线共同合同统一；任何资源/维护/资格/日历写方也须相同sentinel锁或对应CAS。禁止另一个入口逆序锁定。
2. 读完整固定资源/当前资格/日历/TZif/容量/占用，包括跨项目占用和本UOW已暂存写。即使原来没有预约也锁sentinel，防幻读。读取实际SampleUnit/ActualConfiguration和逐sample/item覆盖，由现有样件权威办理。
3. `stage_formal` 与样件预约/破坏性消费都在此UOW内。共同T1预览必须已包含资源读集；资源 `store.confirm` 复用外层已消费且绑定该资源读集的同一证明，**不再次消费，也不要求第二次用户确认**。独立动作未注册时 `policy_registered=False`，本包保持未接线。
4. `store.stage` 做insert-only或预约CAS、每物理资源occupancy CAS/bump，核验资源/资格/日历/原件/权限/取消epoch；仅occupancy CAS不防资格撤销竞态。阶段结果、SampleUnit占用/消费、Run/Request更新、共同证明、业务回执、审计与Outbox一起flush/commit。
5. 任一重核、样件冲突、CAS、后续Mutation/回执/Outbox失败，外层**回滚整笔UOW**，不得捕获资源异常后仍提交样件，或资源先commit再另办样件。结果未知只查原共同意图回执，不重新建预约或重复消耗。正式占用完整性不符时拒绝重放和开测，历史不抹除。

`test_entire_caller_uow_rolls_back_resource_sample_proof_and_receipt` 覆盖资源暂存后、样件后、回执后及CAS失败；`test_sample_mutated_first_still_rolls_back_when_resource_stage_fails` 覆盖反向失败。`test_counterexample_separate_uows_leave_orphan_resource_occupancy` 是**禁止拆事务的反例**：资源独立提交后样件失败留下孤立正式占用。均为合成调用者UOW，不能证明PostgreSQL事务/并发联验通过。

## 政策、持久化与主线具体接线项

- 治具验收沿canonical `npi.fixture.accept` T2，只给具名人员；AI不能接受/代签。本包只核验已有事实和提供候选显示。
- 人员资格签发/撤销、设备/治具校准接受、维护管理、独立预约/暂定/释放/取消尚无本包公共操作注册，需主线专用合同、角色/分级与共同T1/T2政策。不得擅自映射T0或以DC-11政策批准当真实资格。已有品质RunStart也应先注册其专用合同后暴露；内部资源步骤沿该动作现行政策。
- 新实体建议：ResourceIdentity/不可变ResourceRevision（kind/用途/适用性/来源）、Qualification/Calibration/AcceptanceFact版本与具名决定、MaintenanceFact、Calendar固定版本与容量、ResourceOccupancySentinel、Reservation及追加Event/固定ReadSet、稳定意图和原回执链接。名称仅接入建议，公共models/namespace/迁移单调号由主线统一。
- 必须约束scoped FK/实际配置适用性、每tenant物理资源稳定ID、每run一套资源bundle、预约ID和key别名唯一、insert-only/CAS、当前occupancy epoch、正式状态占用一致性；跨项目容量读取用受控sanitize端口，不因view ACL漏掉占用，不暴露他项目业务详情。被引用的物理资源/sentinel不可物理删除。历史释放/取消不抹除旧资格或具名决定。
- V1固定请求内容不原位换窗口/资源、不抢占/拆分/优化；一个run一套bundle。重新策划需新受控run或主线追加明确版本化改约合同，不能改key/ID绕过稳定意图。UNKNOWN结束时间不提交假窗口。无限期资格/多次测量/crew角色细分须主线提供专用政策；当前无无限期资格假定。
- API/BFF与父入口：生成真实服务器读投影，映射组件字段，接现有Button/语义主题；`onPrepare`仅委托共同动作，`actionReview`注入主线现有预览/一次确认/回执。父客户端负责晚返回的contextKey核验及过期/结果未知恢复，无本包确认体系。不得把包内合成测试材料接入业务页面。

## 消费接口摘要与交付边界

`verification/ports.py`：消费Scope及SampleAvailabilityPort.reserve的同事务/零commit约定；没有修改签名。`schemas/verification/contracts.py`：直接复用Scope/SourceRef，不新建样件或Actual配置。`planning/dto.py`：直接复用CalendarSnapshot；ResourceSnapshot/ForecastOutput仅作只读参考。`planning/calendar.py`：复用WorkingTime.intervals冻结TZif/DST，不调用预测创建预约。规划原integration为其result.md“主线必须提供的读写port”章节；品质integration明确破坏性样件与资源重核同事务。前端直接复用Button/React/Phosphor，共同确认只读参考并通过slot消费。

初始/交付哈希及漂移结论见 `consumption-initial.json`/`consumption-final.json`；前端额外只读界面摘要见 `ui-consumption-final.json`。包内固定候选见 `candidate-manifest.json`，纯检查原始日志与退出码见 `checks.json`。本包未修改唯一清单，不访问数据库/共享服务、.env/.local/真实密钥、原件/模型/云、共享.next、依赖锁或git提交/push。

仍未实现主线持久适配、注册/迁移/RLS、API/BFF/页面与真实资源事实、数据库并发/跨资源样件原子联验、HTTP/浏览器与正式G/N/P/Q出口。缺真实条件明确UNKNOWN/待接入；包内合成通过不授资格、不启用生产、不计人工Exit。
