# Wave16 · 公开单问题读取与界面接缝复核

范围：只读核对 A `domain/quality_followup/service.py`、B `domain/capa_verification/{schemas,service,commands}.py` 与 Root 冻结公开 envelope、C 新界面消费字段；未连接数据库、调用 HTTP、运行浏览器或公共构建。本文不是后端联合验收。C 已获授权修复的两个所属界面问题单独记录在 `ui-component-check-v2.json`，原 v1 证据保留。

## 需要主线准确接入的三个位置

1. **首次问题选择原先没有入口，现已在 C v2 修复。** `quality_execution.service.list_quality` 和 A `list_quality_followup` 的无范围读取实际返回 `issues:[]`，不能将其当全产品问题索引。新界面初读仅 `builds`、`workspace`；用户明确选择 Build 后请求 `quality-execution?build_id=...`，选择该索引内 Issue 后才请求单对象 `quality-followup?issue_id=...`。不添加 `run_id`，避免在索引阶段重做逐失败原值证明。空选择边界仍保持，未默认选择最新轮次。Build 切换丢弃旧深读视图；未确定的原命令仍不可改目标，恢复使用原 command/key/payload。

2. **公开单对象 adapter 不能直接返回 A 内部列表。** A 当前内部投影是 `issues/current_by_issue/capabilities`，C 冻结消费的是 `issue/current/operations/actions/...`。需由 Root 的一次宿主适配完成，下表给出精确映射。`quality-followup/inputs` 也需按三个 canonical operation 分发：根因/完成走 A，回链走 B；A 的 payload registry 不包含回链。

3. **当前共享入口尚未登记 Wave16，属于主线待接线，不能算界面已可用。** 复核时 `api.py` 未有公开 `quality-followup` route；真实 BFF 文件为 `pdos-next/web/src/app/api/[...path]/route.ts`，现有 quality/change 允许列表不含此路径和三项新命令。父入口可在 `workspace.tsx` 已有 `WorkspacePanel name="quality"` 中、原 `BuildQualityLoop` 后挂 `BuildQualityFollowup`，传 `data.product`、当前 `session.principal_id`、已有 `api` 和 `refresh`，保留 actor/product key。`WorkspacePanel` 初次访问才挂载并保留草稿，不需更换用户正在调整的导航，也不需改共享 API wrapper。

## A 内部行 → Root 冻结 GET 的映射

公开路径为 `v1/products/{pid}/quality-followup?issue_id=<logical>[&revision=<explicit>]`，只读取一个明确 Issue。

| 公开字段 | 实际来源与边界 |
| --- | --- |
| `issue` | 精确目标 `issues[]` 行；`id` 是不可变版本行 UUID，`issue_id` 才是命令逻辑目标；显式 revision 须精确匹配，不能取列表首行冒充 |
| `current:{version_id,revision}` | A 当前 `current_by_issue[logical].issue_version_id` 映为 `version_id`；不能从所选历史行自填 |
| `basis` | 当前活核 `row.followup_basis`；缺口保持 null。`saved_followup_basis` 是历史保存依据，不能作为当前能力或正式措施完成证明 |
| `operations[op]` | 选定行 `capabilities[op]` → `allowed`，`authority[op]` → `authority`，保留实际 `reason_codes`；禁止用顶层 any-true 概况授权其他范围 |
| `actions[]` | `action_id/executor_id/completion` 保留；A `text` → `label`；`can_prepare_completion` 只允许填写真实候选后交 inputs 核对；`can_complete=false/completion_verified=null` 保留，不能变为已完成或已核实 |
| `source_options[]` | A 已返回 `{title,source,quote}` 所需内容；`source.position` 是服务器核过的完整行 SHA 定位，勿按摘要或局部摘录重新生成。额外 line 可仅用于显示 |
| `required_source_read_set` | A/B 当前完整来源并集；Domain 输出/专业 UUID 不是 Artifact，不应塞入 Artifact SourceRead |
| `integration` | `effectiveness:false,close:false` 固定；Issue 当前数值通过、存在 link 或 candidate 都不能将其补 true |

**实际历史指针缺口：** A `list_quality_followup(issue_id,revision=n)` 只加载该版，并仅当它是 current 时填 `current_by_issue`。因此明确旧版时 map 为空。公开非空 `current` 须另在同一授权范围读取真实 current pointer，并核对其当前可读性；不能把历史行 UUID/版号填进去。若当前对象私有且此 actor 不可读，不得泄漏该 pointer；当前冻结合同不支持 `current:null`，需明确拒绝整个单对象读取，或另经主线冻结可空历史合同并适配界面。历史行本身 `is_current=false`、authority 未评估、capabilities=false 保持，C 不会按历史保存资格办理。

A 的 `actions[].blockers` 是 `{code,detail}`，公开合同采用 `reason_codes`。若 adapter 只丢掉 blockers，具体“须提交本人结构化完成原文并核对专业/实施 owner”的原因将被省略。可把 code 保留在 action reason_codes，并保留实际 detail 在只读行内或扩展 action 字段；这项说明不能反过来将已允许准备候选的 action 禁死。无完成候选时 `can_complete=false` 是正常状态，不是接口坏掉。

## B 输出、回链和复验候选的真实含义

- B 没有公开全量 GET/options 构造器，Root 授权宿主读适配仍需接入。`OutputReading.ref` 是真实 immutable owner row ID + 固定 revision；`logical_id` 另列，只有 BOM 行/制造工序允许真实 key。公开 `output_options` 的 label 可取已读 title、status 保留；不能用逻辑 Request/Run ID 代替版本行 ID。必须复用 B owner、scope、private、原件安全、Run 保留证明等守卫，不能直接 SQL 罗列并自造可选项。没有实际 owner/options port 时返回空列表与明确缺项。
- B `_link` 重新核对真实保存行，返回 **ResolvedOutputs**，并非 **RemediationLink DTO**。`links` 若投影保存历史，需从真实 link row 得到 link ID/revision、固定 basis/action/output_refs、原 received_at、sources/readset 与原因；当前重核失效应显式 needs_recheck，403 隐藏内容。不能把 resolution 当新 link、不能用新 Issue 当前版覆盖其历史 basis，也不能以临时内存结果生成候选 UUID。
- `inspect_verification` 才能读取已有真实 candidate row；不存在候选时 `candidates:[]` 合理。已返回 CandidateInspect 仍是 `result=indeterminate`，适用性、独立核验、观察期均 null，effectiveness/close false。当前绑定成立不等于专业判断通过。
- B 回链 preview 的 `after.received_at` 是字符串 `server_on_save`，C v1 会露出英文；**C v2 已专门映为“保存时由服务器记录；不是实际事实发生时间”**。不用当前时钟填充、不改变服务器 preview 摘要，也不改真实保存的 received_at。

## inputs、预览、回执与 BFF

A inputs 返回 `operation/allowed/required_source_read_set/authority/review`；根因和完成 review.before/after 是 **logical Issue UUID → pure Issue** 的 map。C 按相同目标、原 expected revision、新 revision +1 核对，不能把它改成普通 IssueView 或动态插入 now。A 新根因决定时钟、接收时钟在 preview 保持 null + `clock_basis=server_on_save`，实际 completion.at 独立保留完整小数秒/UTC offset 与 IANA 来源。

B link review.before 可为 null、after 是新 link 的固定 resolution；link 不推进 Issue。回执根因/完成为 `quality_issue` 新版本行，回链为 `capa_remediation_link` 实际新行；界面成功后刷新当前 Issue，但不从 link receipt 推断 Issue 版号增加。T2 根因 prepared command 必须保留 `approval_token`、`write_tier:T2`、`named_decision:true`；两个 T1 保留 `confirmation_token`。submit/replay 都使用完整 returned command，不能在 route adapter 重建 payload 或标识。

BFF 最小扩展：

- GET `quality-followup` 仅允许一个 `issue_id` UUID 和可选严格正整数 `revision`；重复键、未知键、非法 UUID、无 issue 的 revision 拒绝。revision 不是 UUID，不能照搬现有 quality/change 查询循环。
- POST `quality-followup/inputs` 不允许 query；三操作的共同 `/commands/preview`、`/commands` 加入长操作分类，GET/inputs 也按真实来源/保留证明核对等待 180 秒。保留 body 一次读取、原文本转发、无自动 retry、cookie 会话、同源守卫和 no-store。
- GET 失败只表示读取失败；mutation 超时表示原回执未知。保留共享 wrapper 的 READ_SUPERSEDED 取消语义与 actor/product epoch；不能为首屏提速引入跨用户缓存、跳过每次 inputs/preview/apply/replay 当前重核。

## 本次结论与交付边界

C v2 消除了已证实的无范围空索引入口问题及保存时钟英文占位问题，37 项辅助检查、所属类型检查和三文件 lint 通过，原 v1 证据未覆盖。公开 adapter 的历史 current pointer、A/B 三动作分发、B owner 读取与真实历史投影、BFF 严格 revision 查询及父入口仍由主线完成并集中验证。无真实 source/专业/完成 callback 时应保持显式缺项，不能宣称 Wave16 整体可办理或通过联合出口。
