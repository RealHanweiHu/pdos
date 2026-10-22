# pdos-next 规划计算首版与接入说明

日期：2026-10-02。范围：G1.3/G5.2 的独立日历、依赖排程和 Forecast 候选计算；业务写入、项目/计划共同对象、页面与联合验收由主线接入。本包不更新 G/N/P/Q 清单，不证明业务闭环完成或任何实际资格。

## 可用模块

- `pdos-next/server/pdos_next/engines/planning/dto.py`：不可变、拒绝额外字段的 typed DTO `planning.v1`。固定节点 ID、日历 ID/版本/原始时区/明确时段/逐日例外；工时及等待各有上下界、total/remaining、来源版本和可信程度。未知为 `null`，零须显式提供。
- `calendar.py`：`WorkingTime` 的 `snap/advance/segments/working_minutes`，UTC 分钟运算、本地工作日、午间空档、跨日、假日和加班例外、正负工作时长、DST。计算实例和摘要使用同一冻结 TZif 字节；可提交 `timezone_rules_sha256` 固定规则，规则变化拒绝计算。
- `forecast.py`：`calculate_forecast(ForecastInput) -> ForecastResult`。稳定拓扑顺序，FS/SS 区间传播，FS/SS/FF/SF 精确估时与正负 lag，Actual 锚点及明确剩余量；局部缺数保留独立支线结果，环/重复身份/缺端点/缺日历整体拒绝。结果含缺项、冲突、来源、全输入快照、输入及候选摘要、日历规则摘要。
- 最小资源检查：固定资源 ID/版本、资源日历、Decimal 容量、已占用半开 UTC 区间及节点需求。检查剩余工作时段与资源日历、已有占用和其他候选节点是否冲突。只产生解释，不改开始时间、不选择优先级、不创建或释放预约。
- 完全已知、无 Actual 锚点且未请求资源检查的候选，可计算相对当前项目 Forecast 完成时间的 latest start/finish、elapsed/working float 和关键节点。其他范围显式 `float_status=not_calculated`，不沿用精确点估计浮时。

`engines/` 公共父目录未创建 `__init__.py`，本包可作为 namespace 子包独立导入。唯一入口示例：

```python
from pdos_next.engines.planning import ForecastInput, calculate_forecast

snapshot = ForecastInput.model_validate(payload)
candidate = calculate_forecast(snapshot)
candidate_json = candidate.model_dump(mode="json")
```

完整可运行合成输入/结果见 [example.json](example.json)，生成器见 [example.py](example.py)。无旧 app 或新 service/runtime/api/models 导入，无数据库连接、模型 transport 或业务写方法。

## 计算语义与首版限制

1. 所有瞬时输入须带时区，DTO 统一成 UTC；Calendar/ExternalWait/TimeRecord 保留原始 IANA 时区。Actual 不做分钟取整，预测按未来方向取整。工作量和 waiting 都是分钟；waiting_clock 明确 `elapsed`（UTC 实际分钟）或 `working`（本节点日历）。跨夜班须按本地日期拆段，逐日例外完整覆盖当日片段。
2. 非零工时先落到可工作时段；零工时可作为明确零时长检查点。`parallel_units` 是线性可分工作的投入假设；大于一必须 `divisible_work=true` 并有 allocation_basis，不构成人员资格或资源容量事实。
3. Dependency 的 working lag 使用后序节点日历；elapsed lag 用 UTC。负小数 lag 向未来取整，避免放宽依赖下界。只把执行依赖送入本核，审批/引用/反馈边不属于本图。
4. FF/SF 或 finish-target 外部等待与非精确区间耦合时，首版返回 `finish_constraint_range_not_supported`，保留输入与 Actual，不虚构反推日期。精确完成下界仍可计算。要支持这类区间，需要后续实现耦合边界求解并验证；不能简单跑两次全图点估计。
5. `TimeWindow(earliest, latest)` 中 `latest=null` 表示没有有限交期；`earliest=null` 表示连下界也未确定。节点 `status=exact/range/unknown/conflicted`，项目 `complete` 仅代表本计算所有完成上界已知且无阻断说明，仍是 Forecast 候选。`range` 不能当承诺或精确日期使用。
6. 已开工节点须显式提供 work 与 waiting 的 remaining 估时；不得从 total 或原基线猜剩余量。实际完成节点保留事实，即使违反依赖、缺资源或日历计算失败，也不移动或清空 Actual。未来 Actual、倒置时间、非法估时等不构成可用输入。
7. ExternalWait.ready 是来源给出的就绪区间，`null/null` 是未知，blocking 明确是否约束 start/finish。本核不从请求发起或提醒次数推导对方响应；有效送达、最新版本、失效与关闭条件由主线读端口核对。
8. 资源需求仅支持 `occupation=work_only`；等待占用、资源拆分/优化/抢占、人员资格/设备校准/工装适用/样件消耗尚未实现。这些条件不得由 `capacity_status=checked` 推断通过。需求区间不精确、资源或日历缺失时为 unknown；数字超额或工作时段不可用时为 conflicted。已完成事实不参与未来容量检查。
9. Baseline/Forecast/Commitment/Actual 是独立 `TimeRecord.time_kind`。输入原记录完整留存，只输出 `time_kind=Forecast, disposition=candidate`；Baseline/Commitment 不作为隐式约束或 deadline，不改承诺/基线/事实。没有生成时间/随机数，固定快照、算法、时区规则与固定 Decimal 精度下结果可复算。
10. horizon_days 默认 366、最大 3660；时间/日历超出有限窗口或 datetime 范围时返回明确原因，不能拿 horizon 端点充当预测交期。未带 TZif 摘要时会在本次调用固定并返回实际规则摘要；跨环境重放应传回固定摘要，否则不同规则产生不同输入摘要。

## 主线必须提供的读写 port

这些是接入需求，本包没有注册对应业务对象、命令、表或 port 实现。

| 主线接口/对象 | 输入与职责 |
|---|---|
| 受控 PlanningReadPort | 服务器从授权上下文固定租户/真实项目范围，读取当前 source read set。提供真实 `ProjectProductLink` 的 ID/版本及固定 DefinitionRevision，不由模型参数决定范围。 |
| 双线 WorkPackage/Task 读投影 | 工程与 NPI 真实稳定节点映射、具名 accountable owner/接收责任、前置专业工作与执行依赖。缺责任/定义关联不能凭计算结果正式建项目或任务。 |
| PlanRevision 读快照 | 以 snapshot_id/version 对应固定计划候选及读版本，提供每个节点的日历/版本、估时范围及来源、显式剩余量、四时间独立来源；跨项目边由主线固定外部锚点后投影，未知保留。 |
| Calendar/ExternalWait/ResourceSnapshot 读口 | 版本与适用范围、TZif 摘要、例外、有效送达/当前就绪依据/失效、资源日历/容量/占用与来源；一致快照，不能漏掉当前占用或把旧预约当资格。 |
| ForecastCandidateWritePort → 共同命令入口 | 存输入快照与 input_sha256、algorithm_version、candidate_sha256、读版本集及完整缺项/冲突。写入前复核范围、版本/来源有效性、幂等/过期、撤回与共同事务回执。只写 Forecast 候选或明确差异，不能改 Actual/Commitment/Baseline/Reservation。 |
| 具名正式命令/决定 | 基线批准、承诺、预约、项目与双线工作包应用另走主线共同入口。需要真实责任/当前权限和对应 T1/T2 路径；纯计算结果不赋予批准、资格或执行权。 |

后续页面须显示区间/未知、四时间差异和阻断说明；不能为甘特图把 null 填零。主线可以先接 FS/SS 与精确完成约束的人工计划路径，复杂 finish 区间仍显示当前缺口。

## 提取依据与候选证据

旧源码仅供算法参考，未复制数据库服务、旧 Contract、任务枚举或业务实例：

| 源路径 / 符号 | 本包采用与改动 |
|---|---|
| `server/app/domain/working_time.py` · `ceil_minute/minute_quantity/WorkingTime` | 本地端点/DST 校验、UTC 正负分钟推进；替换 DTO，加入逐日例外、有限窗口、UTC 半开段与午夜排他边界。 |
| `server/app/domain/plan_scheduling.py` · `_schedule_plan/schedule_plan` | Kahn 拓扑、FS/SS/FF/SF 约束、精确完成下界与浮时；替换 ID/估时区间/显式等待，负 lag 正确取整。 |
| `server/app/domain/schedule_forecast_engine.py` · `calculate_forecast/_calculate` | Actual 固定、开工后 remaining 必须明确、未知传播；移除旧业务字典、材料/工装/预约服务和任务枚举。 |
| `server/app/domain/work_calendars.py` · `_zone_rules` | 冻结同一 TZif 字节计算和留存摘要的原则，日历输入摘要覆盖时段/例外/DST 政策。 |

完整文件与符号 SHA-256/行号见 [source-summary.json](source-summary.json)。包候选摘要及 17 份交付文件逐项 SHA-256 见 [candidate-manifest.json](candidate-manifest.json)；运行实例的候选摘要在 example.json。导入边界检查见 [import-boundary.json](import-boundary.json)。

当前最终候选：**76 项纯算法检查通过**，包内 Ruff 与格式检查通过，见 [checks.json](checks.json)、[pytest.log](pytest.log)、[ruff.log](ruff.log)、[format.log](format.log)。测试覆盖：日历空档/周末/假日/加班/跨日、LA 春秋 DST、沪美跨站点、TZif 固定、四类依赖/正负与小数 lag、已知区间/未知工时/未知等待/局部传播、环与错误引用、实际锚点与异常保留、四时间不改、Decimal 环境稳定、有限窗口/日期溢出、半开资源占用/候选互斥/缺容量/资源日历。

独立复核入口为 verify.py，仅本包路径、`--confcutdir=tests/planning_engine`，禁用 pytest 外部插件及共享缓存/字节码；没有加载根数据库 fixture、读取 .env/.local、访问数据库/预览/工作流服务、调用真实模型、安装依赖、运行完整构建、修改公共对象/迁移/web/清单/设计、提交或 push。实际业务接线、数据库并发写入、浏览器整链及 G1.3/G5.2 完整验收尚未实施，留给主线候选统一验证。
