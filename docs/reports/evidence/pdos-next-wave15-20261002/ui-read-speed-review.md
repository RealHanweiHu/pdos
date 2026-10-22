# Wave15 质量界面读取放大与下一候选建议

2026-10-02，只读源码分析。主线报告实际选择失败约一分钟；本文未测量延迟、未调用 HTTP / 数据库 / 页面 / 测试，也未改变冻结组件。依据 `web/src/components/builds/build-quality-loop.tsx::choose/refresh/perform`、`web/src/lib/build-quality-loop-view.ts::readQualityContext`，并定向核对当前 scoped GET 实现。

**建议先改同一已读范围内的纯选择，再按动作刷新受影响聚合。** 保留每次提交的 inputs → T1 preview（适用动作）→ apply / replay 当前核对；不引入跨用户、跨 scope、跨提交阶段的权限或事实缓存。

## 1. 可确证的请求放大

`choose(patch)` 对所有 selection 都执行 sequence++、置 loading、调用完整 refresh；它没有区分所选实体已经在 context 里，还是 Build / Run / Issue 真正变了。`readQualityContext` 每次走：

```
builds + workspace（两个独立 GET）
  → verification-results?build_id=...
    → quality-execution?build_id=...&run_id=...
      → change-execution?issue_id=...（已有选定 Issue 时）
```

| 当前交互 | 本组件发起的 GET 数（按代码分支，不是实测） | 不必要部分 |
|---|---:|---|
| 首屏空选择 | 2 | 不深读业务历史，这一保护已正确 |
| 选择 Build、Run 尚空 | 3 | 需要该 Build 的运行索引，但不必每次重读整个 builds / workspace |
| 选择 Run，Issue 尚空 | 4 | 要取得本 Run 的真实失败与 Issue；已读 Build 集合与原文不必成为每次重新发现前提 |
| 仅选择已有 failure | 4～5 | failure 只从已读 `quality.failures` 查找；helper 请求参数根本不消费 selectedFailureId，却重读整组 |
| 仅选择已读 Issue / Change 历史版本 | 5 | 版本已经在 issues / changes 数组中，刷新仍读取最新指针与整个上下文 |
| Issue 分诊 / 遏制 / CAPA 或 Change / Impact 保存 | 通常 5，再顺序调用父 onSaved | 当前动作没有改变原 Run、Build 或原文集合，但仍重建其整组展示 |
| 新建 Issue 成功 | 原 Issue 未选时先 4，再选新 Issue 后 5，再父 onSaved | 两轮 refresh 的区别主要是新增 Issue 选择及其 Change 选项 |
| Graph capture 成功 | 通常 5 | 本次只新增一个变更图快照，无需重读原报告及失败 |

父 `workspace.tsx::refresh` 又请求一次 workspace；子全量 refresh 和父 onSaved 目前顺序执行，因此现有“仅在途 GET 去重”不会合并这两个已完成的同 URL 读取。父读取更新活动 / 来源等有用途，但重复不等于必须每层完整重建。

纯文字编辑、出处选择 / 加入、CAPA 假设 checkbox、图快照 select 当前使用 edit / setState，不触发 GET；这些路径不需要额外优化。scope digest 包含 failure / Issue / Change 及来源 / 能力，用于废弃预览；不能因取消全量读而删除这一安全绑定。

## 2. 下一候选最小优化顺序

### P0：把“已读对象选择”与“服务器刷新”分开

增加小型本地 selection 路径，仍保存本机草稿、清 inputs / preview，保留 busy / pending 锁与 scope digest；仅用于**同 actor / Product / Build / logical Run 下、已存在返回数组中的 failure**，以及已读不可变 Issue / Change 历史版本、已有 capture。failure 切换不修改请求的 scope，也无新来源读取，目标是 0 GET；不存在目标或范围变动则真正 scoped refresh。

本地读取的是本轮已返回的展示快照，不声明其权限 / 资格仍然当前。创建 Issue 仍先由 inputs 重核精确失败和事件；历史版能力保持只读，不能从 current row 借 cap。本地切换同样废弃旧 preview，不能将已准备命令改成新选中的 failure。不要让选择跳过 pending 未知请求或移动原 command。

### P1：明确 Issue 后使用精确 detail 读取

当前 BFF 已允许 quality-execution 的 issue_id，后端 `list_quality` 已按该 logical Issue 过滤版本；**只传 issue_id 时不会再次调用 `_failure_candidates`**。若同时继续传 run_id，底部仍会重新建立整个 Run 的失败候选，不能声称已省掉它。

建议将“本 Build / Run 的选择列表”与“当前选定 Issue detail / policy / authority”拆为明确读域：选择 Run 时取得范围列表；选择新 Issue 后读 `quality-execution?issue_id=...` + `change-execution?issue_id=...`，不重建原 Run。结果 shape 的 failures 可能为空，不能用 detail 响应覆盖 discovery 列表而让 failure selector 或跨 Issue 选择消失；也不能把先前 issue 列表的旧能力混成新 detail 的当前能力。

已选 Change 时 `change-execution?issue_id=...&change_id=...` 可以给当前精确历史 / captures 与创建选项。后端 change_id 已下推 SQL；issue_id 当前是在产品 101 行上限后按固定根 / 引用过滤，因此仅缩小 URL 不等于 SQL 已全程按 Issue 限定。下一后端候选如优化索引 / 查询需单独核权限、分页与隐私，本文不改或降低服务守卫。

Current detail 必须原子替换、缺失即清空其内容及能力；不可读目标不保留旧私有正文作 fallback。范围列表可保留名称 / 固定身份供选择，但显示为既有读取快照，不从它决定写权限。明确刷新仍重新取得父范围与列表，不制造永久 fulfilled cache。

### P2：保存后按回执刷新受影响域

| 已保存动作 | 确实需要的回读 | 可避免的祖先重建 |
|---|---|---|
| quality.issue.create | 从真实回执定位 Issue，读其 current / 失败 / 政策；随后加载该 Issue 的 Change 选项 | 新建前整个 Run refresh 后再整个 Issue refresh 的两轮发现 |
| triage / containment / CAPA | 精确 Issue 当前版、历史、政策 / caps；重读其 Change 关系，旧固定提案可能因 Issue 续版失效 | 原 Build / verification-results 的同一固定原值证明 |
| change.request.create | 原 Issue 范围中的新 Change / current pointer、创建选项 | builds / 原 Run / 全 Run failure discovery |
| graph capture | 本 Change 的 captures / graph 当前性 | Run、Issue 失败候选、无关 Change histories |
| impact compute | 本 Change 新版 / current / graph 状态；过期 capture 明确重核 | 原始执行和失败重新证明仅为展示而重复取得 |

Receipt.subject_id 是版本行 UUID，并非 logical Issue / Change。若原回执 result 未有可靠 logical 身份，保留**一次**必要的 scoped discovery 回读用于匹配；不要把 subject_id 当 logical target，或从未校验 result 直接给当前能力。若后续主线扩展回执最小关联字段，再去掉这一轮发现。保留父 onSaved 用于更新活动；不要仅为省一次 workspace GET 就跳过父页失效 / 身份控制。可以在下一公共协调候选让父最新 workspace 数据显式传给子展示，或合并同阶段独立回读；这需要清楚的 props / epoch 合同，不能自行复用已经 fulfilled 的旧响应。

## 3. 哪些读取 / 核对不可省

- 初次进入、actor / Product / Build / Run 真正变化、恢复本机目标时，要读服务器当前可见目标及其范围；空选择继续不深读全部历史。上游切换清下游选择 / 内容 / 预览，避免旧私人 detail 在新 scope 中闪现。
- 用户点“刷新当前事实”、返回页面需重核、来源 / policy / authority 失效或 409 等确定冲突、保存成功后的相关 current / pointer / graph，都需要真实 GET。历史旧正文可按现规则保留，当前能力不能从历史复用。
- **每个新提交**仍读该 operation 的 inputs，取得完整 readset、authority、allowed、review；T1 仍取得真正固定 preview。inputs 的返回值不能作为之后 preview / apply / replay 的资格缓存；这些服务器 phase 各自重核。T0 也不因展示 current 就绕过 inputs / apply。
- 原件字节读取前后、专业 / issuer / policy epoch、私有受众和原失败 proof 当前性继续由后端核；UI 不能以原文名称、hash 或前次 GET 替代它。这里只减少展示重复请求，不减少写入安全核。
- 真正未知提交 / capture 继续同原 command / key / payload 恢复；不能借局部刷新造新请求。成功后读取失败保持“已保存，随后刷新失败”，不再次提交；403 / 401 清敏感数据，其他真实读失败明确展示。

## 4. 取消、读写隔离与验证范围

保留现 sequence / alive / scopeRef 守卫；拆读域后要有共同 scope epoch，晚到 A-issue 响应不能覆盖新 B-issue，POST 开始应使旧只读结果过期。每个返回值应用前核 actor / Product / 上游范围和所请求实体；`READ_SUPERSEDED` 仅忽略已知取消，真实网络失败不吞。不要把每个子读域独立计数后忘掉整体 epoch，或让局部 reads 的成功清除另一域真实错误。

继续沿现 workspace transport 的在途同 URL 去重 / GET 并发限制 / POST 不等读与暂停新 GET，不把全部请求同时发出试图覆盖后端串行开销。任何在途复用限同当前实例与 epoch；无全局、跨用户、跨 fulfilled phase 或 TTL 权限缓存。

下一候选的受影响检查建议：mock transport 证明 failure / 历史本地选择 0 GET；跨 Build / Run 必须深读；Issue detail 的 URL 不携 run_id；detail 不丢选择列表 / 不继承旧 caps；Issue / Change 保存只刷新上述相关域；迟到响应 / POST epoch / scope 销毁不回写；成功后读失败不重发、恢复仍原 key；401 / 403 清私有正文、历史能力仍 false。主线再对新冻结候选集中实测操作前后耗时与页面恢复；本稿没有测得或承诺提速倍数，也不把静态 GET 数量等同服务器工作量。
