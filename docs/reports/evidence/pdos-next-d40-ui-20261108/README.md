# D40 提案和专业页 UI 补齐 · 证据（2026-11-08）

依据：[10-26 UI 对照报告](../pdos-next-ui-comparison-20261026/result.md)“提案编辑”“专业页面”“型号与定义”“设置”四条；视觉与交互按 `web/src/app/ui-lab/platform`（`DESIGN.md`“提案表格编辑”“设置”）和[完整产品 UI 设计候选](../../../design/2026-10-23-pdos-full-product-ui-candidate.md)“事项 → 详情 → 确认 → 结果”。基点 `pdos-next/design-v1.1` @ `07c023e5`。

## 做了什么

| 缺口 | 现在 | 写入走什么 |
|---|---|---|
| 方案 A/B 并排、单元格直改 | 方案按列并排（方案 A、B、C…），名称/类型/说明三行，单元格常驻可编辑，悬停显示边框、聚焦橙色描边；改动累积为草稿，顶部“保存修订”一次保存；改回原值自动撤销草稿；每列可撤销、删除；“添加方案”新增一列，填名称后“保存方案” | 现有 `proposal.item.patch`（upsert/remove，带 base_version） |
| 待决问题手动增删 | 问题、负责人、期限、状态与答复同一行直改；“添加问题”在表尾加一行并聚焦；改问题、负责人或期限时行内出现“核对改派”；删除按钮 | 新增与改派走现有 `proposal.question.create` 的预览 + 一次确认；状态/答复随“保存修订”；删除走 `proposal.item.patch` remove |
| 专业页长表单改为按需抽屉 | 有摘要或记录列表的专业分区（工程配置与 BOM、制造准备、试产、发布与交付包、外部移交及各记录面板）标题旁“〈分区〉· 专业办理”，点开右侧 880px 抽屉（窄屏全屏）里的原办理表单；记录行详情改为右侧详情抽屉，“继续专业办理”转到办理抽屉；产品定义改为已保存版本的紧凑列表，行点开详情抽屉（含原“续版”动作），“编辑定义草稿 / 准备首版定义”打开编辑抽屉 | 抽屉内是原有组件与原命令，未改任何写入 |
| 型号页仍是 7 个标签 | 单页概要：用途、当前定义、平台关联、当前项目；“版本与派生”表列出定义版本与变体（来源、差异、状态）；7 个专业区改为“资料与办理”入口，按需在抽屉打开；旧 `?view=` 深链直接打开对应抽屉 | 只读；抽屉内原组件 |
| 成员页缺责任列和范围 | 成员 / 责任 / 范围三列：责任来自 D33 项目团队（角色、主责、项目负责人）与角色目录名称，按项目分行；范围标“当前品类”或“仅项目成员 · 需要品类授权”及参与项目数；某项目团队读不回时提示“可能不完整”，不显示为无责任 | 只读（`/v1/categories/{c}/participants`、`/v1/personal/projects`、各项目 `/team` GET） |
| 个人偏好缺待处理提醒和默认首页 | “工作与提醒”两行：需要我处理的提醒（开/关）、默认首页（我的工作 / 收件箱 / 项目）；开启时侧栏“我的工作”旁显示要我决定 + 接收 + 验证的事项数，读不回则不显示数字；打开 `/` 且未指定页面时进入所选首页 | 现有本人偏好存储 `personal_preferences.body`（JSONB）加两个字段，**无迁移**；两字段不进入小Pai运行上下文 |

另修：提案确认对话框原先对“改派问题”也显示“确认提交 G0”，现按操作显示“确认新增问题 / 确认问题的责任安排”。

## 自动检查

| 检查 | 结果 |
|---|---|
| 前端全部 `.mjs` 测试（163 个文件） | 1924 通过，0 失败 |
| 新增/改动测试：方案并排与草稿撤销、问题直改/改派/新增须确认/无确认路径时不出现“添加问题”（`proposal-document.test.mjs`）；成员责任聚合、读失败计数、并发上限（`member-responsibilities.test.mjs`）；默认首页只在未指定页面时生效、提醒数只 GET 且拒绝他人队列（`shell-preferences.test.mjs`）；BFF 偏好校验新字段（`personal-preferences.test.mjs`）；专业页抽屉按需挂载（`project-views.test.mjs`） | 通过 |
| `tsc --noEmit` | 通过 |
| `eslint src` | 0 错误；4 个警告均在未改动的测试文件 |
| 服务器：`test_personal_preferences.py` + `test_personal_preferences_pg.py`（隔离 `pdos_test`） | 38 通过 |
| 受影响的运行上下文：`test_result_continuation_pg.py::test_reduced_context_keeps_omitted_fields_and_run_frozen_preferences`、`test_assistant_depth_integration.py` | 12 通过 |
| `tests/core/test_public_api.py`、`tools/validate_contracts.py` | 通过；`contracts/openapi.json` 重新导出，差异只有两个偏好字段 |

## 浏览器走查

环境：本 worktree 用 `tools/local_environment.py create` 建的带标记独立库（建库时迁移往返照旧在降级到 base 时失败于 `s0_0784`，即 D260；库停在 head `s0_0861` 后单独执行种子）。API 无 Temporal（`PDOS_WORKFLOWS_ENABLED=0`），前端 `next dev --webpack`（worktree 的 `node_modules` 是指向主工作区的链接，Turbopack 不接受）。合成账号：种子产品经理、`tools/acceptance_account.py` 建的评审人（产品经理）和结构工程师（无产品管理权）。数据全部经公开命令建立：一个经具名 G0 批准的项目（团队三人、角色由负责人经 `project.member.set` 设定），一个草稿提案，一个等待产品经理评审的提案。未调用模型。

| 截图 | 内容 |
|---|---|
| [01](01-proposal-ab-questions-light.jpg) | 提案页亮色：方案 A/B 并排、问题表直改、“添加方案 / 添加问题” |
| [02](02-proposal-cell-edit-draft.jpg) | 直接改方案 A 名称：聚焦描边，列底“未保存 · 撤销”；之后连同问题 2 的“已答复”一次“保存修订”，提案 v2、两条目各升 v2 |
| [03](03-proposal-new-question-row.jpg) / [04](04-proposal-new-question-confirm.jpg) | 新增问题行（自动聚焦）→ 核对 → “确认新增问题”对话框 → 确认后登记，草稿行消失 |
| [05](05-proposal-reassign-confirm.jpg) | 改期限后行内“核对改派”→“确认问题的责任安排”（走后返回修改并撤销，未保存） |
| [06](06-proposal-dark.jpg) / [07](07-proposal-375-light.jpg) | 暗色；375px：两张表在各自区域内横向滚动，页面宽 375 无横向滚动 |
| [08](08-definition-compact-list.jpg) / [09](09-definition-detail-drawer.jpg) / [10](10-definition-editor-drawer.jpg) | 项目“产品与工程 → 产品定义”：紧凑版本列表；行详情抽屉（Esc 关闭、焦点回到行）；编辑抽屉，关闭再打开时未保存填写仍在 |
| [11](11-professional-summary-with-action.jpg) / [12](12-professional-work-drawer.jpg) / [13](13-professional-drawer-375-dark.jpg) | 工程配置与 BOM：摘要 + “专业办理”；原 BOM/Build 表单在抽屉中；375px 暗色全屏抽屉，关闭后焦点回到按钮 |
| [14](14-model-overview-light.jpg) / [15](15-model-variants-drawer.jpg) / [16](16-model-375-dark.jpg) | 型号页单页概要与版本表；“准备派生”打开平台与差异抽屉（地址带 `view=variants`）；375px 暗色 |
| [17](17-members-responsibility-scope.jpg) / [22](22-members-375-dark.jpg) | 成员与范围：项目负责人、产品经理、项目经理（主责）；结构（主责）、测试工程；品质 |
| [18](18-preferences-work-reminders.jpg) / [21](21-preferences-375-dark.jpg) | 个人偏好“工作与提醒” |
| [19](19-default-home-inbox.jpg) | 默认首页设为收件箱后打开 `/`：进入 `?area=inbox` |
| [20](20-reminder-count-badge.png) | 有一份待我评审的提案时，侧栏“我的工作 1”（读屏为“我的工作，需要我处理 1 项”）；关闭提醒并保存后数字立即消失 |

另核对：私有提案把问题负责人选为不在受众内的工程师时，服务器按原规则拒绝（“G0 前的问题负责人须能读此私有提案”），界面未放宽；删除问题后条目减少且提示已保存。

## 未验证 / 边界

- 专业记录行的详情抽屉只有单元测试，没有在浏览器里用真实记录走：合成环境没有试制、质量、变更记录（见 D339）。
- 型号概要未显示设计稿中的“工程配置”一行（无项目时没有现成的只读来源），设计稿 A/B 下方的“当前取舍”行也未放（正式数据里取舍记录在“更多 → 决策记录”）（见 D340）。
- 提醒数只计要我决定、接收、验证三类，不含“我的任务”和小Pai等待；数字在页面载入和窗口重新获得焦点时刷新（至少间隔 60 秒）。
- 未做手机推送设置（D172 的推送规则另属通知范围）。
- 浏览器只用合成账号走查，不代表真人试用或验收。
