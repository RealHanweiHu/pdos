# W6 ⑤ D37 讨论与评论、@成员提及、通知降噪与 P56 交接（2026-11-08）

分支 `claude/eloquent-mclean-240ee2`（基于 `pdos-next/design-v1.1` 的 `07c023e5`），本地提交，未推送。

- **迁移占位**（D37 ⑤ 区段 `s0_0873`–`s0_0877`，接 `s0_0861`；集成时按真实 head 重排文件名、revision、down_revision 与快照文件名）：
  - `s0_0873_handover_lane`：P56 交接通道。升级前核对被替换的 6 个对象与 `s0_0859` / `s0_0790` / `source_object_audience` 的原文一致（md5）。
  - `s0_0874_project_discussions`：讨论、评论、关注、通知与设置六张表；有数据时拒绝降级。
- **依据**：
  - 设计稿 `2026-11-01-project-team-cockpit-mentions-design.md` §4.4、§6、§7.1–7.2、§8、§10、§12。
  - 确认稿 P34、P41（第 4–7、9 项）、P52、P53、P56、P77（D73、D74）。
  - 用户 11-08 裁定写入确认稿 P98（静音只挡关注变化和摘要）、P99（停用先提醒，已承接任务的改派留到 W6 ③）。

## 做了什么

| 部分 | 内容 |
|---|---|
| P56 交接（替代 D33 临时偏离） | 移出时成员资格、角色和**项目受众立即结束**，所有现有项目读取（项目行策略、计划、回执、运行上下文）自然拒绝此人。此人只能经“交接通道”办理本人未交接事项：服务器先用 `open_handover_lane` 在 SQL 中核对（本人、交接中、事项属本人且未完成），再设事务级 `pdos.handover_lane`；`projects` 策略、`source_object_audience`、`work_receipt_project_visible` 逐行复核 `project_handover_lane`。未交接事项（本人负责的未完成任务、未兑现的承诺、负责的未关闭外部等待）由 `project_handover_items_of` 一处判定，团队页、通道和自动完成共用。任务验收或改派、承诺验收、外部等待记录后调用 `settle_project_handover`，事项清空即自动完全移出（撤回随本项目加上的型号/定义受众）。项目受众约束改为“= 当前成员”。迁移时把已有待交接成员的项目受众删除，降级时补回 |
| D214 停用 | 管理员停用账号时，`notify_deactivated_handover` 给每个此人仍有未交接事项的项目负责人发一张“待接事项”卡片（要我确认或决定）；团队页把此人标“账号已停用 · 待交接：任务「…」”。已承接任务的取消/改派按 P99 留给 W6 ③ |
| 讨论与评论 | 项目讨论主题（有标题）与对象评论串（任务、文档；每个对象一个串）。串不带自己的受众：每次读取在读者自己的 RLS 下复核所挂对象，客户私有文档下的评论只对该文档受众可见。评论记下对象当时版本（`subject_revision`，数据库触发器核对），编辑重新锚定。作者可编辑（每次留一个版本）和撤回（显示“已撤回”，版本保留，他人读不到已撤回的历史）；不硬删。讨论注明“不构成决定、承诺或批准” |
| 提及 | `@[名字](person:…)` 等标记由服务器解析：@成员只能提及当前能看到对象的人，否则 422 并列出“不在本项目受众中”的人；@角色只通知本项目该角色中能看到对象的成员；@全体限负责人；@任务为引用。提及只通知并让此人关注该串，不授权、不分派。@小Pai 返回 `agent_mention_pending`，接口留给 ⑥ |
| 通知与关注 | 五类（提及我、分派给我、要我确认或决定、小Pai 需要我、关注的变化）。写入只经 SQL 函数：操作人不收自己操作的通知；小Pai 自己的写入只通知受派人（P53）；收件人此刻须能看到对象；10 分钟内同一对象合并（计数、参与人、最新一条）。自动关注：创建、评论、被分派、被提及（只关注该串），本人取消优先。按项目设置级别（全部 / 重要变化 / 只看提及）、静音（P98：只挡关注的变化和摘要）、关注变化改为每日摘要。通知行不存正文，标题与摘要读取时按读者权限取自对象，失去访问即隐藏 |
| 稍后提醒（D73） | 1 小时后 / 今天 15:00 / 明天 9:00 / 下周一 9:00，30 天内；到时以未读重新出现，实时游标随之变化 |
| 实时投递（D74） | `GET /v1/personal/notifications/stream`（SSE）每 2 秒在服务器侧比较游标，有变化发 `changed`，15 秒保活，2 分钟后让浏览器重连。每轮用不计活动的 `peek` 复核会话，会话失效即 `closed`。BFF 新增专用流式代理，不缓冲。浏览器断流后每 30 秒轮询 `/changes`，同一节拍重试 SSE；恢复时带 `Last-Event-ID`，服务器发现缺口立即发 `changed`，页面重新读取 |
| 导出（D279） | 项目导出新增“讨论与评论”表，读取范围与页面相同；撤回只导出“已撤回”，提及标记导出为“@姓名” |
| 前端 | 概览加“项目讨论”（主题列表、发起讨论、串视图、本项目通知设置）；任务详情抽屉加“任务评论”（版本锚点“评论于 vN · 当前 vM”）；`?thread=`、`?task=` 深链；收件箱新增“提及与工作”标签（分类、收件 / 稍后提醒 / 每日摘要 / 已归档、已读、稍后提醒、归档、全部已读、实时状态）；我的工作顶部“交接中的事项”（本人事项、任务评论、登记开始与提交成果，均为核对后一次确认）；团队页逐条列出待接事项；账户停用提示“已通知 N 个项目的负责人” |
| 合同 | `auxiliary-operations.json` 登记 8 项：`discussion.message.post/edit/retract`、`discussion.follow.set`、`discussion.read`、`notification.read/state.set/preference.set`；`project.member.set` 说明改为 P56/P99。`/v1/personal/notifications`、`/v1/personal/notification-preferences` 纳入未登记写入检查。`openapi.json` 全量重导 |

## 验证

| 检查 | 结果 |
|---|---|
| 迁移 | 独立 `pdos_test`（`tools/local_environment.py create`，降到 base 时照旧在 `s0_0784` 失败，D260；之后 `upgrade head` + `seed`）上 `s0_0873`、`s0_0874` 多次升-降-升通过；有讨论数据时降级被拒 |
| 新增 PG | `tests/projects/discussions_pg` 10 例全过：受众过滤与移出后隐藏、@看不到对象者被拒、@角色/@全体/@小Pai、提及只关注串、操作人不收、10 分钟合并与窗口外新开、已读；编辑留版本、撤回占位、他人读不到撤回历史、仅作者；幂等与改内容冲突、AI 身份零权限与作者守卫、不可硬删；任务评论版本锚定、分派/开始/提交（要我确认）通知与合并、静音与级别只挡关注变化；**P56 全流程**：移出→项目、工作区、项目讨论、他人任务评论均不可见→本人任务评论可读可写、`/v1/personal/handover` 只列本人事项、负责人可在本人任务下 @ 此人而在项目讨论中被拒→交接期提交成果、不能动他人任务→负责人验收→自动完全移出→零可见（交接列表空、评论 403、通知隐藏）；停用后负责人收到“任务 1”卡片、本人 401、团队页列出待接任务；稍后提醒到期回到未读并移动游标、归档与恢复、他人通知 403、每日摘要；SSE（ready、断档补发 changed、会话失效 closed、`peek` 不刷新空闲计时）与 30 秒轮询接口；客户私有文档评论对项目同事 403、不能 @、导出按读者过滤、撤回导出占位 |
| 受影响 PG | 见下方“受影响范围回归” |
| 团队与目录 | `tests/projects/team_pg` 10 例通过（1 例按 P56 新口径把“交接期仍可见整个项目”改为“立即不可见、型号受众保留到交接完成”）；`test_m3_lifecycle_catalog.py`、`test_combined_registries.py` 75 例通过；ORM 与迁移比对仍是基点已有的 7 项（D261），新表无差异 |
| 合同 | `tools/export_contracts.py` 后 `tools/validate_contracts.py` 通过（87 operations / 92 events / 67 acceptance IDs） |
| 后端静态 | 改动文件 ruff 无错误 |
| 前端 | `tsc --noEmit` 通过；改动文件 eslint 0 错误（仅两条既有测试文件警告）；新增 `discussions.test.mjs`、`notifications.test.mjs`（含实时投递：SSE→断流 30 秒轮询→重连停轮询、closed/reconnect）、`notification-stream-proxy.test.mjs`、BFF 路由新用例；全部 `.mjs` 1928 项 1927 过，唯一失败为 `xiaopai/file-upload.test.mjs` 的时序用例，单独连跑两次均通过，与本次无关；`[...path]/route.test.ts` 90 项全过 |
| 浏览器 | 两个合成身份（同一 dev 服务，切换本机会话），真实 G0 私有项目。负责人：@ 选择器中同事可选、品类内非受众“王岚”置灰并提示“提及不授予访问权”、@全体 `01`；讨论串实时 `02`；任务评论“评论于 v4”且由 `?task=` 深链打开 `03`。同事：收件箱三条（任务评论、提及合并“· 2 条”、分派）`04`；稍后提醒菜单 `05`，提醒后移出收件；暗色 `06`；从提及通知跳到讨论串并回复 `07`；375px 无横向滚动 `08`。交接：移出前提示 `09`；负责人待接卡片逐条列出 `10`；同事“交接中的事项”只显示本人任务与其评论、侧栏不再有该项目 `11`；提交成果经核对后一次确认 `13`→“待成果验收”、交接期评论“评论于 v5” `14`；负责人收件箱“提交了成果，等你验收”与合并的“开始了任务 · 2 条” `15`；负责人验收后团队页不再有“待交接” `16`；同事零可见（交接 0、通知 0、本人原任务评论与项目讨论 403）`17`。新标签页里收件箱与我的工作控制台无错误（之前的报错来自重启前端时断开的 SSE 与有意的 403/409 探测） |

截图在本目录 `01`–`17`。`12` 是第一份种子：测试夹具扫描的原件在预览 API 下被判“无当前有效扫描”（D215 规则，扫描配置不同），与交接通道无关（报错发生在项目已可见之后的来源核对）；第二份种子改用不带原件的登记资料（`server/tests/projects/discussions_pg/browser_seed_d37.py`），走完提交与验收。

## 受影响范围回归

范围：`tests/projects`（含 work、fulfillment、external_wait、team、discussions）、`tests/exports`、`tests/core/test_accounts_pg.py`、`tests/my_work`、`tests/categories/preproject`、`tests/builds/test_build_project_scope.py`、`tests/core/command_catalog`、`tests/agent/kernel/test_domain_candidates_pg.py`。在本 worktree 的独立 `pdos_test`（`s0_0874`）上串行跑完：**1988 通过、28 失败、3 个准备阶段错误、1 跳过**（60 分钟）。

| 失败 / 错误 | 个数 | 结论 |
|---|---|---|
| `tests/projects/work/test_service.py`（4）、`test_g0_service.py`（1） | 5 | **本次引起，已修。** 纯逻辑测试禁止 Session 读取，只替身 `owner` 上的 IO 接缝；交接通道与通知钩子原先直接写在 `validate` / `finalize_receipt` 里。已改为 `owner.handover_lane`、`owner.after_fact` 两个接缝，测试按原约定补桩。8 项通过 |
| `test_export_pg.py::test_project_export_matches_page_for_two_roles_and_hides_private_project` | 1 | **预期变化，已改断言**：项目导出新增“讨论与评论”表（D279）。整个文件 6 项通过 |
| `test_material_proofs_pg.py` | 19 | 基点既有（D262）。在 `git archive 07c023e5` 的干净副本上、同一库退回 `s0_0861` 后复跑，同样失败 |
| `test_review_fixes.py::test_actual_owner_and_definers_are_non_superuser` | 1 | 基点既有：报 `change_receipt_key_bound` 的属主是 postgres，不是本次函数；基点副本上同样失败 |
| `attention_pg/test_work.py` 1 个失败、`my_work/inbox/test_inbox.py` 2 个与 `attention_pg/test_work.py` 1 个准备阶段错误、`test_personal_views.py` 1 个失败 | 5 | 环境：07:01 UTC 数据库容器内一个后端被信号 9 杀掉（Docker 虚拟机内存压力，同机有多个并行会话的数据库容器），库进入恢复模式。单独重跑这些文件全部通过 |

修复后复跑：`tests/projects/discussions_pg` 10 例、`work_pg/test_workflow.py`、`work/test_service.py`、`work/test_g0_service.py`、`tests/exports` 全部通过。迁移在清空讨论数据后从 `s0_0874` 降到 `s0_0861`，被替换的 7 个对象原文 md5 与升级前逐字一致、新函数全部移除，再升回 head 通过。

## 未做 / 未验证

D321–D331（清单 W6 D37 下）：问题/Build/提案条目评论；文档评论前端入口；“被提及于”反向链接；合并窗口租户可改；每日摘要定时推送与手机/钉钉推送；轮询刷新空闲计时；交接提交只能沿用任务来源、外部等待交接无前端；真实原件来源的交接提交只由 PG 覆盖；AT-65/66 未登记（⑧）；openapi 全量重导；负责人取消与停用者已承接任务改派（W6 ③）。@小Pai（⑥）、驾驶舱读模型（⑦）不在本次范围。未调用真实模型；未做任何推送或外部出站。
