# Wave16 界面与公共接线交叉核对

范围：只读核对 C 的三个新增界面文件、未应用的 `ui-public-integration-proposal.patch`、Root 的 `quality_followup_api.py` / `quality_followup_integration.py`、B 的 `quality_followup_views.py`，并定向对照 A/B inputs、共同预览和回执。没有运行数据库、HTTP、浏览器或公共构建。公共后端正在由 Root 接线；本记录不是部署、真实专业资格或人工出口验收。

## 实质发现与修复

发现一处权限撤回后的私有内容残留：`FollowupPanel.perform` 已取得有效写回执，然后自身刷新或 `onSaved` 返回 401/403 时，旧分支仅提示“已保存、刷新失败”，跳过 `clearSensitive`。因此之前的 Issue、精确原文、预览和本机草稿仍可留在页面及本地存储。触发路径不需要重发或改变后端权限规则。

Root 授权后仅修改三个 owned 文件。v3 对 401/403 先清空 context/data、原文选择、预览、inputs、全部本机草稿及 pending，再保留“已取得成功回执，当前权限不可用，只核对读取并刷新，不重复提交”的明确提示。已确认提交后的普通读取失败也维持成功事实；只有尚未取得确定回执的网络不确定情况保留原命令恢复。没有把清理权限范围变成可重发的未知操作。

旧 v2 源码归档在 `ui-v2-source/`；差异为 `ui-v2-to-v3.diff`。40 项 helper 检查通过（保留旧 37 项，新增 3 项成功回执/权限丢失恢复边界），三个 owned 文件类型检查与 lint 通过、0 error / 0 warning。原始记录、准确命令和最终 SHA 见 `ui-component-check-v3.json` / `ui-source-v3-manifest.json`。没有覆盖 v1/v2 证据。

## 字段与动作链

| 接缝 | 定向核对结论 |
| --- | --- |
| 首屏与明确范围 | 空 Build 不深读全部问题；选 Build 后请求 `quality-execution?build_id=` 索引，再用逻辑 `issue_id` 读单对象 `quality-followup`。历史选择传真实索引中的正整数 revision，不把版本行 UUID 当逻辑命令目标。 |
| GET 公共 envelope | B 返回真实 `current:{version_id,revision}`、`operations`、`basis`、actions、output_options、links、candidates、source_options，与 `normalizeFollowup` 字段相符。A action.text 被映射为 label；没有把内部原 list envelope 直接传给组件。 |
| 准备完成事实 | `can_prepare_completion` 与本操作 `allowed` 仅开放本人填事实；`can_complete:false` / `completion_verified:null` 没有被转成已完成或已核验。缺可信完成 callback 时关闭准备资格；不能由 Product 写权推导专业角色。 |
| inputs 与预览 | 三操作 inputs 接完整 Command，组件只在同操作 `allowed===true` 时接服务器完整读集进入共同预览。没有把 authority 存在、字符串 true 或缺失布尔当作通过。 |
| 根因 T2 | 操作名 `quality.issue.root_cause.decide`，需 `approval_token`、`write_tier:T2`、`named_decision:true`。before/after 的逻辑 Issue 映射和旧/新 revision 与 A 实际 review 一致；已保存根因不覆盖。 |
| 完成 T1 | 操作名 `quality.capa.actions.complete`，需 confirmation_token。实际时间保留原 offset 及完整小数秒；预览归一化只按同一瞬间比较，不丢微秒。事件 SourceRef 使用整行 UTF-8 SHA 定位，必须在 evidence 中。服务器收到时间与根因保存时钟不伪装成行动发生时间。 |
| 回链 T1 | 操作名 `quality.capa.followup.link`。选项只消费服务器真实 label/ref/status，不手输 UUID；输出 ref 是真实不可变 owner 行 ID/revision。B review.before=null、after.received_at=`server_on_save` 与界面相符，显示“保存时记录”，不生成实际时钟。 |
| 一次执行与回执 | 组件提交返回的 prepared command 原样，不另造 key、token 或载荷。根因/完成回执 family 是 quality_issue（实际新版本行），Link 是 capa_remediation_link；回链成功文案不声称 Issue 推进、原措施满足或有效性通过。 |
| 原请求恢复 | 未确认写入的 execute 网络故障保留同命令、载荷和原标识。READ_SUPERSEDED 旧读取消与真实网络错误分开；成功后刷新失败不得重新执行。v3 补齐成功后的 401/403 私有清理。 |
| 历史与未知 | B 历史 basis=null、三能力 false，组件同时核真实 current 指针、is_current 与来源状态，禁止写入。候选空列表和 effectiveness/close=false 不推成通过；当前没有受控候选创建或正式有效性/关闭按钮。 |

Root 公共操作登记与 C 名称一致，事件为 `issue.root_cause_decided` / `capa.actions_completed` / `capa.followup_linked`。共同预览使用 `exclude_unset=True` 保留原载荷的缺省语义；没有把客户端未填的独立 effective_at 自动补为事实时间。

## 公共提案与保留边界

BFF 提案仅放行严格产品 UUID、GET 必填 issue UUID及可选正整数 revision；拒绝未知/重复 query。inputs 只接受三操作、完整 Command 与有效固定来源读集，一次读取正文、原样转发、没有自动重试。两个 followup 路径及三操作预览/提交等待为 180 秒。父入口只在现有质量面板并列挂载新组件，不新增导航或重排用户已完成页面。

没有发现另一个会阻断所审三动作字段链的实际 mismatch。提案 BFF 的 revision 上限是 JS safe integer，Root API 上限为 2147483647：真实 DB 版本在 API 范围内；超大人工 query 会由 API 拒绝，未构成授权绕过。后续如收紧，应对齐 API 上限，不扩大允许值。

`request_options` 当前只枚举同项目、真实可读的当前 Formal Request，B 再核 owner/Receipt/来源；不能据此声明已接齐所有工程/制造输出种类，亦不能把一个可选旧 Request 自动视作独立新复验。Link 的 action_fulfilled 保留 null，候选/专业独立性/实际观察期仍未知。合成完成 profile 只能由宿主显式配置，客户端没有自授入口。

保留旧核状态边界：根因仅 actioning 可办理；全部措施完成后进入 awaiting_verification，当前没有补根因端口。界面明确展示“先具名根因，再全部完成”及最后全部完成的缺口，未静默增加前置条件或修改 kernel。来源、安全或权限核对失败时不使用本机旧事实开放按钮；私人不可读内容不回退展示。

Root 集中验证仍需覆盖：真实公共挂载、整行完成事件与微秒保持、T2 根因后本人 T1 完成及 Link 独立回执、未知执行同 key 恢复、历史禁写、成功后权限撤回的清理；以及最终迁移/原子 proof/PG。此处的局部检查不能替代上述验证。

## 审阅时源快照

| 路径 | SHA-256 |
| --- | --- |
| `quality_followup_api.py` | `b4ddb2e0f576637206dc8864e93793387b1180dfa30d328c99cf36253cea4bc5` |
| `quality_followup_integration.py` | `7aafcdd287143f43ba22fe46a85d6ab9163210ff2af9f153e940f3f2997cea35` |
| `quality_followup_views.py` | `c3f4fdcae8639fed3a4fe53d954df563f004c4802bf160d8695bbb2798e8196c` |
| A `domain/quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| B `domain/capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| 未应用 `ui-public-integration-proposal.patch` | `bd6aa49fa470dab23c3f0a31cdaab957e4260629140c00eac38d0aef0aad7f94` |
| Root 接线提案 `root-public-integration-proposal.patch` | `e9047fb546da4bb029c8a5ff42e3e35fb2913bc7840c53b85b4f37ed7bddec1f` |

这些公共文件由 Root/原 owner 持有，本次没有修改；快照不是公共最终冻结声明。
