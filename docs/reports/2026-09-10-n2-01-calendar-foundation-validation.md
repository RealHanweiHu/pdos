# N2-01 工作日历计算基础

2026-09-10。按活动清单“依赖是完整交付所需能力，不等整包开始独立基础实现”推进本片。输入只消费已获批 N0-01/DC-02、DC-05 的 WorkCalendar 字段；N0-02 待批的主体、运行参数、计费及保留政策未用于实现。N2-01 整项仍依赖 N0-02，不据本片绕过批准。

## 实现与使用语义

[work_calendars.py](../../server/app/domain/work_calendars.py)提供不可变 `WorkCalendarCalculator`：

- `local_date(instant)` 按具体站点时区映射日期，拒绝无时区 datetime。
- `day(date)` 给出实际 UTC 日界、是否工作日及名义工时。普通 DST 日可为23/25小时；名义工作量沿配置，两者不混算。没有班次信息时不推断每日9点开工，也不据此计算小时级资源占用。
- `period(start,end_exclusive)` 按半开区间枚举工作日，排除周末及显式假日，以 Decimal 计算名义工时。空区间/无工作日为真实0，不等于资源输入缺失。
- `shift_workdays(anchor,n)` 排除锚点，正/负整数分别找后/前第n个工作日；0原样保留锚点，不暗中调到工作日。布尔与小数拒绝，工作日为空或搜索耗尽明确失败。
- 结果带日历ID/版本/正文摘要、算法版本及**实际读取的 TZif 时区规则摘要**。计算使用同一份规则字节构造 ZoneInfo，避免只标版本但实际读取另一缓存规则；计算不修改原日历。

例：周一至周五、2026-09-07显式假日、7.5小时/工作日，9月4日前进1工作日为9月8日；`[9月4日,9月9日)`有9月4日和8日两个工作日，名义15小时。2026-03-08洛杉矶日界为23小时，11月1日为25小时；不是减少或增加名义7.5小时配置。

计算保护上限为36600个日历日，位移默认最多扫描3660日、调用方可显式给更小或有界更大的搜索区间。这只是纯函数的资源上限，不是待批运行预算或业务截止时间。耗尽返回 `calendar_scan_limit`，不返回不完整结果当作完成。

## 验证

在 `server` 执行：

```sh
.venv/bin/pytest -q tests/test_work_calendar_calculations.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py
.venv/bin/ruff check app/domain/work_calendars.py tests/test_work_calendar_calculations.py
.venv/bin/ruff format --check app/domain/work_calendars.py tests/test_work_calendar_calculations.py
.venv/bin/mypy app/domain/work_calendars.py tests/test_work_calendar_calculations.py
.venv/bin/python -m scripts.export_common_contracts --check
.venv/bin/python -m scripts.export_runtime_policy_contracts --check
```

本片13项测试，含已冻结共同合同共90项通过；Ruff/format、Mypy及两套合同产物漂移检查通过。覆盖双向假日位移、半开区间、DST跨越、同一瞬间不同站点日期、空工作周、搜索耗尽、日历版本与规则摘要、无时区/错误日期粒度/布尔/小数/溢出。Pacific/Apia 2011-12-30的缺失日界和America/Havana 2020-11-01的重叠午夜明确拒绝，未把系统默认fold当作业务决策。

这些为本地纯计算测试，不连接数据库，不调用模型，不证明资源授权、并发预约或页面可用。没有新增迁移、模型工具注册或生产变更。

首次共同产物漂移检查发现 `manifest.json` 新增一个领域源码条目 `server/app/domain/work_calendars.py`，因为导出器完整盘点领域文件。已逐项比对：无既有来源摘要变化、无字段/操作/盘点正文变化，只有该新增来源；随后仅刷新当前源码manifest并重验。`approved-draft.3/`获批原件及其摘要完全未改，不把当前代码清单更新当作重新冻结合同。

## 剩余范围

N2-01 保持部分完成。当前仅日期粒度：缺班次时不算小数工作日、小时级lag或局部日容量；午夜跳变/重叠日期仍需后续显式日界/班次策略，不能宣称全部时区历史已支持。正式四时间存储/不可变版本、节点复合FK、跨项目授权、日历例外、共享资源身份/容量、Forecast历史序列、迁移和页面尚未接入；关键路径/预约属于N2-02。

N0-02 的 DC-06/07/08 仍等待用户明确裁决，主指针不变。冻结或未回复均不自动使上述未完成内容成立。
