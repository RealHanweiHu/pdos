# Wave17 候选、观察、独立复核与两次 T2 · 最小页面接线方案

状态：只读接线建议，未实施页面或公共接口。本次只新增此文档；未编辑 web/server/staging，未运行测试、数据库、HTTP、浏览器或构建。依据冻结的暂存施工合同、effectiveness 草案 §9–12、[facts 最终复核](facts-independent-review.md)及[paired 最终差异复核](ui-proof-final-delta-review.md)。暂存 DTO 和结构证明不能作为当前资格、原件字节或真实同事务批准的授权依据；公共 GET、inputs、辅助操作及 companion 持久化仍待 Root 冻结。

## 最短可用路径

在现有“问题与变更”入口中保留原调查/整改页，新增一个并列的独立验证区，不重组导航。建议以后独占 `web/src/components/quality/build-capa-effectiveness.tsx`、`web/src/lib/build-capa-effectiveness-view.ts` 及同名 helper 测试；当前不创建这些文件。基础 props 沿 `BuildQualityFollowup` 的 `product/principalId/api/onSaved`。若父页已有明确选择，是否增加受控的 Build/Issue 选择 props 由 Root 冻结，不能靠跨面板 localStorage 猜选。

| 步骤 | 用户看到/填写 | 必须来自服务器的事实和门槛 |
|---|---|---|
| 1. 选择调查与固定版 | 显式选择 Build → Issue → 当前/历史版；展示原失败、根因、每项完成、验证要求和原来源 | 实际 Current、稳定完成锚、有限谱系、精确 owner/当前 caller。历史只读；无根因、未全完成、needs_recheck 或当前来源不可核对时列缺项，不进入决定 |
| 2. 选择真正新复验及晚回链 | 查看新请求/Run 的实际执行、样件/项目/配置、原报告与确定投影；按服务器实际选项保存另一条晚回链 | Current Formal 和 Current Run 分别核；Run 的 originating Formal 只作历史起点。原 Draft Link 仍是 planned 历史，不能自动替换为 performed；缺 paired owner 则不提供可办理选项 |
| 3. 保存固定候选 | 给全部原失败选择服务器返回的新样件/item/Measurement/Projection 映射；逐项看缺项、原值和适用依据；T1 一次确认 | 候选固定完整锚、晚回链、真正新 logical Run 和不可变版，不用原失败 Run 复验。客户端不能填写结果、适用/独立/观察 complete 标记；缺项候选可保留，不能显示“验证通过” |
| 4. 读取规则、记录实际观察 | 只读可信规则的抽样目标、最少记录、方法/接受依据及观察窗口；填实际观察起止、逐目标实际记录/来源及事件钟，T1 一次确认 | Rule 的 issuer/epoch/期限、全部失败/措施绑定来自可信宿主导入；页面不发布规则。目标、采样完整性和原值结构由真实 owner 核验，不提供任意 JSON 或“观察完成”复选框 |
| 5. 具名独立复核 | 固定候选/规则/观察版本；逐失败核方法与判据适用，逐措施核 investigation/formal_change/unknown 履行分类、理由与来源；独立 T2 实质预览 | 完整参与者及专业/政策事实由服务器核出，只读显示。可核对的适用结论是 applicable/not_applicable/unknown；不能由 UI 排除自己、改参与名单或把存在完成/输出当履行满足 |
| 6. 有效性决定 | 展示核出的完整证据、实际观察、全部失败/措施覆盖及当前独立资格；单独具名 T2 办理 effective 或 ineffective | `quality.capa.effectiveness.decide`；真实当前允许时才显示可办理。unknown/indeterminate/缺资料不是 ineffective，不能用“否”代替未知。保存只追加一个 Issue 后继，ineffective 仍待验证，不自动增措施/关闭 |
| 7. 另次具名关闭 | 成功后先刷新 Issue Current 与同一证据；查看来源、政策及专业资格重新核对，再单独 T2 关闭 | `quality.issue.close`；须紧随 effective、同一原有效性决定者当前合格，另一条命令和另一实际 T2 证明。不可“有效并关闭”一次提交；缺新核对则保留有效性历史并禁关闭 |

第一次正向独立用例应使用从源头即合法共享的新失败调查。现 private 调查只展示其当前可读历史/缺项，不能改变 visibility、借 Product 写权授予独立人或复制原失败制造共享场景。场景 `nature=synthetic` 或 authority.synthetic 必须明确“本地合成演练，不代表真实产品有效性、生产资格或人工出口”。

## 已有组件与辅助逻辑怎么复用

`BuildQualityFollowup` 已有显式 Build/Issue/version 选择、精确 SourceRef 阅读、逐操作服务器资格、实质预览 dialog、T1/T2 区分、固定历史、敏感作用域清理和原请求恢复。这些流程可复用；其中 `SourceReading/Details/Authority/RefChoices` 是组件内私有函数，不能直接导入。最小方案是在新独占组件沿用其样式和交互，若要抽成共享组件须 Root 另明确文件归属，不为接线暗改旧页。

可复用已导出的 `followupStable/followupSame`（递归对象键排序、数组顺序保留）、`followupReads`（冲突或 >20 明确失败）、精确 `followupSource/validFollowupSource`、`followupTime/followupZone`、`followupCancelled/followupFailureRecovery` 和现有 `FollowupApi` 调用形式。时间校验返回原 ISO 文本，保留微秒与 offset；不能用 `Date.toISOString()` 重写实际事实。来源引用显示可读标题、版本、整行 quote/定位；原件报告的 original_line/fragment 与派生 Artifact 行分开展示，不能自己推等价。

不能直接复用以下封闭校验：`FollowupOperation/followupTier/followupCapability` 仅覆盖 Wave16 三操作；`FollowupCommand/validFollowupInputs/validFollowupPreview/validFollowupReceipt/restoreFollowupLocal` 也绑定旧操作/目标/回执 family。Wave17 应新建冻结 allowlist 和逐动作校验，不能强转类型或默认 T1。既有 source_options 中的精确引用原样提交，不能为“易读”改 position；名称适配仅展示副本。

## 暂存 DTO 对应的页面材料

这些是服务端读取材料，不是拟议的客户端写 payload。页面不提交 FactAtom、authority_snapshot、消费 UUID、Receipt/事务组或客户端计算的 hash 作为可信事实。

| 已有暂存材料 | 最小展示/编辑边界 | 还缺的公开形状 |
|---|---|---|
| `StructuralPairProof`、`PairBinding` | 分别显示 current_formal/current_run/origin_formal，真实 owner 与本次 writer、planned/performed、实际流程和只读保存占用；结构核对只能说“结构已核” | 当前真实 owner 核验状态、missing、当前能力、可读名称/样件模穴/测试项/固定配置及精确 refs。`structural_only=true` 永不转为 allowed=true |
| `FactBase/FactRef` | 固定不可变行+revision、前版、scope/purpose/nature、原锚及要求、真实保存钟与来源；摘要可折叠 | Current/historical 指针与可读 ACL、source_status、完整缺项；不能用 created_at 排序猜 Current，也不能把保存成功当最新资格 |
| `RuleVersion/SamplingRequirement` | 只读 issuer/版本/时效、全部失败与措施、method/criterion、目标、min records、观察区间及是否要求 Run review/disposition | 可信规则选项/真实导入资格和原文说明；没有配置就显示“规则未接通”，不开放客户端自授规则 |
| `ObservationVersion/ObservationRecord` | 实际 observed_from/until、逐目标 occurred_at/IANA、原文出处和 missing_fields；保留空缺 | 有界常用记录字段、可读目标选项、精确原文如何核 raw_material/采样覆盖、事件 source 与 actor 绑定。未冻结前不把内部 dict 暴露为 JSON 编辑器 |
| `NamedReview` | 每个失败精确 pair_applicability、每个 action_fulfillment 的分类/结论/理由/来源；参与者和原/new executor 名单只读；固定观察 refs、实际 at、有效边界 | 可办理 Reviewer 与独立性结果、真实方法/判据/实际配置 owner 依据、来源选项、T2 payload/preview。Review.applicable 也不代 CAPA effective |
| `FactInspection` 与 owner missing | 按 code/detail、目标/字段显示未知、not_applicable、观察不足、来源/期限/独立性失效；无端口明确未配置 | Root 统一业务缺项 DTO 与 `operations[op]` 精确能力，不能因缺 missing 字段显示“全部齐备” |

所有来源闭包由服务端返回：原完成锚和失败、晚回链/pair/原报告、候选、Rule、全部 Observation、Review、专业/政策出处，以及合法后继新增来源。并集最多20，冲突或超限整体失败并提示缩小合法范围/补合同，不截前20、不删旧失效来源让核对“变绿”。UI 只保留服务器 Artifact read-set，领域资格/Rule/Receipt UUID 不伪装 Artifact 引用。

## 一次确认、未知与异常恢复

沿既有 `inputs → preview → 人工确认 → execute` 阶段，但每一动作单独保存原完整 Command。inputs 是只读核对，不能消耗证明；公共路径仍待 Root 冻结，API 参数采用现有 wrapper 的 `v1/...` 无前导斜杠形式。所有预览只接受同 command_id/key/product/operation/expected_revision、原语义 payload 和完整读集、正确 tier/目标/前后版/authority 的服务器 prepared command，最终原封提交。

实际观察/Review 事件时间不默填 now；原微秒/offset/IANA 保留，空钟明确未知。只有服务器即将生成的保存/决定/接收钟在 preview 使用 null + 明确保存时记录说明；不归一 actual observation、测量或措施完成钟。每次切换 actor/product/Issue/version、规则/候选/观察/复核版或当前来源/资格时，废弃可见旧 preview；尚未确定的 execute 原命令仍锁定，不能借 scope 切换另造一次写入。

真正 timeout/500/普通409 保留 stage execute、原 key/token/readset/payload，并只提供“核对原请求”。成功 Receipt 优先于随后刷新失败：显示“已保存，读取尚未完成”，不重发。401/403 先清私有 context、选项、草稿和持久敏感状态，仍保留已成功且不可重发的提示。READ_SUPERSEDED 只取消过时读；当前读取消/失败结束自己的 loading 并保留禁写/只读重试，旧响应不得清新读 loading。perform 接管读 sequence 时也结束被接管的 loading。

Wave16 的 `FOLLOWUP_CONFIRMATION_EXPIRED` 恢复仅冻结旧三操作，不能扩用到 Wave17。新操作若需要过期重预览，必须由 Root 先冻结：服务器在锁内完整去重确认未保存、原未消费 proof 确实到期、Current/材料仍精确匹配，并返回绑定原命令去 token 的限定 recovery。UI 验证完整深相等后只解锁手动“重新预览”，保留原 command_id/key/语义/readset；不自动预览、批准或接受普通409。

新 localStorage 使用新 schema/namespace，绑定 principal/product 与固定选择；保留部分表单、精确 refs 和原 pending command，逐字段限长/校验。不得把 Wave16 三操作恢复器放宽到新 family，或把旧桶中的 private 来源拷入新 actor。前后两次 T2 分别产生明确阶段/回执，第一条成功后才重读关闭资格；关闭失败不清有效性事实。

## Root 必须先冻结的字段与接线

1. **公开读取/index：** 明确选 Build/Issue 的有界过滤与历史参数；真实 Current、anchor/lineage、候选/晚回链、规则/观察/Review 列表及固定 refs、可读名称、缺项和分页。历史资格未评估须明确标志和 null，不展示肯定能力。不得为首屏深读全部产品历史。
2. **逐动作资格：** selected-row 的 allowed/prepare capability、当前 authority/qualified/null、专业用途/期限/nature、禁止原因。能填写实际观察/Review 不等于事实已核；inputs.allowed 才准进入预览。参与者全名单及独立性只能来自真实 owner，当前 caller 和历史系列 owner/writer 分别显示。
3. **公共写 payload 与 family：** candidate T1、observation T1、Review T2 的最终 operation/event/subject_type、必填 refs/CAS、事实时间和来源字段、partial/续版规则；Rule 是 host_import，不设普通 UI 自授入口。两 canonical T2 使用草案的 `quality.capa.effectiveness.decide/quality.issue.close`，但公共 registry/具体 payload 仍须 Root 冻结。两个最终 Receipt family 为新不可变 Issue 版 `quality_issue`；其他 companion family 不猜。
4. **预览/恢复：** before/after 的精确目标、server_on_save 字段白名单、source/authority/readset、T2 named_decision/write_tier/approval_token、回执和窄过期恢复协议。新观察/Review 写 payload 不应直接收内部 FactBase/FactAtom 整包。
5. **实际可信与存储：** paired reader、七类 facts owner、bytes/current ACL/issuer 重核及所有 IO 后 fresh clock；同 Session/UOW 的 T1/T2 consume、Invocation.decision_id、single Issue append、reciprocal atom/CAS/ReceiptAuditOutbox。UI 不暴露 Session 或 phase，不把 inputs 的 positive 缓存作 execute 资格。缺任一 host 即明确 missing/503，不提供有效性/关闭成功路径。

前端可在这些字段冻结后，与 A/B 的真实 companion/owner adapter 及 Root 的迁移/公共接线并行，只改独占新组件/helper/tests。公共挂载、BFF 注册、两 T2 元数据/数据库守卫及统一浏览器/事务验证均由 Root 完成；本方案没有公共路由实现或性能改善结论。

## 最小受影响检查建议（本次未执行）

- helpers：mixed current/historical、unknown 与 ineffective 分离、全部失败/措施映射、不同 Current Formal/Run 不强等版本、Draft Link 不升 performed、来源冲突/>20、微秒/offset保留、正确 tier/family/同 command/readset、成功后401/403清私有但不重发、限定恢复码与旧读取消竞态。
- 主线整链：共享独立正例与旧 private 缺项；部分观察/not_applicable/indeterminate 分路；有效性成功后关闭前 source/issuer/专业 ABA 拒绝并保留历史；两个命令/两个证明、Current CAS、同事务反向原子与 SAVEPOINT/回滚、跨 key 单 Receipt。
- 手机：320/390 宽按“选择 → 查看缺项 → 精确来源 → 单项填写 → 完整预览”操作；长 title/purpose/单位/quote 换行，dialog 可滚动、按钮可触及、T2姓名/影响/范围在确认前可读；亮暗主题及1440由 Root 在冻结候选集中验证。

## 本次读取快照

| 路径 | SHA256 |
|---|---|
| `web/src/components/builds/build-quality-followup.tsx` | `c459e5bc07b5e66f84acd17081c572aab9fce8fe543839dc44dcec7989bb4a40` |
| `web/src/lib/build-quality-followup-view.ts` | `8a216f69b378eed95839ccb76b3f02740e24449ae32bfc3f2c55475a95612f5a` |
| `staging/wave17/facts.py` | `a9c06b974300729fe8953f1c7b85ec5a5c3ceb57416bc4d81c0c79f708083f50` |
| `staging/wave17/paired.py` | `3cff4b1534533b2797f201faceede7e2a9514d84240ca06c6953b1de20dce750` |

上表路径相对 `pdos-next/`，是本次只读快照，不冻结 Root 正在修复/验证的公共候选。本方案不声明实际 Link、观察、具名 Review、有效性或关闭已保存；G3、真实资格、生产及人工 Exit 边界保持。
