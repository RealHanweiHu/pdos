# D56 按权限导出 Excel（2026-11-08）

worktree `xenodochial-tharp-12e9c0`，分支 `claude/xenodochial-tharp-12e9c0`，基点 `pdos-next/design-v1.1` @ `38f5a024`。本地提交，未推送。所有验证都在 `tools/local_environment.py create` 建的隔离 `pdos_test`（127.0.0.1 随机端口、带标记）上进行，没有调用模型，没有连其他库。

## 结论

- 四类视图（项目、我的工作、BOM 差异、测试汇总）可导出 Excel。每类直接调用对应页面的读取函数，行和字段的过滤与页面相同。
- AI 写入或 AI 起草、人确认的行标“AI 起草”。人改过的字段转为人工，行标“部分 AI 起草”，AI 起草的单元格带批注，并在“AI 起草字段”列列出。封面写明行数和 AI 行数，文件带隐式元数据（自定义属性 `AIGC`、`PDOS.*`）。
- 每次导出写一条只追加的审计（`export_audits`），审计未落库就不交付文件。AI 身份、运行和代办上下文都不能导出，服务端和数据库两层都拒绝。
- 讨论导出（P34 未实现）、Word/PPT 模板导出（D185）、真实小Pai 运行的端到端标识、合规核对等余项见清单 D278–D283。

## 设计口径

- 依据：优化评估 F41（四类视图、按读者权限过滤、保留 AI 标记、记审计）；拍板表 C16（导出保留“AI 起草”并记审计，对外导出带标识元数据，不需决策记录）；确认稿 P41 第 7 项（讨论导出并入 D56）、P82 的 D185 行（模板导出单列）。
- 操作登记：v1.1 附录 A 增一段，`contracts/auxiliary-operations.json` 增 `export.workbook.download`（READ、`named_human`、4 个 GET）。
- 导出定为读者本人的 READ，不经系统向外发送。DC-11 §7 的“客户报告外发”仍是 T2，不在本操作内。两点未自行决定，记为 D281：是否单列“对外导出”并加审批；隐式元数据是否满足 GB 45438-2025。

## 验证

| 项目 | 结果 | 说明 |
|---|---|---|
| `tests/exports`（PG + 纯函数） | 10 通过 | 见下表 |
| 前端全部 `.mjs` | 1895 通过 | 新增 `route-export.test.mjs`（BFF 白名单）、`export-download.test.mjs`。两个组件测试按原有方式桩掉导出按钮 |
| `tsc --noEmit`、`eslint src` | 通过，0 错误 | 1 个既有 warning（`external-wait-route.test.mjs`） |
| `tools/validate_contracts.py` | 通过 | 87 operations / 92 events / 67 acceptance |
| 迁移往返 | 通过 | [migration-roundtrip.log](migration-roundtrip.log)：有审计历史时降级被拒；清空隔离库测试行后 s0_0861→s0_0855→s0_0861 两轮通过；策略、FORCE RLS、`pdos_agent` 无写权限、应用角色只有 SELECT/INSERT |
| 后端受影响 PG：`tests/core` 等 158 项 | 153 通过、5 失败，5 项均为既有 | 4 项在基点代码上同样失败（用 `git archive 38f5a024` 在同一隔离库复跑）。`test_migration_matches_orm_and_test_guard` 的差异全是既有的钉钉索引和检索向量索引，`export_audits` 无差异 |
| 后端无库全量 | 无新增失败 | 与基点逐项对照，见下文“无库全量对照” |

`tests/exports` 明细：

| 测试 | 覆盖 |
|---|---|
| `test_project_export_matches_page_for_two_roles_and_hides_private_project` | 负责人与只读成员两种角色：导出行数等于页面读取。私有项目：两个受众外成员（一个有写权限、一个只读）得到与页面相同的 403，不产生审计。跨租户被拒，多余参数 422。公式样文本按文本写入 |
| `test_my_work_export_reads_personal_queues_and_audit_is_private` | 六张表与页面队列总数一致；审计只有导出人本人可读 |
| `test_ai_identity_and_delegated_contexts_never_export_or_audit` | AI 身份（代办或本人）、`agent_run_id`、`run_id` 上下文都返回 FORBIDDEN_SCOPE；以 AI 身份直接写审计被数据库拒绝；审计不可改 |
| `test_ai_drafted_rows_and_fields_reach_the_workbook` | 真实版本行上的字段级判定：整行 AI 起草，以及 AI 分派后的“部分 AI 起草（状态、执行人、验收人）”；批注、封面、`AIGC` Label=1、审计计数。未打桩的 `Provenance` 识别真实 agent 主体 |
| `test_bom_diff_export_uses_get_bom_on_both_sides_and_private_bom_stays_private` | 第 2 版对第 1 版的行级差异，首版全部列为“新增”；只读成员看不到私有 BOM，导出 403，不产生审计 |
| `test_test_summary_export_matches_current_runs_and_measurements` | 当前运行 1 条、测量值 2 条与页面一致；跨租户被拒 |
| `test_workbook.py` 4 项 | 标识、计数、隐式元数据、公式与控制字符、空视图 |

## 浏览器

本 worktree 的 API（8961）和 `next dev --webpack`（3961）连同一隔离库。测试数据由现有命令夹具创建：G0 项目、2 个任务、BOM 两版、只读成员。

- 亮色：我的工作导出（[截图](screens/light-my-work-export.png)，0 行，与页面一致）；项目任务“更多 → 导出 Excel”（[截图](screens/light-project-tasks-export.jpg)，“已导出 2 行，不含 AI 起草内容”）；BOM 第 2 版“导出与上一版差异”（[截图](screens/light-bom-diff-export.jpg)，3 行）。
- 暗色：项目任务导出（[截图](screens/dark-project-tasks-export.jpg)）、BOM 差异导出（[截图](screens/dark-bom-diff-export.png)）。
- 控制台无错误。
- 浏览器内下载的文件不便直接取出，所以用同一前端代理和同一会话 cookie 再取一次，存到 [xlsx/](xlsx/)。用 openpyxl 打开核对，记录在 [browser-bff-exports.json](browser-bff-exports.json)：
  - 项目：负责人和只读成员各 2 行，来源均为“人工”；
  - 我的工作：负责人 0 行，peer 的“待我接收”1 行；
  - BOM 差异：1 条差异加 2 条修订信息；
  - 只读成员导出私有 BOM 得 403，多余参数得 422；
  - 每个文件的 sha256 都与审计行一致。
- 带 AI 标识的样例：[xlsx/project-ai-drafted-sample.xlsx](xlsx/project-ai-drafted-sample.xlsx)，由字段级判定测试导出，包含“AI 起草”“部分 AI 起草（状态、执行人、验收人）”、单元格批注、封面提示和 `AIGC` Label=1。
- 测试汇总的导出入口没有在浏览器里走（浏览器数据里没有 Build 和结果），由 PG 测试覆盖。

## 无库全量对照

在同样条件下（不设数据库变量），分别跑基点 `38f5a024` 的 `git archive` 副本（不含 `web/`）和本分支，比较 FAILED 集合，结果见 [nodb-compare.txt](nodb-compare.txt)：

- 基点 171 失败，本分支 169 失败。PG 用例在无库时为 ERROR，不计入。
- **本分支有而基点没有的失败：0。** 基点多出的 2 个来自副本缺 `web/`，或属于时序波动。
- 第一次运行时，新表让两个生命周期目录对照测试失败，已在 `originals/lifecycle` 登记 `export_audits` 修复。
- 这 169 个都是既有失败，基点尚未合入 D27 的测试债修复（D27 记录的修复前基数是 169）。

## 未验证

- 真实小Pai 运行写入的行（D280）。
- 测试汇总在浏览器里的点击（PG 已覆盖）。
- 隐式元数据的合规性（D281）。
- 集成分支上的迁移重排与全量回归：本分支迁移号是占位 `s0_0861`，down 为 `s0_0855`。
