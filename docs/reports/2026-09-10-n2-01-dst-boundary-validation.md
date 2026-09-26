# N2-01 日界与回拨时间顺序修复

2026-09-10；日历算法 `work_calendar.date_grain.v2`。继续已批准日历字段的独立计算基础，不采用 N0-02 待批政策、不接数据库或模型。

## 具体变化

1. 民用日期的开始按该日期首次出现的 UTC 瞬间计算。Havana 重复午夜纳入完整25小时；São Paulo 午夜被跳过时从实际日界开始，得到23小时；Lord Howe半小时DST得到23.5小时，不预设全部偏移为一小时。
2. Apia 2011-12-30整日不存在：直接查询该日明确返回 `calendar_date_nonexistent`；区间用 `skipped_dates` 列出，工作日位移跳过它，不计名义工时。前一天仍有正确结束边界。名义工时与实际日长始终分别记录。
3. 回拨到前一日期再重新进入的非连续日期不能由单一UTC区间表示，例如Goose Bay 1988-10-30；保持 `calendar_noncontiguous_date` 拒绝，不把前一日期时间混入。当前不是覆盖全部历史时区的多区间引擎。
4. 发现并修复共同 `TimeWindow` 的先后判断错误：同一个 ZoneInfo 的 datetime 比较会按墙上时间处理重复小时，原校验拒绝 `08:45Z→09:15Z`，反而接受其倒序。现在统一转UTC比较；同瞬间跨时区仍允许零长度区间。这是落实已批准“时间有序”约束的实现修复，字段、状态及业务批准要求不变。

源码：[work_calendars.py](../../server/app/domain/work_calendars.py)、[TimeWindow](../../server/app/contracts/common_objects.py)。算法版本升级使后续结果不会与v1混淆；每次仍附实际TZif摘要及日历版本。没有把名义工时转换为未知班次或实际容量。

## 验证证据

日历测试由13项增至21项，覆盖精确UTC边界、边界前后1微秒及区间内逐分钟的独立本地日期映射、整日跳过、非连续日期拒绝、极值溢出、回拨合法/非法顺序及同瞬间跨时区。与共同字段和N0-02政策合计 **160 passed**；Ruff check/format、Mypy通过。

```sh
.venv/bin/pytest -q tests/test_work_calendar_calculations.py tests/test_common_object_contracts.py tests/test_product_planning_contracts.py tests/test_version_time_contracts.py tests/test_runtime_policy_contracts.py tests/test_tool_payload_contracts.py tests/test_runtime_adoption_contracts.py
.venv/bin/ruff check app/domain/work_calendars.py tests/test_work_calendar_calculations.py app/contracts/common_objects.py
.venv/bin/ruff format --check app/domain/work_calendars.py tests/test_work_calendar_calculations.py app/contracts/common_objects.py
.venv/bin/mypy app/domain/work_calendars.py tests/test_work_calendar_calculations.py app/contracts/common_objects.py
```

命令均在 `server` 执行，无数据库连接、迁移、真实模型或生产调用。这些回归证明纯计算与合同校验，不证明完整排程或应用接口。

## 当前源码清单与批准原件

刷新前逐项验证：两套导出均只有manifest变更，所有字段/操作/政策/盘点正文摘要不变。共同manifest只更新 `common_objects.py` 和 `work_calendars.py` 的源码摘要；运行政策manifest只更新 `common_objects.py`。两套最终只读漂移检查现均已通过；共同合同经历文件读取等待后，原重跑session 57861返回 `Checked 4 N0-01 artifacts`、退出码0。恢复经过见下段。

### 最终检查的文件读取等待与恢复

原session 85097对应进程33903：调用栈在Python模块导入的file read等待，`lsof`定位为 `.venv/.../pypdf/_codecs/__pycache__/zapfding.cpython-312.pyc`。没有把观察超时认作进程退出。确认具体等待点后，仅终止该自有检查，收到退出码143；随后用独立临时缓存重跑同一命令（session 57861）：

```sh
.venv/bin/python -X pycache_prefix=/private/tmp/pdos-contract-check-cache-33903 -m scripts.export_common_contracts --check
```

重跑进程34590曾等待 `.venv/.../charset_normalizer/api.py` 源文件读取，说明等待不限于原缓存文件。未删除环境文件、重装依赖、终止应用服务或改业务代码；持续读取同一session 57861，最终正常返回，未再次重启。该验证进程现已完成，无需继续轮询。

独立标准库[摘要检查](evidence/2026-09-10-contract-hash-verification.json)已完成：共同manifest的172项来源/3个产物、运行manifest的52项来源/4个产物全部逐字节匹配，获批快照不变。该记录保留其执行当时“完整检查待返回”的事实；之后session 57861的正常退出补齐完整导入/OpenAPI重生成检查，不能把摘要检查本身等同于完整检查。

N0-01获批原件摘要仍为 `9ae54f1385ab835336f75017411d3e3e6a1fec98fd7e63c0876fb13995a232b0`。N0-02原审阅manifest另存[历史原件](../contracts/pdos-runtime-v1/review-history/2026-09-10-draft.3-manifest-before-time-window-fix.json)，摘要 `0529d73896e53cc9e5e01483e0fa80a2009c349482955050c8e1b5693bcfd836`；当前为 `3acef5382f0a8041a6777e9ea82a72628166ac80782c58211f2a196ab9ddec6d`。DC-06/07/08提案和参数本身未改，仍待用户裁决，不借源码修复伪造批准。

N2-01仍部分完成：小时/班次、四时间持久化/节点/共享资源、实际授权及迁移/页面待实现；非连续历史日期尚不支持。N0-02仍为主指针，任何P/Q/Sprint出口均未关闭。
