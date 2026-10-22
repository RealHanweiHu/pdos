# s0_0722 B6 性能采样方法只读核对

结论：当前 B6 工具的六条采样路径使用真实 HTTP 或受信宿主领域入口；覆盖发布计时包含完整同步 importer 主体及实际事务 commit。没有发现需要先修改工具才能进行标准正向采样的方法缺陷。这里确认的是静态调用范围，未执行 PG、pytest 或计时，不构成 B6 功能或性能通过。

## 1 case / 六组各 30 样本

`pdos-next/tools/checkpoints/b6_performance.py::test_actual_capture_impact_and_coverage_publication` 是一个 pytest case，先对同一固定 Build 执行 30 次当前制造资源读取，再循环 30 次 `fresh_sample`。每次分别创建新的 Impact Change 和新的 Coverage Publication Change，得到 30 个独立 Impact 主体和 30 个独立发布主体；它们共用一个 tenant、项目及既有 Issue/CAPA/Run/实物事实。不能写成“30 个独立完整夹具”或“30 个新租户”。

| 分组 | 实际入口及计时范围 | 业务成功校验 |
| --- | --- | --- |
| manufacturing_resource_read | 已认证 HTTP POST resources/inspect，完整实际资源 owner 读取 | current=true、known、fact/来源/relations 非空，并含指定当前资源 |
| change_capture | 已认证 HTTP POST captures；prepare_capture 保存真实 ChangeGraphCapture，路由 tenant_session 退出时提交 | capture 与 impact_payload 存在；后续实际 inputs/Impact 继续验证固定图 |
| change_impact_inputs | 已认证 HTTP POST change-execution/inputs；真实范围、专业和来源证明 | allowed=true、完整必需来源读集非空 |
| change_impact | 已认证公共 commands POST，包含领域事实及共同原子组的实际提交 | subject_revision=2 |
| change_impact_replay | 再次发送原 Impact 命令，包含真实 HTTP/UOW 结束 | 返回同一原 receipt id；不混作新的 Impact 提交样本 |
| coverage_publication | 宿主 `publish → tenant_session → importer.trusted_import`，同步完整调用及提交 | 指定 operation/family、revision=1、receipt id 未出现过 |

`http_measure` 使用 `s0_performance.measure` 包住完整 TestClient 请求：计时结束发生在 HTTP 返回后，HTTP 200 和业务校验全部成功才标记样本 success。发布的 `publication_measure` 包住完整 callback：`publish` 虽在 with 体中 return，但 Python 必须先退出 `tenant_session` 的 `session.begin()` 并完成 commit，callback 才返回；commit 异常也不会产生成功样本。发布不是 HTTP，auth_sql_count=0 表示已有宿主 Context 的领域调用，不能把其 p95 描述为含登录认证的 HTTP 发布时延。

工具要求每组恰好 30 条 success、六组齐全、30 个不同发布 receipt、最终 outcome=passed。汇总器还要求：B6 JUnit 恰好一个无 error/failure/skip 的 case，profiler test_exit=0、源码未漂移、与同候选短路径 source manifest 完全相同；每组 30 条成功、有限非负计时及 SQL 次数，p95 沿用 nearest-rank。单个失败、未完成或部分样本不能冒充最终通过。

## 八个 facet 发布的完整同步边界

每个发布使用单独的新 Change 固定原版和额外实际 graph capture。CoverageMaterial 明确列举 engineering、manufacturing、evidence_applicability、in_process_builds、customer_samples、supply_inventory_wip、production_switch、training 八个 facet；每个 facet 都列举该固定 graph 的全部节点，并为每个节点登记准确 object unit。

`CoverageMaterial.closed` 验证八 facet 集合、逐 facet 节点无重复且恰好等于总节点集、roots 属于闭包、逐节点 object unit、非空真实有效区间。发布原件经真实 `evidence.artifact.register` 保存完整规范 JSON，SourceRef 固定 line:1 与全文 SHA；`trust.configure` 登记 exact original/material pin。该声明明确是合成夹具的八 facet 整体枚举，不能作为真实生产/库存/客户/培训范围完整证明。

计时内的真实 importer 包含：固定 Product/UOW、当前 caller/项目/具名专业权威、原件完整读取和精确 pin、固定 Change origin binding、当前依赖水位/时间戳、真实 OwnerReader 闭包及来源集合、closure SHA 和准确节点集比对、来源安全与受众、幂等冲突及 Current/previous 校验、CoverageFact/Current 实际写入、receipt/audit/outbox/request-key 完整共同原子组、full flush 后的 issuer/runtime/current/binding/专业/caller/时间戳/水位/真实期限末端校验，以及 with 退出后的数据库 commit。没有把领域主体交给后台任务后提前停止计时。

SQL 计数是此 app Engine 的 cursor 事件；事务 commit 的壁钟在 elapsed 内，但驱动 commit 和数据库内部触发器子 SQL 不会自动变成独立 cursor 计数。不能把 app_sql_count 当成 PostgreSQL 内部执行语句总量。

## 明确排除的准备成本

初始 `change_work` 建立真实配置、Build/实物/交接、Run、测量原件/固定失败结果、Issue/CAPA、当前质量与变更专业凭据及策略，均属于初始 fixture setup。

每个 `fresh_sample` 另外排除以下工作：

- Impact Change 的 create-inputs 和 create commit；Impact 的 measured capture 之后，`cmd` 命令 JSON 组装也在计时外。
- 发布所用第二个 Change 的 create-inputs/create commit及额外 graph capture。
- 宿主原件准备事务：`current_fixed`/request snapshot、`fixed_seed`、`owner.inspect_basis` 的完整实际 registry/closure 读取、CoverageMaterial 组装，以及该准备事务退出。后续 importer 仍在计时内重新进行完整必要发布证明，准备事务没有替代发布主体。
- 发布原件的真实 artifact register、规范 JSON/SHA 制备、宿主 issuer/original pin 配置、command/request-key 生成；发布后的 trust.disable 也不计入。
- success 业务断言及 samples JSON 保存。

因此 coverage_publication 是“原件和发布申请已准备好的完整同步发布命令耗时”，不包括从新 Change 到完备发布原件的整段用户流程。B6 的 raw profiler `b6-change.json` 会记录测试 call phase 中这些额外准备 HTTP/SQL；最终性能必须取 `heavy-change-samples.json` 的明确计时区间，不能把 raw 全部 call-phase 聚合与该样本 SQL 范围混用。

## 真实期限：当前读取与 retained 历史分开核对

当前工具没有间接参数化 launch_work，使用普通夹具 Run 窗口 12 分钟、TestResource 事实 20 分钟。fixture 在实际 Start 前短暂固定已发生计划时点，随后 `advance_clock` 恢复真实 UTC；B6 循环中的成功动作没有冻结时钟，也没有更新已保存期限。

首段 30 次 manufacturing_resource_read 是当前资源读取：`manufacturing_resource_owner._material` 明确要求 `clock() < execution.window.finish`，其 `work.scope` 的 Build operational 窗口为创建时点后 20 分钟，还保持 fact.valid_until、当前 issuer、资产/来源和 caller 期限。因此不能用结束后的历史读取替代该组成功。按单次约 ≤1 秒的常规请求估计，首段约 30 秒加短准备，当前没有依据要求扩大窗口；p95 门槛本身不约束最大值，真正异常长的单次或累计停顿仍须按实际期限判定。

后续 Impact/发布的旧 TestRun 属于 retained 证据：`OwnerReader.resolve(test_run)` 和 Issue/CAPA 固定失败 bridge 都调用 `inspect_retained_execution`，按 `original.created_at` 核对原签署权威/资源与完整固定原开测证明；末端仍核对当前 reader Grant/运行时/来源。`execution_window_elapsed` 只是诊断，closure basis 显式排除该值。故不能断言默认 12/20 分钟过去就会使后续新 Change 动作失去资格，也不能把旧 Run 期限延长为当前新开测权。

新 Change 的当前具名权威来自 change_work 独立导入的两小时 Change 专业凭据。每个发布原件的有效期是本 sample 的 fresh graph.captured_at 后一小时。当前 Grant/Login 仍有约 45–60 分钟的实际边界；publication 的 registry future deadlines、当前权威/成员时间戳及最终 earliest_deadline 全部保留，当次事务跨越真实边界应失败。两小时专业凭据或一小时原件不会延长成员会话期限。

现有材料不要求重建 30 个完整 fixture，也不要求改 B6 工具。长跑若真的失败或过期，应保留失败和部分样本，恢复原因后重新冻结；不得修改已经存储的期限、放宽原件/来源/专业守卫、把失败标成 success 或改变阈值。只有确需更长合法夹具时，才能在所有签署前采用既有 45/60 分钟测试参数；它也不会自行扩大 Build operational 20 分钟窗口。本核对不建议现在进行该调整。

核对时静态指纹：b6_performance.py `61fed3084bbe39a4804ccbde374f8341ac513d15c1e1bc5e923ca8b10be66b3f`；s0_b8_performance_summary.py `e9d715f0fe54a186a58b418e84cf38ee4571d6347fa778dbb0ddc9886f506153`；共享 publish helper 文件 `f3f9a9e16abfa2e5ecdaaf45ebff9e159a5806720553c3c8142d1779b5c1d758`；coverage importer `b44413c4f072afe8cb433ccafd694d7eaff2916febcbae8d9ea576542d5bb58f`。指纹用于界定审阅源码，不是实际测试或计时通过。
