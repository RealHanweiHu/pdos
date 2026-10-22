# 长存储夹具只读复核

记录时间：2026-10-03T02:24:56Z（本地 2026-10-02T19:24:56-07:00）。本次仅核对源码、文件元数据及主线指定进程启动时间，不运行 PostgreSQL、公共测试或构建，不改代码/测试/迁移。合成事实时效调整不授予生产资格、改变角色矩阵或放宽生产守卫。

## 最终源码与来源

| 文件 | 当前 SHA256 | mtime（UTC） | 归属及变化 |
|---|---|---|---|
| [verification_launch/fixtures.py](../../../../pdos-next/server/tests/verification_launch/fixtures.py) | `10e5c57889064fd47be6044f80197eecb6c07f46079153e6e6dcb63eef81ff5f` | `2026-10-03T02:23:02.403770Z` | F：严格显式长存储参数及签核前合成时效；只有此测试夹具文件发生 F 的本项代码变化 |
| [test_launch_storage.py](../../../../pdos-next/server/tests/test_launch_storage.py) | `bdceaeaa13d3abdffeb633d77e72980b9870e3663b1a0154de22f07f0cd18ef0` | `2026-10-03T02:18:49.467822Z` | C：仅首个长故障函数 indirect 45/60；各故障重新预览、取本次 baseline；其余两项孤立使用/预约用例保持默认 |
| [test_resources/test_transactions.py](../../../../pdos-next/server/tests/test_resources/test_transactions.py) | `e1ed6f45b7624600fbad72141f5d1baae26dd8add0dc286139d63b86545f4275` | `2026-10-03T02:18:50.541108Z` | A：手动默认调用加 `request=None`，兼容新 required pytest request，仍用默认数据；F 未编辑此文件 |

F 的变更 provenance：

1. 原真实时钟夹具基线为 `278d44528f773f2b2fa16fc6fdad56873413e3fc9ea685dbf029d28710277f1e`：start+5 / finish+12 / resource fact+20 分钟，真实等待。当前 [candidate.json](candidate.json)和[candidate-before-receipt-field-test-repair.json](candidate-before-receipt-field-test-repair.json)仍记录该 fixture 基线摘要，不是最终长夹具摘要。
2. 主线授权仅长存储函数显式 45/60 参数，F 首个参数 checkpoint 为 `85b65b04408d8093cea10519ba6c4a55a2ca709fba4443ae070fb827c75d4dd1`。这只延长 TestResourceFact 与具名 resource decision，不能单独满足上游原 Build/方法/专业证明的 25–40 分钟期限，因此已明确报告为未充分的中间 checkpoint。
3. 主线再明确授权仅同一长场景、在创建/签核前给合成 Grant/专业事实/Build T2 时效 120 分钟。F 仅在本文件增加局部包装，最终摘要为上表 `10e5c…`；不后改不可变专业或 T2 历史，不给生产端口默认正资格。

## 显式长参数与签核前时序

参数必须是 pytest indirect 的严格字典 `{"window_minutes":45,"fact_minutes":60}`，字段、整数类型和值全部精确匹配。额外字段、bool/float、任意期限、显式 null 或空字典均拒绝。上游 `ready_work` 从该测试 node 的 callspec 中精确读取 `launch_work` 参数，并先调用同一个校验器；客户端业务 payload 不能触发此测试配置。

长场景的顺序为：

1. 在调用原 `build_start.ready_work.__wrapped__`、首次专业事实导入与后续签核之前，对同 tenant/product 的既有 fixture human/peer Grant 和 LoginSession 设置足够 120 分钟期限。Grant 按真实数据库 UPDATE 推进 access epoch；不禁触发器，也不在旧专业签名之后补改权限。
2. 局部包装原 `authority_fact` 生成器，仅改变合成 `valid_until`，其他 scope、职责、操作、目的、来源及事实性质继续原生成器内容，真实 import 路径不变。
3. 局部包装原 `authorization_command`，在其 payload 进入共同 T2 预览/消费前将两项 Build 授权及逐项专业 applicability 的有效期设置为同一个 120 分钟期限。原两次具名 T2、完整范围、来源与 accepted API 办理均保留。
4. `accepted_work` 在上游品质 Grant/LoginSession 的构造入口设置 120 分钟；发生/接收时钟不变，不移动 `now`。计划/实际方法及样件 ready 继续真实办理、依据原专业和 Build 证明。
5. TestResourceFact 与设备/人员具名 resource decisions 的有效期为当前夹具时点+60 分钟。Run 窗口 start 仍+5分钟、finish+45分钟，全部当前来源、完整窗口资格和实际 Start 的生产校验继续运行。

`advance_clock` 仍以真实时钟等待到固定 start；无 Python 未来时钟 monkeypatch、SQL 时钟或触发器放宽。生产 Confirmation TTL、专业操作/角色矩阵、原件安全和资源算法均未改。

## 默认分支复核

缺显式 `launch_work` 参数时，新的本地 `ready_work` 只转交原生成器并保留其 yield/cleanup，不执行额外 SQL 或长时效 monkeypatch。`accepted_work` 不进入长分支；原品质 Grant/LoginSession 与原专业事实/T2 数据不变。`launch_work(request=None)` 或未参数化的 pytest request 仍得到 finish+12 / fact+20，start+5 与真实等待不变。破坏性样件仍从原 fixed item 的 `destructive` 读取，本项未修改该合同。

F 完成补丁时已做文件 scoped Ruff 与静态编译；仅抽取本文件函数作无数据库静态模拟，确认三种默认 request 形状都保留原 work/cleanup 且零新增 SQL/patch，八种非法参数拒绝。该检查不等于真实 PG 正例或最终长存储用例通过。本次只读复核没有重复运行这些检查。

## 已启动 storage 进程不能作为最终夹具证据

主线指定 PID `97082` 的只读 `ps` 结果：启动于本地 `2026-10-02 19:20:15`，即 `2026-10-03T02:20:15Z`；观察时运行约 4分41秒。最终 fixtures 文件 mtime 为 `02:23:02.403770Z`，比进程启动晚约 **167秒**。最终写入顺序与主线反馈的“进程先启动、后完成最终 fixture”一致。

pytest 模块在进程中导入后不会因文件修改自动替换已加载的函数。文件当前 hash/mtime、traceback 从当前文件读取行文本，均不能证明该进程实际加载最终 120 分钟夹具。现有证据没有进程内最终加载 hash，不能区分其是否用了原版或仅 45/60 中间版。

**判定：需由主线 fresh storage 进程以最终源码重新验证，现 PID 的结果保留为过渡候选日志，不计入最终长夹具验收。** fresh 运行前后应记录上述最终 source hash，并把 test-only delta 与原生产运行候选分开归档；不把历史或中间候选的通过拼成最终夹具通过。此结论不要求重跑无变化的全部生产检查。
