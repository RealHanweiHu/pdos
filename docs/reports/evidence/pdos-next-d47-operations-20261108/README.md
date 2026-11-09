# D47 未实现操作：两条闭环落地，十条待定（2026-11-08）

分支 `claude/elastic-noyce-fad368`，基点 `pdos-next/design-v1.1` 的 `d6abcbf2`（迁移 head `s0_0861`）。本地提交，未推送。

- 12 条 `not_implemented` 的逐条盘点见 [inventory.md](inventory.md)。清单原写 14 条，其中 2 条在 11-01 之后已以接口方式实现。
- 本次实现 2 条：`supply.commitment.record`（T0）、`work.forecast.refresh`（T0，确定性引擎）。
- 其余 10 条设计不完整或有冲突，没有自己定口径，分别登记为 D305–D312；规格冻结归 W6 的 D36。

## 1. 供方承诺登记 `supply.commitment.record`（T0）

依据：v1.1 §03.5、§04.10、§05.5，AT-20；拍板表 §5.3 F25（设计已覆盖、排期即可）；F15 本人陈述作来源（§5.2，按 v1.1 改回，不是新口径）。

能做的事：
- 一条承诺是独立的版本链：建立、改期改量、关闭、重开，历史全部保留，可为 D199 供方画像积累数据。
- 绑定固定 Build 和它固定需求里的真实物料。供方只记外部标识，不建供应商实体（P87 第 9 项）。
- 来源二选一或并用：具名本人可写本人陈述（`time_basis=human_recorded`）或引用原文行；小Pai 只能引用原文行（`source_claim`），而且须有当前 T0 资格与绑定运行。
- 检查日 = 承诺日 + 1 天（F25）。到期仍未关闭的承诺进“我的工作”外部队列，注意项是只读投影，不另建待办，原因写明“不表示违约，也不表示未到货”。
- 承诺不计入库存与齐套（AT-20）；齐套仍只按供给快照计算。供应面板按 BOM 行三列显示需求、承诺、实到。
- 维护人：建立人、Build 负责人或项目负责人。

入口：
- 命令：`POST /v1/categories/{c}/commands`，T0 直接写，不开放人工预览。
- 读取：`GET .../products/{p}/builds/{b}/supply-commitments`（按行视图与历史）、`GET .../products/{p}/supply-commitments/{id}`。
- 前端：项目 → 产品与工程 → 物料齐套 → 维护记录与专业办理 → 选 Build，右栏“供方承诺（声称）与实到”。可登记、改期改量、关闭、重开。
- 技能包：`build_execution` 升到 0.1.3-draft，加入 T0 工具和用法说明。

存储（迁移占位 `s0_0868`）：
- `supply_commitment_versions` 只追加，`supply_commitment_currents` 是当前指针。
- 读写都跟随 Build 的可见范围（行级安全）。
- 提交时有两道约束触发器：每个版本必须绑定同事务的公共回执，人工版本是本人陈述或本人引用，AI 版本必须有绑定运行和原文行；当前指针只能单步前进。
- `pdos_agent` 没有任何权限。挂上原件生命周期的两个通用触发器，并登记到 `COVERED_COLUMNS` 和 `GUARDED`。

## 2. 预测重算 `work.forecast.refresh`（T0，确定性引擎）

依据：v1.1 §03.5 四种时间分开、I08；P82 D181（关键路径与浮时、延期只传给受影响的后继）；P58（预测晚于承诺只显示差异）；P41 第 10 项（工作日历接通前标“未扣节假日与停线”）；P66（单列“系统重算”，不可撤回，不算小Pai 动作）；AT-18、AT-19。

能做的事：
- 读当前已应用计划的固定输入（工期上下限、依赖、日历），再读关联计划任务的工作任务的实际开始与提交时间，用现有的 `projects/planning/engine` 计算区间、浮时和关键路径。
- 已完成的任务按实际时间固定，并在实际完成时放行后继。计划依赖都是零间隔 FS，所以这是等价化简，没有改动共享引擎。
- 只写新的预测记录和项目当前指针；计划版本、计划任务、基线和承诺都不变。与计划排期、与承诺的差异只做显示。
- 信息不足时给未知或区间：没有工期上限、已开始但缺剩余工期，都不补日期。
- 意图指纹绑定服务器算出的输入摘要（计划、事实、承诺、日历当天）。同一天输入不变，重放原回执；输入变了必须带新摘要，否则返回 VERSION_CONFLICT，并在 detail 里附当前摘要。
- 活动记录里单列为“系统重算的预测”。

入口：
- 命令：`work.forecast.refresh`，参数为 `project_id`、当前 `plan={id,revision}`、`expected_input_sha256`。
- 读取：`GET .../products/{p}/projects/{project}/forecast`，返回当前预测、下一轮输入摘要和最近 20 次记录。
- 前端：项目 → 计划，“计划 vN 已应用”下方的“预测（系统重算）”面板，有“重算预测”按钮，并显示与计划比的偏移、浮时、关键路径和承诺对照。
- 技能包：`work_management` 升到 0.1.3-draft，加入 T0 工具和用法说明。

存储（迁移占位 `s0_0869`）：
- `work_forecast_refreshes` 只追加，`work_forecast_currents` 每个项目一个指针。
- 读写跟随项目的可见范围。提交时约束触发器检查回执绑定、执行人（本人或绑定运行）、是否为当前计划，以及当前指针单步前进。
- 结果只含计算时间、任务键和标识，不复制来源内容，登记为非消费表（`NON_CONSUMING`）。

## 3. 验证

| 项 | 结果 |
|---|---|
| 供应承诺 PG（`tests/manufacturing/test_supply_commitments.py`） | 6 项通过：本人陈述建立与回执/审计/事件；不进快照与齐套；重放、新键同意图、同键异载荷冲突；改期、关闭、重开与版本链；“我的工作”检查日；越范围物料、过期 Build 版本、私有 Build 对同事与他租户不可见、缺读集、错行、AI 无绑定运行被拒且零写入；数据库只追加、伪造版本在提交时被拒、`pdos_agent` 无权限 |
| 供应承诺规则（`test_supply_commitment_rules.py`） | 8 项通过：检查日、未知日期、AI 不能用本人陈述、维护人限制、关闭后须重开、载荷形状 |
| 预测重算 PG（`tests/projects/test_forecast_refresh_pg.py`） | 3 项通过：只写预测、计划预测、项目版本、当前计划和承诺数都不变；未知工期保持未知；重放与新键同意图；过期摘要和旧计划版本返回 409；真实开工后输入变化，“已开始、缺剩余工期”保持未知，版本链与指针前进；他租户不可读写；数据库只追加、指针不能删、`pdos_agent` 无权限 |
| 预测合成纯函数（`test_forecast_refresh_compose.py`） | 5 项通过，含 D181 固定案例：A 延 6 天、B 延 3 天时只推后各自的后继；C 延 3 天被浮时吸收；关键路径只有 A→X；未知不编日期；实际完成放行后继；预测晚于承诺只显示差异 |
| 合同 | `tools/export_contracts.py` 后 `validate_contracts.py` 通过；`operations.json` 中这两条变为 `implemented_local_slice`（`not_implemented` 由 12 降为 10）；OpenAPI 只新增 3 条读取路径 |
| 迁移 | 升到 `s0_0869`；`s0_0869→s0_0861→head`、`head→s0_0868→head` 往返通过；有预测记录时降级被拒（“Forecast refresh history requires s0_0869”） |
| 受影响的公共 PG | 生命周期目录覆盖、原件生命周期、我的工作、项目活动、命令目录与调用须知共 371 通过。2 项失败均与本次无关：ORM 对照的 7 处既有索引差异（钉钉摘要、企业检索向量索引，无本次的表）；`test_personal_views` 全库回执计数与并行浏览器种子重叠，单独重跑通过 |
| 无库全量 | 10770 通过，1 失败：`tests/agent/kernel/test_source_views.py::test_get_only_router_uses_current_context_and_read_snapshot`，在基点 `d6abcbf2` 源码上同样失败（登记 D313） |
| 前端 | `.mjs` 1924 项、`.test.ts` 752 项全过；`tsc --noEmit` 无错；eslint 0 错误（4 条警告在既有测试文件） |
| 浏览器 | 合成种子（同一隔离租户）：“我的工作”出现两条供方承诺跟进项；供应面板按行显示需求、承诺、实到，在页面上真实办理一次改期改量，版本记录变为 2 条；计划页“预测（系统重算）”在任务开工后真实重算一次，记录变为 2 次，已开始任务显示“缺剩余工期估计”。亮暗截图：[supply-commitments-light.jpg](supply-commitments-light.jpg)、[supply-commitments-dark.jpg](supply-commitments-dark.jpg)、[forecast-refresh-light.jpg](forecast-refresh-light.jpg)、[forecast-refresh-dark.jpg](forecast-refresh-dark.jpg) |

环境：`tools/local_environment.py create` 建的隔离 `pdos_test`。它在降级到 base 时仍停在既有的 `s0_0784`（D260），之后手动升到 head 并 seed。全部测试显式指向该库，没有回退到 `.env`，没有调用真实模型；收尾时已 destroy。

## 4. 余项

- 本次两条闭环的余项是 D314、D315。
- 待你确认的条目是 D305–D312。
- 开发环境问题 D316：本机多个预览共用 `localhost` 的会话 cookie。
- D241 只解除了一半：供应承诺已可用，替代料批准仍待 D308。
