# W6 D37 ⑧ / W8 D117 · 资格评测集、按运行指标自动降级、抽检与 AI 价值指标（2026-11-09—11-10）

分支 `claude/epic-chatterjee-780576`（worktree `epic-chatterjee-780576`），基于主线 `c13c3fd6`。本地提交，未推送。
用户 11-09 拍板见确认稿 [P109](../../../design/2026-10-08-pdos-next-design-confirmation.md#p109)、[P110](../../../design/2026-10-08-pdos-next-design-confirmation.md#p110)。

## 结果

| 项 | 状态 | 位置 |
|---|---|---|
| AI 价值指标（D117）：撤回率、人工修改率、草稿保留率、原样保留率，按“租户 × 技能包 × 模型版本”，只读 | 完成 | `server/pdos_next/agent/kernel/skill_quality.py`，`GET /v1/categories/{c}/agent-skill-quality` |
| 自动降级：撤回率 >5%（所有 T0 技能），人工修改率 >30%、框架检查失败率 >10%（只 `work_management`），窗口不满 N/A；降级记录与依据运行；恢复只经 `ai.skill.qualify` 且用降级后的审阅 | 完成；两项计划指标的数据源待 W6 ②③（D410） | 迁移 `s0_0890`、`s0_0891`；`policy.qualified`；`core/run_revert.py` |
| 抽检（P42）：哈希 20%，每周补足到 min(2, 当周 T0 数)；`ai.skill.spot_check.record`（T1） | 完成 | `skill_quality_records.py`，设置页“抽检复核队列” |
| 资格评测集：`ai.skill.eval_set.register`（T1），审阅可引用评测集案例；不授予资格 | 完成 | `skill_quality_records.py`、`skill_qualification.py`，设置页“资格评测集” |
| 通知：技能资格页置顶“待复审”，“技能与资格”子标签带计数；接通知中心与 outbox 事件留到 W6 ⑥、W7 合并后（D413） | 部分 | `skill-quality.tsx`、`platform-settings.tsx` |
| 判据：AT-64–AT-66 写入 v1.1 附录 B 与 `contracts/acceptance.json`；两条命令登记附录 A 表下与辅助操作合同；§06.12 加注指向 P42 | 完成 | v1.1、`contracts/` |

## 不经模型、AI 零写权

- 指标与降级判断全部来自数据库函数对执行账本（`agent_tool_calls` 中已完成的 `domain_t0` 调用）、回执、`agent_runs.reverted_at`、单条撤回回执和之后人的正式改动的确定性计算；阈值和窗口在代码里（P41 值），数据库里不冻结技能包或阈值。
- `kernel_skill_quality_hold` 写降级记录前自己重算：窗口不满或未越线即拒绝，关键错误必须有已记录的抽检标注；调用方传不进事实。
- 三张新表只追加；`pdos_agent` 无任何权限，应用角色对降级表无 INSERT；读取只给当前租户管理员本人（不加锁的谓词，可在只读快照里读）。

## 验证

| 检查 | 结果 |
|---|---|
| 新 PG 用例 `test_skill_quality_pg.py`（7）、`test_skill_quality_records_pg.py`（5） | 全部通过 |
| 受影响 PG 范围（隔离 `pdos_test`，11-10）：上述 12 个 + 资格、技能启用、执行绑定、运行撤回、命令用途目录、命令目录、ORM 与迁移比对、原件生命周期表目录、证据撤回、定义者归属 | 175 通过、0 失败（21 分钟）；PG 全量留给集成统一跑 |
| 迁移往返 `s0_0869 ↔ s0_0891`（空表） | 通过；有记录时降级被拒（保留记录） |
| 合同：`tools/export_contracts.py` 只增不删（openapi +279 行、payloads +245 行）；`tools/validate_contracts.py` | 通过：87 operations、94 events、70 acceptance |
| 前端：`next typegen && tsc --noEmit`、`eslint src/features/settings src/app/api` | 通过（1 条既有警告，非本次） |
| 前端：设置区 `.test.mjs` + BFF 路由 `route.test.ts`，设置区 `.test.ts` | 164 + 21 通过 |
| 浏览器（webpack 开发服务，隔离 `pdos_test`）：亮色桌面、暗色桌面、暗色 375px | 见 `screens/`；375px 无横向溢出 |

### 浏览器走查

- 合成种子（脚本只在草稿区，不入库）：预览租户登记为管理员和试点，`public_research` 的资格行以关闭触发器的方式写入（模型未配置，所以页面显示“模型 未登记”）；20+20 次合成 T0 运行经真实运行存储写入，2 次经真实撤回戳记撤回，`record_breaches` 由数据库写出一条撤回率降级。
- 页面：“技能与资格 · 1 待复审”计数；置顶“待复审”列出技能、2/20、阈值、资格负责人、依据运行；指标面板显示撤回率越线、人工修改率与框架检查 N/A、价值指标表。
- 在浏览器里实际提交：抽检标注一次普通错误（回执 `408620d6…`，人工修改率随之从 0/40 变为 1/40），登记第 1 版评测集（回执 `8277596b…`，覆盖 0/2）。
- 截图：`screens/light-desktop-holds-banner.jpg`、`light-desktop-metrics.jpg`、`dark-desktop-holds-banner.jpg`、`dark-desktop-metrics.jpg`、`dark-375-holds-banner.jpg`、`dark-375-metrics.jpg`。

## 余项

D410–D417，见[清单 W6 段](../../../../tasks/ai-native-integrated-todo.md)。

## 集成注意

- 迁移占位 `s0_0890`（down `s0_0869`）、`s0_0891`（down `s0_0890`），按真实 head 重排（11-10 第五轮集成改为 `s0_0874`、`s0_0875`，接 `s0_0873`）；`schema_s0_0891.py` 从 `schema_s0_0890` 导入事实函数原文做替换和还原，改号时两边模块名一起改。
- 核心文件小改：`core/run_revert.py`（撤回后记录降级）、`core/models.py`（回执按对象索引）、`core/command_handlers.py`、`core/contracts.py`、`core/service.py`（两条命令与事件登记）、`originals/lifecycle/catalog.py`（三张表与 `eval_set_id`）、`agent/kernel/command_usage.json`（两条，已写何时调用）。
- 前端共用文件：`web/src/app/api/[...path]/route.ts` 只改了 `skillQualification` 一行正则和本分支的查询校验；`platform-settings.tsx` 只改“技能与资格”标签文字。
- 合同：v1.1 改了附录 A（表下段落）、附录 B（三行与附注）、§06.12 一句，`contracts/*.json` 的 sha256 随之更新；`openapi.json` 是整份重导出，集成时按真实 head 再导一次。
