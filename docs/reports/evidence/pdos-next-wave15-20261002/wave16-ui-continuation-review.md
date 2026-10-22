# Wave16 品质整改界面续接评估

2026-10-02，只读建议。依据 [Wave16 草案](../../../design/2026-10-02-pdos-next-wave16-quality-followup-draft.md)和当前质量 / 变更入口；草案尚未冻结实施合同，本次未改业务 / UI 源码，未操作浏览器、数据库或运行验证。Wave15 当前演练由主线统一办理。

**最小界面闭环：当前 Issue / CAPA → 具名根因 → 本人实际措施完成 → 固定新对象回链 → 独立复验缺项。** 新 Run、观察期和独立人真实就绪后，才开放有效性 T2；Issue 关闭另一次 T2。八 facet 未知的 Change 保留未批准状态，不能以 CAPA 完成绕过变更批准或声称制造生效。

## 1. 可复用与需适配的入口

| 现有资产 | 可复用部分 | Wave16 必须补的边界 |
|---|---|---|
| `web/src/components/builds/build-quality-loop.tsx` | 明确 Build / logical Run / Issue 与版本选择；原测量和实际执行历史；完整行出处；当前 authority / caps；读取消、同原请求恢复、成功后刷新失败分离 | 建议新增独占 `build-quality-followup.tsx` 及 helper，在同一当前 Issue / CAPA 固定版读取后续。不能将仅支持七个旧动作的 `qualityTier` / `validQualityPreview` 当成新 T2 协议。 |
| `build-quality-loop-view.ts::qualitySource/qualityEvent` | 有效 Artifact 的完整行 UTF-8 摘要；aware 发生时间与原 IANA；不补 now；内容 / scope 变更重核 | 根因结论使用具名决定时钟，不能误用 completion 事件钟。完成必须选既有 action key；精确复验引用由服务器提供，不能用公开 SourceRef 自造“独立、适用、通过”事实。 |
| `quality_issues/reading.tsx::QualityIssueReading` / `FailureReading` | 固定失败、假设与具名根因、措施完成状态、政策 / 失败覆盖、有效性及历史决定、来源失效提示 | reader DTO 只有完成布尔和来源，没有完整 completion 发生 / 接收时钟与 owner 输出证明。新的时间 / 回链卡须保留这些字段。现 `mapIssueReading` 对 `root_cause` 或 effectiveness 直接返回 null，需要新精确映射，不能凭支持展示就宣称主线已接通。 |
| `quality_issues/workbench.tsx` / `editor.ts` | 根因、既有未完成措施选择、复验候选和关闭表单的业务布局与缺项文案 | 属独立纯 UI 包，camelCase intent、PreparedAction 与宿主 common command 不同，不可直接当公开 payload。其有效性默认 effective、原生 multiple select 和可选责任人也不宜直接沿用：新增入口明确选择结论，用手机可逐项操作的证据卡，完成执行者固定当前本人。 |
| `quality_issues/review.tsx` | T1“一次确认”、T2“具名提交此决定”、未知回执禁止重提的语义 | 实际仍接 common preview 返回的完整 command，T2 对应 approval_token / named proof；不要重造旧包 token / digest 或弱化为通用“确认”。 |
| `BuildResults` 与现有准备 / Formal / Handoff / Launch 入口 | 原报告 → 原值 → 固定计算 → 具名复核 / 处置，双配置 / 样件 / 执行计划 / 实际开测 / 自身占用历史 | 新复验使用新请求（每逻辑请求 oneRun）；原失败 Run 不复用，破坏性已消费样件不重用。入口链接仅指向真实既有对象 / owner，不暗中创建或把计划 / 草稿回执当实际完成。 |
| `ChangeControlReading` 与当前 Change / Graph 卡 | 固定根、工程 / 制造已知路径、显式 unknown、历史版、源失效 | 待 Order / Implementation / Effectivity 端口真实接通。八 facet UNKNOWN 继续阻断批准；CAPA、Issue 与 Change 的状态、决定和关闭分别显示。 |

## 2. 三类新增表单应怎样呈现

### 具名根因：T2，保留假设

固定显示当前 Issue 版、CAPA key、全部失败 / 样件 / 实际配置与原假设，填写**具名根因结论**和可核验精确出处。当前 draft 指向已有 `quality.issue.root_cause.decide` 纯核，公开合同仍待冻结；服务器必须给 operation-specific authority / caps、来源 / 政策版本及拒绝理由。

预览对照“原假设 / 旧结论”与“将追加的具名结论、办理人、证据、固定范围”。纯核 NamedConclusion 的决定时刻由服务器真实保存时记录；预览应是稳定的未保存占位，不要求用户填写一个“实际完成时间”来代替决定钟。保留旧假设，不能覆盖已有根因；根因确认不等于措施有效、Change 批准或问题关闭。

### 实际措施完成：T1，本人逐项记录

仅列当前 CAPA **已指派给本人且尚无 completion** 的真实措施；显示原计划内容 / kind / 责任人 / 固定要求及已完成历史。用户明确选择 action key、填写实际执行内容、已发生的 offset ISO 时点、原 IANA、行动证据并另选事件出处。复用遏制的精确行和 EventTime 表单，但 ID 来自已有措施，不能生成新的 containment 身份替换 action。

每项独立显示实际发生时间、服务器接收 / 保存时间及来源；批量完成时各项仍保留自己的事件。代填、未来时间、未知 action、已有 completion 或续版冲突不得提交。部分完成继续 actioning；全完成才 awaiting_verification，仍不自动根因、有效性或关闭。

涉及正式变更实施的措施要单独展示固定 Change / Order / 实际输出 proof 与其批准 / 实施 / 生效状态。未知或未批准时，允许记录真实研究草稿、独立试验或其他已发生行为，但文案和输出类型不得称“批准变更已实施”。不能给一个人工勾选框把 draft 变成 implementation。

### 新对象回链与独立复验：先证据，后决定

回链只选择服务器逐 owner 核验的真实固定输出：新配置、Build、Preparation / Formal、Run / Projection 与必要 item key；显示名称 / revision、目的、nature、当前来源与状态。计划、草稿、实际产出、实际开测分别呈现。按每条原 failure 显示新测试 pair / 实际配置 / 方法 / 判据适用映射，不让“总结果 pass”掩盖遗漏。

复验候选卡至少显示：固定 CAPA 要求与摘要；新 Run / Projection / 原报告定位；原失败→新 pair 覆盖；全部测试 / 措施 / 遏制 / 根因参与者；具名独立 verifier；方法 / 判据 / 改变配置的当前适用依据；实测 observed_from / observed_until、CAPA observation_until 与当前观察期缺项；规则版本、政策 / 专业 / 原件安全 basis、来源读集和真实 / synthetic 标记。current / applicable / independence / computed result 由可信 bridge 给出，不从输入或 UI 比较推断。

事件钟互相独立：措施发生 / 系统接收，测试实际开测 / 结束 / 观测，规定观察截止，证据复核 / 有效性决定 / 关闭时刻。空钟显示“未记录 / 未核对”，不填 now、窗口或计划日期。已保存 Run 占用是自身历史效果，不宣称资源当前可用。

## 3. 有效性和关闭的批准卡

canonical `quality.capa.effectiveness.decide` 仍为 T2。选择完整当前证据后，服务端重核全部措施完成、根因、观察期和**精确全部原失败集合**；新观察须在措施完成之后，覆盖规定截止，不能未来观察或复用原失败 Run / 混用 synthetic 与 real。

独立性不能只检查“不是当前操作者”：须列出原测试、措施、遏制、根因决定、新证据测试的所有参与者；复核人 / 决定人不得在排除集合中。高 / 关键风险或独立政策还须服务器判定证据复核人本人办理。资格不足与未知分别说明，不从 ProductGrant 或已存在 duty 推断。

建议结论选择初始为空：**有效**须全部证据确定 pass；**无效**须有确定 fail；unknown / indeterminate / invalid 保留待输入，不能自动选择 ineffective。完整实质预览绑定本 Issue / CAPA、政策与证据 read_digest，明确“具名有效性决定”及当前缺项，不沿用 Wave15 T1 标题。

有效决定保存后，关闭仍是独立 T2，并重核同一政策 / 证据摘要与纯核规定的有效性复核人本人。界面分别显示措施完成、独立有效性、Issue 关闭、Change 验证 / 关闭、工程 / 制造 / 客户放行；不联动关闭或释放占用。ineffective 后没有追加措施 / 根因更正公开合同，保持历史及待整改，不提供再次 draft / patch JSON 绕过按钮。

## 4. 新 GET / preview 最少需要的读字段

按明确 selected Issue / CAPA 读取，避免首屏全产品历史深查。既有 IssueView 保留 immutable version row 与 logical 身份、current pointer、scope / purpose / audience、sources / readset、逐操作 caps / authority / blockers；历史固定版显示当前资格未评估，不能把 null 映为失败或可办。

新增：完整根因及决定时钟；每 action 的本人可办 capability 和完整 completion EventTime / 接收钟；RemediationLink 的 output identity / owner receipt / status / ChangeOrder 关系；可见 CapaVerificationEvidence 候选、当前性 / 适用性、上述覆盖映射、全部 executors / 独立人及观察期缺项。原报告位置必须区分派生 Artifact 行与原件 page / cell / original-line；Artifact SourceRef 整行摘要由现 helper生成，原件 byte hash / 安全 epoch / locator proof 由服务器守卫。

公共输入 / 预览 / 执行继续一份 CommonCommand、Receipt / AuditOutbox 和 UOW；T1 / T2 prepared command 原封提交。新增 replay 不能只重放旧成功，而跳过当前权限 / 来源 / issuer / policy 守卫。Scope / actor / revision 变化废弃预览并清除不可读派生内容，未知提交只恢复同 key / payload，成功后刷新失败只读回而不重发。

## 5. 最小手机操作检查（待主线执行）

冻结候选后仅选受影响闭环集中检查；此处是检查计划，不是已通过结果：

1. **320 / 390px、亮暗各一轮**：选 Issue → 当前 / 历史版 → 根因 → 一项本人完成 → 回链 / 证据。长标题、整行中文 / JSON、长单位、IANA、参与者和固定名称能换行，不横向撑屏；内部 UUID / 摘要留技术折叠。
2. **来源与时间可操作**：源 option 可辨认标题 / 版本 / 行，完整行另有可展开阅读；根因多来源与复验证据用逐卡勾选，避免手机原生 multiple select 难操作。offset 时间和 IANA 分开保留，无默认 now，软键盘不遮住下一字段。
3. **T1 / T2 可区分**：窄屏预览堆叠保存前 / 将保存，全部范围 / 独立性 / 时钟 / 缺项可滚动查看；T2 按钮明确“具名决定”。主按钮可触及、有可见焦点，不被弹窗底部或键盘遮挡；提交一次、忙碌锁定。
4. **部分与未知**：另一人措施、历史版、观察期未到、漏一 failure、复验未知、私有证据不可读各显示具体当前原因，按钮禁用；不能只有灰按钮或把 null 显为 0 / 否 / 已完成。
5. **恢复**：T1 / T2 提交未知后返回 / 重载仍恢复同请求，禁止新动作；成功后模拟读失败只提示刷新；切换当前 actor / 私人 scope 清敏感派生内容，不把旧证据缓存给新身份。
6. **下一轮边界**：由固定输出进入真实现有准备 / Handoff / Launch / Results 入口，看到新请求 oneRun 和新样件身份；原失败 Run / 原消费记录不变。未到独立复验条件时止于已保存事实与明确缺项，不展示假有效、假关闭或假正式实施。

后续实施可沿 Wave16 草案 A 整改办理、B 复验桥、C 新 wrapper 三路并行；先冻操作分级、Issue writer / evidence DTO 与公共 preview，主线统一迁移、接线及页面 / PG 检查。本文件不授权这些实施、不继承旧纯组件检查为新闭环验收。
