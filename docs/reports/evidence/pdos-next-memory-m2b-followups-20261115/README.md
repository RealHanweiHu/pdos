# M2b 余项续做证据（2026-11-15）

分支 `claude/memory-m2b-followups-2ebf38`（独立工作区，从集成分支 `pdos-next/memory-integration` 的 `704eaab7` 起），本地提交，未推送、未合并。用户 11-15 说“设计中没完成的继续先完成”；本会话负责 M2b 范围条目的余项 D504、D506、D509、D510、D511、D514。依据：确认稿 P31、P32、P62、P87，记忆层设计 §9，RAG 设计 §7.1。

环境：本工作区用 `tools/local_environment.py create` 自建的独立临时库 `pdos_test`（先是容器 `pdos-next-test-20261002-eb4eec96`，127.0.0.1:55742；为了在空库上做迁移往返，后来销毁并重建为 `pdos-next-test-20261002-5b29eb0e`，127.0.0.1:54421），显式 `TEST_DATABASE_URL`，没有用 `.env`，没有碰 57105、54222。每次运行前由脚本核对容器编号、标记和端口。没有调用真实模型或嵌入服务，没有出站。

迁移是占位号：`s0_0910_scope_note_review_days`，接 `s0_0892`。集成时 revision、down_revision、快照文件名 `schema_s0_0910.py` 和其中降级守卫的文字一起按真实 head 重排。

## 各项结果

| 条目 | 结果 | 证据 |
|---|---|---|
| D504 复核期限租户可配 | 做完。`memory_tenant_policies.scope_note_review_days`（缺省 90，1–365）；只有现任人类管理员能改；新记或修改的版本按当时期限起算，已写的版本不变；设置页加一项 | `tests/knowledge/scope_notes/test_scope_note_review_period_pg.py` |
| D514 会话历史依赖 | 做完（团队备忘部分）。运行带入过、`memory.search` 返回过的备忘作为依赖；停用、撤回、对本人不可读时隐藏历史轮次，续接运行在下一次模型调用前停下；修订、替代、过期只标“已更新”。讨论串回复的受众核对（P62 共用实现）随之把备忘算作读取来源 | `test_scope_note_history_pg.py`（3 例，含注册的 `conversation.history`、`memory.search` 负例） |
| D509 证据链接与正式对象 | 做完。新读接口列出读者现在能读到的可关联对象（只给标题）；行上“补充证据”、决策背景可挂任一列出的正式对象（含 G0 决定）；历史逐条显示证据。页面不做权限判断，命令再核 | `test_scope_note_evidence_pg.py`（2 例）、`web/src/lib/scope-notes.test.mjs`、浏览器走查 |
| D506 其他范围的近况 | 产品接上：复用产品页“实际活动”的回执查询（按读者权限、按水位）。提案、品类没有可复用的动态流，只带备忘变更 | `test_scope_note_scopes_pg.py::test_a_product_scope_reuses_…` |
| D510 钉钉 | 没有放开。P31 没写团队备忘；记忆层设计 §9 要求按 P31/P62 的来源受众规则处理，而钉钉群还没接 P62 第 3 项的共用核对（D392）。登记 D570，给了三个选项，建议和 D392 一起放开 | 清单 D570 |
| D511 驾驶舱走查 | 做完，见下 | `screens/` |

## 浏览器走查（D511）

在本会话的测试库里用脚本造了一个合成租户（两名成员和小Pai 身份），经 G0 流程建立项目“F64 便携充气泵”，记了约定（置顶）、关注点、决策背景各一条和一条品类约定，给决策背景加了一条 G0 决定的证据。本地起 API（8911）和 Next 开发服务（3911，webpack 模式），以合成负责人的会话打开驾驶舱概览。

| 截图 | 内容 |
|---|---|
| `cockpit-memo-list-light.jpg` | 备忘区列表，置顶约定在前，决策背景标“未形成正式决定” |
| `cockpit-memo-history-evidence-light.jpg` | 历史：两个版本和证据链接（G0 决定、第 1 版、背景、位置） |
| `cockpit-memo-evidence-form-light.jpg` | 补充证据表单：来源下拉（服务器列出）、立场、位置、摘录 |
| `cockpit-memo-evidence-confirm-light.jpg` | 服务器预览：谁能看到、补充 1 条链接、内容和确认状态不变；确认后写入 |
| `cockpit-memo-formal-linked-light.jpg` | 决策背景改挂 G0 决定后，“未形成正式决定”消失，显示正式记录 |
| `cockpit-memo-list-dark.jpg`、`cockpit-memo-history-dark.jpg` | 暗色主题 |
| `cockpit-memo-375-dark.jpg` | 375px，页面宽 375、可滚动宽 375，备忘区 343/343，无横向溢出 |

375px 亮色下打开了补充证据表单，用脚本量得页面宽 375、可滚动宽 375，无横向溢出；那一步浏览器窗格被隐藏，没能截图。

走查中发现并修了一处：第四个按钮“补充证据”把驾驶舱窄栏里的正文挤得很窄；改为备忘区宽度不足 560px 时（容器查询）按钮换到正文下面。另见到两件与本次改动无关的事：开发模式冷编译时驾驶舱第一次读取报“暂未读取到当前事实”，点刷新即正常；一次确认因我操作间隔过长、预览的确认凭据过期被拒（409），页面保留填写内容并提示重新核对，重做预览后保存成功，这是 T1 凭据的既有行为。

## 检查

| 检查 | 结果 |
|---|---|
| 迁移 | 重建的空库上 `local_environment.py create` 跑全链 head → base → head 通过（head 为 `s0_0910`）；再单独 `s0_0910 → s0_0892 → s0_0910` 通过。在有测试数据的旧库上降级被守卫拒绝（`A tenant scope-note review period requires s0_0910`），符合设计：有租户改过期限时不能降级；策略行只追加，不能改回 |
| 带库回归第一轮（`tests/knowledge` 除 `pg/` 外全部、`tests/agent/memory`、`tests/agent/kernel` 的会话历史与续接组 12 个文件、讨论串 @小Pai、`tests/integrations/dingtalk`） | 596 个：550 通过、31 跳过、15 失败，10 分 51 秒。14 个失败是同一个缺陷：单元测试用不带新键的普通字典行，`row["scope_notes"]` 抛 KeyError，改为 `row.get`；修后这 4 个文件加两个备忘历史、证据文件重跑 100 通过。剩下 1 个见下文“集成冲突” |
| 重建的空库上 `tests/knowledge/scope_notes` + `tests/knowledge/pg`（含知识生命周期重测试） | 76 通过，8 分 17 秒。第一轮把 `tests/knowledge/pg` 放在一起跑时机器负载 33–52（其他会话的测试），2 小时只跑完 12 个（全部通过），停掉后拆开重跑 |
| 合同 `tools/export_contracts.py` | `openapi.json` 只新增 162 行：新 GET 路径 `scope-note-sources/{anchor_kind}/{anchor_id}` 与策略的 `scope_note_review_days` 字段 |
| 合同校验 `tools/validate_contracts.py` | 通过：87 操作、97 事件、70 验收编号 |
| 前端 `tsc --noEmit` | 通过 |
| 前端 eslint | 0 错误；全仓 4 个警告都在本次没动的文件里，本次改动的文件无警告 |
| 前端 `.mjs` 全量 | 2002 通过、0 失败 |

前端用主检出的 `node_modules`（只读借用的符号链接，没有提交）；`pnpm` 在借用目录上会尝试重装，所以直接调用 `next typegen`、`tsc`、`eslint`、`node --test`。

## 集成冲突（不是本次改动引起，没有改）

`tests/agent/memory/test_memory_session_controls_pg.py::test_owner_deletes_a_session_and_its_memory_rows_are_gone` 断言每条情景只有 `answer`、`episode` 两行索引（会话控制分支写的），而同一集成分支并入的检索缺口分支（`s0_0890`）给情景加了第三行 `object`，实际是 3 行。两边的文件本次都没动；建议由集成会话按 `s0_0890` 把这条断言改成三行（删除会话后三行都应清除）。

## 没有做、依赖别处的部分

- D510 → D570 等你定（建议和 D392 一起做）。
- D506：提案、品类没有动态流可复用，要有须先设计。
- D514：个人条目的同类依赖在另一会话的文件里（`notes.py` 一带），本会话没动。
- D509：提案类回执在来源列表里显示操作编号（中文操作名目录只覆盖项目动态）。
- 提议卡上的“记为项目备忘”仍没在真实卡片上点过（D298，提示词路径关着）。
