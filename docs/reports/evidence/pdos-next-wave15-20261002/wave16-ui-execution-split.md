# Wave16 最小界面路径与并行执行清单

2026-10-02，只读准备。依据[最新 Wave16 草案](../../../design/2026-10-02-pdos-next-wave16-quality-followup-draft.md)、[Wave15 施工合同](../../../design/2026-10-02-pdos-next-wave15-quality-loop-implementation-contract.md)及现有品质/验证界面。本文仅新增文档，未修改冻结源码、公共入口或清单，未执行数据库、HTTP、浏览器、构建或测试。下列入口与字段是待主线冻结的实施建议，不能当作已开放 API。

**最小路径：当前 Issue/CAPA → 具名根因 T2 → 本人实际完成 T1 → 固定输出回链 → 一条真实保存的新复验分支及缺项。** 有效性决定、Issue 关闭、ChangeOrder 批准/实施/生效均不在本最小范围，能力保持 false。本文件按最新草案收窄了[先前界面续接评估](wave16-ui-continuation-review.md)中关于未来有效性/关闭表单的讨论；不因新 Run 判定 pass 而启用它们。

## 1. 用户能走完的最小路径

| 顺序与建议界面标签 | 用户办理与保存结果 | 必须保留的边界 |
| --- | --- | --- |
| ①「整改后续」→ 选真实当前 Issue/CAPA | 查看原固定失败、措施、政策、当前具名资格及来源；可读历史另列 | 用 logical Issue 与服务器 current pointer 定位；历史、归并来源、needs_recheck 只读，null 资格不是 false 或授权。已有 indeterminate 只调查，不新建失败单。 |
| ②「具名根因决定」 | 填结论、逐项勾选精确出处；服务器实质预览后具名批准，追加根因且保留假设 | 仅 actioning、尚无根因且当前 quality 操作/用途资格允许。已有根因不可覆盖；决定不批准措施有效或变更。 |
| ③「记录本人措施完成」 | 选本人未完成 action，逐项填实际内容、事件时间/原时区、行动与事件出处；一次确认保存本人全部或部分完成 | 不能代另一责任人办理，不能覆盖 completion。完成纯核没有根因前置，但根因仅 actioning 可办：未办根因就全部完成，将转 awaiting_verification 且当前无根因补办端口。最小闭环先办根因；部分完成仍 actioning。界面必须明确这个后果，不额外造隐藏状态关卡。 |
| ④「固定整改输出与下一轮」 | 先由已有 owner 保存真实输出，再从服务器选项选固定对象、相关 action 与原失败范围，T1 回链 | 草稿配置、已建请求、实际输出分别显示；仅调查/检查类实际措施适合首个演练。要求正式改版/量产切换的 action，只有草稿不能算完成。 |
| ⑤「进入独立复验」 | 从真实回链对象进入既有准备/正式请求、实物与实际方法、交样接收、Run 计划/承诺/开测及结果入口 | 至少保存一条真实的新准备/正式请求分支和待办；不能只交空 Evidence 表。条件不齐止于已保存分支与具体缺项，不补 Run、样件、实际时钟或 pass。 |
| ⑥「复验覆盖与观察期」 | 显示新固定 Run/Projection、原报告、原失败→新测试 pair、方法判据适用性、独立参与者与观察窗；可保存服务器核验的候选（辅助 T1 待冻结） | 候选不等于 CAPA effective。缺原失败覆盖、当前专业依据、观察事实、独立人或原件安全时明确待核；有效性与关闭始终不可办理。 |

不改变配置的调查复验可引用仍适用的固定 Build/Actual；改变工程或制造配置的复验须引用 owner 新增的固定双配置及新 Build。两路都用**新 logical Formal request、新 Run**，重新核真实样件/实际方法/接收/资源；原失败 Run、原消费记录和旧批准不变，破坏性已消费样件不能复用。合成事实在入口、预览和历史都显示「本地合成演练，不代表真实整改有效或生产放行」。

## 2. 三个入口的具体表单与预览

### A. 具名根因 T2

可复用旧 `quality_issues/workbench.tsx` 的「具名根因决定」「固定证据及精确位置」布局和 `review.tsx` 的具名决定文案；旧包 camelCase intent/PreparedAction 不可直接发送至共同命令。新 wrapper 不沿用 Wave15 仅支持旧七操作的 tier/preview 判断来接 T2。

| 类型 | 必须展示/填写的内容 |
| --- | --- |
| 固定只读 | 当前 Issue 名称/版、CAPA key、原失败/实际配置/测试项、已有假设、政策、该操作当前 authority/capability/blockers、办理人姓名。 |
| 人工字段 | 「具名根因结论」多行文本；「结论精确依据」至少一项，可逐卡多选。纯核 `RootCauseDecide` 为 `text`、`sources: SourceRef[]`。 |
| 服务器字段 | logical Issue/CAS、scope/purpose、具名 actor、保存后 `NamedConclusion.at`、完整读集/专业依据；公开 wrapper 与 approval_token 合同待冻结。用户不填写决定时钟，不选择另一签核人。 |
| 实质预览 | 原假设/原根因与将追加的结论、完整失败范围、精确出处、当前专业/政策依据、保存影响；新决定时点是稳定未保存占位，注明「服务器保存时记录」。建议按钮「具名批准本次根因结论」，明确 T2。 |

不提供“接受假设即根因”“覆盖已有结论”或客户端赋 quality 角色的选项。决定成功后显示实际回执与服务器钟；根因更正须另合同，不重发 decide 绕过已有值。

### B. 本人实际完成 T1

旧 workbench 的措施选择仅筛未完成、责任人可任意选择，不能原样用作新办理权限。新入口由服务器逐 action 给 capability，办理列表仅含已指派当前本人且未完成者；其他人的措施和已完成项保留只读。

| 类型 | 必须展示/填写的内容 |
| --- | --- |
| 固定只读 | action key/原内容/kind/指派人、当前 CAPA 要求/原失败集合、是否已有 completion、该 action 当前操作资格、来源与正式 Change/Order 状态（如有关联）。 |
| 每项人工字段 | 「本次实际执行内容」；「实际完成发生时间（含 UTC 偏移）」；「原始 IANA 时区」；「行动精确证据」至少一项；另选「本次完成事件出处」。事件出处必须证明同一 action、执行者和实际时点，不能仅引用一段无关但可读文字。 |
| 固定身份与载荷 | 纯核 `ActionsComplete {completions: Containment[]}`；每项 `{id,text,executor_id,evidence,at}`，`id` 为原 action id，`executor_id` 固定本人，不生成新 action 或换责任人。`at={occurred_at,original_timezone,source,effective_at:null}`；公开事件证明格式/CAS/token 由主线冻结，不能先猜整行 JSON 协议。 |
| 实质预览 | 按项显示原措施、实际内容/执行者、各自事件与证据、尚未完成项、将追加的 completion 与聚合状态；建议按钮「一次确认本人实际完成记录」。批量只办所选本人子集，各事件不合并成一个录入时点。 |

完成记录只能证明 action 所要求的真实行为已经发生。若措施要求正式变更实施，应核已批准 Order 与实际输出；研究草稿/检查回执不足时保持该 action 未完成，不能把描述改成较小行为来宣称原 action 已完成。未开放的纯 manufacturing 专业合同须提示阻断，不能以 executor 或 Product 写权限补授 test/quality 身份。

**最后一批完成须单独提示状态缺口：** 如果当前根因仍为空、本次将完成全部措施，表单与实质预览醒目显示「全部完成后进入待验证；当前规则无法在该状态补办根因，请先办理具名根因以走完整改闭环」。完整路径先根因 T2 再全部完成；根因前可如实记录部分完成。操作是否允许仍按服务器 capability/旧核，不在 UI 静默添加根因前置，也不改旧核、伪造已决定根因或承诺存在补办按钮。若已实际进入 awaiting_verification 且无根因，保留事实与此具体阻断，另待恢复合同。

### C. 固定输出回链与独立复验入口

回链/候选辅助操作名称、payload、GET、receipt family 尚待冻结。UI 只能展示服务端 owner resolver 返回的可读选项；不要先用文本 UUID、任意 JSON 或人工勾选创建“current/applicable/independent/pass”事实。

| 分区 | 人工可选字段 | 必须由服务器只读返回的依据 |
| --- | --- | --- |
| 输出回链 | 当前 CAPA/action；真实固定输出选项；说明与精确来源；如需要，固定 Change/Order/item 选项 | 输出名称/id/revision/item key、owner 回执、状态/实际钟、purpose/nature/受众、原失败集合/requirement 摘要、完整 reads、逐项允许/缺项。计划、研究草稿、实际完成状态不能混成“已实施”。 |
| 新复验分支 | 选择真实已建 Preparation/Formal，或进入已有创建入口后刷新选择；按服务器选项关联原失败与新测试项/样件 | 新请求身份/固定版、Build 与实际双配置、当前方法适用/实物状态/接收范围、资料缺项与 professional authority。指名下一责任人只是责任提名，不授专业授权。 |
| 复验候选 | 选新 Run 固定版/Projection、原失败→新 pair 的真实选项、适用依据、具名独立核验人及说明（均限服务端候选） | 全部测量原值/原报告定位、实际方法/判据/配置 binding、规则/政策/来源安全 basis、所有参与者、观察窗、完整性/当前性/独立性缺项。适用映射缺端口仍 unknown，不能仅以相同摘要或 aggregate=pass 代替。 |

独立性卡分别列原测试、措施、遏制、根因决定及新测试执行者；不能只比较“核验人不是当前人”。私有原件/Issue/实际样件未授独立人读取时明确阻断；禁止重建同一失败的公开 Issue、改旧 visibility 或代独立人签字。`observation_until` 是规定截止，另显示真实 `observed_from/until`；到期或一条新 Run 不能自动证明完整观察期。

## 3. 时间与精确出处交互清单

1. 时间字段保留用户原 aware ISO 字符串、UTC offset 与完整小数秒，例如 `2026-10-03T06:25:03.160086+00:00`；禁止用 `Date.toISOString()` 重写实际事实而截为毫秒。客户端可解析作初步 aware/非未来检查，服务器继续精确时间与事件关联守卫；原 IANA 单独保留且核合法，不截时间或补 now。
2. 每一 completion 独立显示实际 occurred_at、原 IANA、服务器 received_at/保存钟。根因的服务器决定钟、复验实际 Start/End/观察钟、规定观察截止分卡展示；空值显示「未记录/待核对」，不以计划窗口、录入时刻或原失败钟补齐。
3. 来源选择项显示标题、固定版、完整行号，展开原行后明确加入；每条结论/措施另勾自己的证据，事件 source 另选。Artifact `SourceRef={id,revision,kind:'artifact',position:'line:N;quote_sha256:<完整行 UTF-8 SHA256>'}` 可复用已修精度的质量 helper；不能用局部摘录或手填摘要冒充完整行。
4. 原件 original-line/page/cell/byte 定位与派生 Artifact 行分开显示。原件 byte hash、security epoch、原值定位及 issuer/受众由服务器给出并重核，不由 UI 根据 Artifact 行猜原件位置。引用当前不可读时保留历史说明，不回显私有原文或沿用旧资格。
5. preview 时间归一化仅用于语义比较：同一 instant 的 offset→UTC 可匹配，微秒确实改变须拒绝；提交始终用服务器返回的完整 prepared command。source/资格/政策/固定配置漂移须重新核，而非只放宽 preview 比较。

## 4. 读取、一次确认与异常恢复

| 场景 | 新 wrapper 最小行为 |
| --- | --- |
| 首屏/本地选择 | 显式选 Issue/CAPA 后再 scoped 深读；已加载同 scope 的 action/历史选择只改本地视图并废弃旧预览，避免重新整组 workspace/builds/results/quality。历史显示「固定历史，当前资格未评估」，不从旧/null caps 开办。 |
| 准备提交 | 每次 inputs 获取当前完整读集、scope/专业/owner basis，再 common preview；T1 与具名 T2 使用各自 token/证明。客户端只限制与解释，allowed/caps 必须严格 true。最多 20 条完整源并集，超限明确拒绝，不截断。 |
| 预览期间改字段/作用域 | action/结论/source/时间/当前版/actor/purpose 改变即废弃预览；T2 不复用上一 T1 确认，也不重造 digest。预览保留 before/after、全部范围及保存效果，提交 returned command 原封一次。 |
| 提交结果未知 | 保存同 command_id、idempotency_key、完整载荷及对应 prepared command；锁新动作，按钮「按原请求核对回执」。重载恢复同请求，不刷新 token后另造 key 盲目再做。过期 proof 由服务器明确判断，不能客户端将未知改成未执行。 |
| 已成功但刷新失败 | 先保留成功回执，再提示「记录已保存，当前后续事实读取失败，请刷新核对」；只读刷新，不再次提交。Receipt 版本行与 logical Issue/输出身份分别处理，不把版本 UUID 当新逻辑对象。 |
| 取消与真实失败 | 仅已知 `READ_SUPERSEDED` 旧读取消静默忽略；网络、403、资格/来源变化展示真实缺项。独立读取 epoch 防止晚到旧响应覆盖新 Issue；不把普通 GET 失败说成未知写回执。 |
| 私人作用域/身份失效 | 清当前敏感正文、候选、预览及本身份恢复副本；其他用户不复用本地草稿/读取结果。恢复 key 至少隔离 principal/product/逻辑办理对象；新身份仍须服务器读权，不能用存在 localStorage 判断授权。 |
| Issue 续版后依赖 | 根因/完成推进 Issue，旧 Change 根引用不跟随；旧 capture/impact 保留并显示需重核。旧 RemediationLink 不能仅因无关聚合追加就一律作废，须服务器核相同 CAPA/action/要求/completion/output 语义 basis；相关变化则取新候选，不由 UI 决定 current。 |

共同 Receipt/AuditOutbox/Current/Version/proof 使用同一事务，子组件不另消费 proof。已由 owner 独立提交的 Build/新请求不是本次链接事务的一部分，失败回滚不得声称撤销它们。当前权限、来源、原件/issuer 和政策核仍先于旧回执 replay；读缓存只能本期减少重复读取，不能跨 inputs/preview/execute 肯定资格。

## 5. 最小冻结接口与可并行归属

| 归属/独占候选 | 先冻结给其他包的内容 | 可同时做且不得扩展的工作 |
| --- | --- | --- |
| A `domain/quality_followup/{schemas,service,adapters}.py`、`tests/quality_followup/` | 根因/本人完成公开 payload；logical Issue/CAS 接旧 writer；逐 action caps/authority/完成 Clock；review 与 receipt 身份；回链调用 B 的 typed 接口 | 调旧纯核，不建第二套 Issue/CAPA；拒代填/重写/错 action。前后预览钟稳定占位、保存钟真实。 |
| B `domain/capa_verification/{schemas,models,service,ports}.py`、对应 tests | 独占 RemediationLink/CapaVerificationEvidence models；owner 输出选项、pair 映射、候选/currentness/完整 readset/缺项 DTO；link 与实际新分支身份 | A 只调用 B，避免争模型。复用原值/结果/retained/方法 owner；缺独立/观察端口只显示 unknown，不授 effective。 |
| C 新 `web/src/components/builds/build-quality-followup.tsx`、`lib/build-quality-followup-view.ts` 与 tests | props 沿现有 `{product,principalId,api,onSaved}`；按明确所选 Issue scoped GET；逐操作/逐 action 能力、完整时钟、固定候选/历史、before/after/authority 与稳定时间说明 | 先表单、来源、历史/缺项与恢复状态机，再接真实 DTO。旧 QualityIssueReading 可精确适配只读部分；现 mapper 对 root_cause/effectiveness 返回 null，须新映射，旧 reader 缺 completion 全钟须补专卡。 |
| 主线公共区 | professional operation matrix、共同 command/T1/T2/token/semantic/replay/UOW、GET/inputs/capture 路径、实际 head 单调迁移、RLS/原子守卫、BFF/导航及 owner resolver 注册 | 统一公共接线/PG/HTTP/构建/浏览器与候选证据；效力/关闭能力仍 false。不在子包并行改共享 models、workspace 或 API。 |

前置冻结顺序：主线先定「仅根因/完成/回链」分级与 writer → B 先交 typed binding/模型/签名 → A、C 按同 DTO 并行 → 主线统一持久接线 → owner 真正创建一条新准备/正式请求并回链 → 条件齐备再走既有独立 Run/原值/复核，核验候选仍不开放有效性/关闭。

## 6. 最小手机与恢复检查（待主线统一执行）

- 320/390px 亮暗：当前/历史 Issue、本人 action 卡、根因/完成预览与缺项可读；长名称、完整 JSON 行、IANA、单位与六位小数秒换行，不露主视图 UUID、不横向撑屏。多来源逐卡勾选，不用原生多选列表。
- 同一来源操作：标题/版本/行清楚；结论依据与事件出处分别选择，实际时间手填含 offset、IANA；输入微秒在预览仍精确保留，空时间不默认当前。
- T2 根因与 T1 完成按钮/说明可辨认；提交忙碌锁定，预览可滚读全部 action、参与者、来源和影响；软键盘不遮住必要字段与主按钮。
- 本人仅完成一项、别人 action、历史/私有不可读、来源撤回、未知实际方法、漏原失败、观察期不足分别显示具体服务器原因；根因未办而本次全完成时明确当前无补办端口，全完成仅「待验证」，有效性/关闭没有假可用按钮。
- 同原请求重载恢复、成功后读失败、旧读被替换与真实网络失败分开；切换身份/私人 scope 不残留正文；进入新分支后看到实际新 request/Run 身份和原消费限制，旧失败/批准/原值不变。

上述是待实施检查清单，没有本波运行结果。必须先明确的合同缺口是：根因/完成公开专业矩阵与事件事实证明格式；回链/候选辅助操作和 owner 固定输出 DTO；私有独立人合法读权；新 pair 方法/判据适用与观察期事实端口。任一依赖不足只阻断对应动作，保留可合法办理的已发生事实和已保存新分支，不将其包装为正式整改有效、放行或人工 Exit。
