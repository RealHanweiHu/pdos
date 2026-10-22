# 最终报告与自有检查点收尾逻辑审查

本次仅只读 `pdos-next/.local/s0-finalize-report.py`、`s0-cleanup-owned-checkpoints.py` 与公开 final-candidate 证据，未读取 `.local/runtime.json`、其他 runtime 文件或私有凭据／备份内容。经主会话澄清，shell 仅用于 sed／nl／cat／rg 读取文件；未执行任何被审脚本、验证、PostgreSQL、pytest、迁移、计时或环境收尾。仅写此独占报告。

结论：已发现的 3 处真实证据门槛缺口均由主会话在 freeze 以外的 `.local` helper 修正，复读当前脚本已确认。未发现另外一项需要立即修正的具体错误。当前性能候选仍未完成：收到任务时 B4 约 21/30，主会话最后更新为 27/30；尚无全部性能通过与 cleanup 的实际证据，本审查不宣称 S0／M1 完成或脚本实际运行成功。

## 报告写入门槛

`s0-finalize-report.py:10–17` 在所有完成声明写入之前要求：

- 性能聚合 `all_required_groups_complete`、`all_thresholds_passed`，32 组各 30 个成功样本、0 failure 且各组 passed。
- pipeline 步骤严格为 short → b4 → b5 → b6 → summary，五步退出码均为 0。
- pipeline、冻结清单与 live `snapshot()` 的完整 SHA-256 映射一致，且 source_unchanged 为真。
- 通过冻结汇总器的 `require_junit` 再核对 B4／B5／B6 JUnit 的 30／1／1 个实际 case；公开既有 `0722-b6-performance-review.md` 明确该汇总器要求零 failure／error／skip、完整样本与有限非负计时、固定分组、nearest-rank p95。
- short／B4／B5／B6 四份 raw 证据的 source_sha256 与冻结清单一致。短路径是直接测量脚本，本来没有 pytest test_exit 字段；其 `.get('test_exit',0)` 由 pipeline 的 short 退出码 0 与聚合样本检查支撑，不将缺 pytest 字段本身视为缺陷。

因此完成声明不由日志点数、部分 raw profiler 或准备好 helper 触发。32 个具体必测标签、p95 数值与分档门槛来自冻结汇总器输出；此 helper 本身检查汇总完成／通过及组数，不另造一套统计口径。本次范围不重新审阅或执行汇总器源码。读取时最终 `performance/pipeline-status.json` 尚不存在，现状直接运行这些 helper 会在完成声明／stop 之前拒绝，不能把当前 B4 部分进度登记为成功。

`:18–29` 另外要求三个实际受影响／恢复报告退出码 0、source_unchanged，collector 为 exit0／collect_only=true／source_unchanged=true／freeze 相符，5274 个 unique 节点、独立 preproject 50、107 个模块且 S0 节点合计 5224。collection_scope 从这些实际字段构造，并明确 `is_pass_evidence=false`。空链和非空恢复的 0722 head／结果均在写报告前核对。

`:30–37` 要求 root-reviewed 非 draft 的 failure ledger、原 417 个失败／错误精确处置为 382 实际复验＋35 接口退役、两个 pending 分组均 0，原始全量计数精确 4839P／368F／49E／1S；同时要求实际 cleanup 的 passed、main/shared/private-backups preserved 和最终 diff-check 空日志。

`:44–46` 在写 `s0-acceptance-map.json` 前检查八项判据对应证据存在；`result.md` 在上述门槛后生成（`:65`），source-delta-coverage 的最终性能状态也只在此后 promotion（`:66–68`）。helper 并未提前将 performance pending 改为完成。既有功能／源码覆盖由所链接的独立证据支撑，未把存在一个 Markdown 审查文件称为业务实测。

## 报告事实与范围

公开 `full-regression-results.json` 的原计数为 4839 passed、368 failure、49 error、1 skipped，合计 5257。failure-closure-map 的原失败 417、实际闭合 382、旧接口退役 35、pending=0 与当前 helper 的 assertions 一致。报告保留原失败／错误与后续诊断，并明确“未执行第二次当前候选全量通过”；35 退役接口不被伪装成重测通过。

`0722-current-collection-fixed.json` 实际 exit0、collect_only=true；静态精确节点计数 5274，其中 `tests/preproject/` 50；`module-regression-coverage.json.current_collection_totals` 为 all=5274、s0=5224、m3_excluded=50、modules=107。报告把独立 M3 排除，并明确 M2／M3／S1 新能力、真实资格和生产启用另行验收，collection 不是 pass。

既有 `0722-affected.json/.xml` 为 165 项通过（153 纯、12 实库），删除未使用 conftest 导入后的 `0722-request-prepare-fixed.json` 为两个品质事务节点 setup／call／teardown 均通过，`0722-recovery.json/.xml` 为 1 个实际恢复节点通过。报告明确较早 165 候选的测试导入差异，并以最终两项与 collector 对应冻结，不冒充 165 项全部在最终导入调整后重跑。

非空恢复使用 `0722-checkpoint/backup-restore.json` 的实际事件数量；`:43,61` 动态读取 delivered。该证据当前为 delivered=2、unknown=0，两个 metadata-only claim.recorded 事件；`configuration-handoff-recovery.json` 为 0 workflow／0 external_sends、公开回读与原 Start 零新增效果。142 张表指纹及六个非空链表与既有实际恢复一致，没有引用上一 0721 的 5 个事件。合成原件字节保留重读，范围明确为数据库恢复。

性能文案按本地认证 ASGI、排除网络／setup、同步发布包含真实主体与 commit，客户端 SQL 不展开 PostgreSQL function／trigger。B0 对比表读取 comparable_b0 的同口径 p95 和 app＋auth SQL 范围；历史单次长延迟／失败发布的聚合 SQL 仅作诊断。32×30＝960 和全部门槛通过的文字只会在完整性能 gate 后写入，不是当前状态。

## 自有检查点收尾范围

`s0-cleanup-owned-checkpoints.py:11–17` 在任何 Docker／数据库操作之前，要求相同的 32×30、全部门槛通过、完整五步 pipeline exit0，以及 pipeline／freeze／live snapshot 完全一致；已有 cleanup.json 时拒绝重复收尾。最初仅信 `source_unchanged` 字段的缺口已修正，不会先停止环境、再让 finalize 才发现当前源码漂移。

`:25–31` 验证 main 端口 53502 并保存其 container_id／marker；待停止范围是三个固定自有 runtime 文件与对应 purpose：

- `s0-b8-runtime.json` → s0-b8-checkpoint；公开升级／恢复证据为 B8 62303。
- `s0-b8-empty-runtime.json` → s0-b8-empty-chain-0721；公开空链证据为 59006。
- `s0-b8-empty-0722-runtime.json` → s0-b8-empty-chain-0722；公开空链证据为 61319。

每个目标先调用既有 `local.verified(local.read_state())`，核对 purpose，并要求 container_id／marker 均不同于 main。此审查只看调用与固定目标，不读取私有状态或重新验证其真实身份；脚本正式执行时仍必须由该已有 verifier 核对实际目标。没有遍历所有容器、compose down、删除卷、停止共享服务或 M3 的操作。

`:32–46` 仅读取目标 Alembic head，先为目标 pdos_test 做新的 custom-format pg_dump。备份／私有诊断为 exclusive create、0600，dump 退出码非零或文件为空就拒绝 stop；保存 SHA-256，再核验目标、stop、检查已停止容器的 ID 与 marker。只停止容器，保留恢复卷；不覆盖已有私有备份或失败证据。

`:19–24,47–50` 对共享 agent-state／SearxNG 保存并比较前后 container ID／running 状态，对既有 Temporal start-dev PID 只读盘点并要求原 PID 仍在；main 再验证 ID／marker 相同。只有三个目标均完成备份／stop，且 main／共享保持核对通过，才写 passed cleanup.json。M3 不在 stop 目标中；保留声明以固定自有文件／purpose 的实际核验为边界，不凭本审查推测所有未来独立环境。

## 审查中修复的缺口与尚待实际完成

主会话已修正并经本次复读确认：

1. cleanup 停库前缺少 live source／freeze 比对及每组 30／0failure gate；现为 `cleanup:14–16`。
2. finalize 读取 closure 却硬编码已闭合数字；现为 `finalize:30–35` 的真实账本 assertions，acceptance 从 ledger 字段构造。
3. collector 仅检查 source、未检查 exit／完整节点与 M3 边界；现为 `finalize:20–26` 的实际 collector flags、unique nodes、50 个 M3 与模块合计核对。

尚待主会话串行完成最终 B4／B5／B6 采样、完整汇总/JUnit/source gate、实际自有环境备份停止与 cleanup 证据，然后才运行 finalize 并核对生成报告。当前 helper 的静态逻辑通过不等于这些操作已经完成；本次没有提出重复全量、并行实库或扩大到其他环境的验证要求。
