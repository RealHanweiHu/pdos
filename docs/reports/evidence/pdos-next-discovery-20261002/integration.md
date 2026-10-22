# 主线接线合同

## 入口和所有权

领域入口：`pdos-next/server/pdos_next/domain/discovery/handlers.py::Discovery`。DTO：`schemas/discovery/contracts.py`。端口：`domain/discovery/ports.py`。具体来源守卫：`domain/discovery/sources.py::PinnedSources`。独立 UI：`web/src/components/discovery/index.ts`，业务页不含 fixture。

唯一正式定义写入口仍为 `domain/products/definitions.py::apply_draft`。本包没有定义表、Spec 表、项目表、确认表或回执表，也没有数据库连接/commit。ResearchPort 和 DefinitionPort 是调用者 Session 的适配合同，不是可直接暴露给浏览器/模型的授权接口。

## 必须先冻结的真实范围

1. 主线提供 `Authority`，从当前服务器会话绑定 tenant、human actor、真实 `scope_id`、用途、受众和当前写授权/取消状态；模型或 payload 不可提交这些事实。私有研究仅所有者可消费，受众必须保持一致。本包目前仅支持具名人工写入；AI 输入可以作为观察材料，执行身份仍为具名人工。未来 AI 执行必须另接真实资格、Run 和取消守卫。
2. 研究可以没有 Product/Project。当前共同 `Command.product_id` 和 `Artifact.product_id` 都是必填；主线需增加真实研究 scope 的共同命令/来源关联与 ACL，而不是创建虚拟 Product/Project。研究 scope 未绑定时 `SCOPE_BINDING_REQUIRED`；已有授权 Artifact 关联研究也须服务器记录真实授权关系。
3. 定义预览/交付才需要 `Authority.product_id/product_revision` 和真实用途。缺少时 `PRODUCT_BINDING_REQUIRED`；不能从标题、模型参数或 UI 标签推出绑定。每条研究来源须获得该目标 Product 的使用权限，PinnedSources 将逐条检查 `allowed_product_ids`。本包不自动搬运或复制来源到 Product。
4. OEM 完整性类别由 `required_categories` 当前服务器政策给出。空集合表示未绑定适用规则，UI 不显示“完整”。有缺类别/未选组需要 `partial_reason`；本轮原文/并列冲突仍在候选 provenance 中。资料类别齐全只表示已登记，不表示技术正确或客户批准。

## 持久化与当前来源端口

主线新增真实 Research 聚合持久化，至少存 DTO 的 `id/tenant_id/owner_id/audience/scope_id/revision/title/mode/questions/use_cases/items/observations`。JSON 聚合明细可保留每条 Observation/Citation 和上次 Verification；当前核验不依赖历史 verdict。显式租户/研究 ACL、唯一 ID、revision CAS、只插入新研究、不可覆写观察身份。按真实迁移 head 分配公共迁移与 RLS；本包没有预留迁移号。

`ResearchPort.locked` 必须先按 tenant + scope 锁聚合并重核 ACL；不能只以请求的 ID 读取。`record` 在调用者 Session 中保存 Mutation，和现有 Receipt/Audit/Outbox 同事务。`before_revision=0` 只插入，不 upsert；其他 CAS 原版。`replayed_content=True` 不新建观察或领域版本。主线仍负责共同 command key、同 key 不同 payload 冲突、跨 key 稳定意图锁/回放 ACL和实际回执；`intent_digest` 仅提供内容去重，不能建立平行回执系统。

为 PinnedSources 实现 `SourceReader.read(authority, citation)`，在共同事务里按确定顺序锁 Artifact/原件及其权限/关系。返回 `SourceSnapshot` 的当前可信内容与访问事实：当前 tenant/revision/active/readable/visibility、允许研究/Product、正文与正文摘要、真实 original_id/不可变存储 version/hash/原件安全可用状态、主线 locator_map。`Citation.location` 和原件身份由上传/解析映射得到，不接受模型替换；文本 Artifact 的直接位置必须等于 derived_line。

PinnedSources 覆盖逐项 ACL/版本/哈希/位置守卫，并对完整结构化 JSON `{key, kind, statement, spec}` 做窄范围全字段比较，原字段 Decimal 以精确字符串表示、缺项必须为 null/空数组。重复 JSON 字段拒绝确定性验证。普通 PDF/单元格/自然语言不冒充自动语义验证，返回 pending；可以替换 SourcePort.verify 为主线现有确定性字段解析/已核验人工记录适配，但必须核对所有字段与原位置，不可只检查引用存在。

`accepted_requirement_id` 仅候选引用。SourcePort.verify 的 `accepted_requirement=True` 必须重新读取具名已接受、当前有效、同 scope、同内容/来源的真实记录。默认 PinnedSources 永不授该状态；本包无发布规格状态。Verification.status 仅字段对应关系，不能充当事实成熟度或审批。

## 预览、确认、定义写入的一个事务

1. `preview(authority, research_id, expected_revision, CandidateRequest)` 读取并核对全部来源包（包括未选择组），不消费意图或确认。返回 `DefinitionCandidate`。候选摘要绑定研究完整内容、当前字段核验、全部来源、服务器 authority、目标 Product 版本、固定父定义、部分导入范围与逐组原因。无法核实的规格只保留原值于 provenance，映射规格为 unknown；方法/条件/单位不会冒充已核验事实。
2. 将 `candidate.payload` 接入现有实质预览，展示当前定义与此候选的差异、影响、并列证据、unknowns、missing/omitted 和来源位置。UI `DefinitionSelection.onPreview` 只进入该共同办理区，`confirmationSlot` 允许放已有组件。没有本包 onConfirm/token 存储。整个定义候选是一个原子组，逐组选择影响 payload，不表示逐组后端确认事务。
3. canonical `product.research.start` T0、`product.definition.draft` T0、`product.definition.update` T1、`product.definition.publish` T2 保持。政策层级不因本包而改变。当前人工草稿/导入路径由主线注册实际支持动作并守卫；T1 仍固定载荷一次确认，T0 AI 仍需真实资格+当前授权，T2 本包不执行。没有资格时继续人工路径。
4. 主线通过现有共同命令框架处理 request key/稳定意图/当前授权、Product/父定义/研究/来源读集锁和确认到期/撤销；同事务重建 authority，并执行 `handoff(..., fixed_digest)`。fixed_digest 必须来自服务器已绑定预览，不是客户端自行计算的批准。本包重算摘要并在漂移时 `PREVIEW_CHANGED`；来源失效更早失败。既有框架消费一次确认，DefinitionPort 不再消费第二次。
5. `DefinitionPort.draft` 适配 `domain/products` 所有者。构造它要求的 canonical Command、expected_revision 和去重 SourceRead（Artifact ID/expected_revision），使用 candidate.payload；仍执行其人类身份/当前 Product/父版/负责人/原文行/受众检查及版本冲突规则。候选每条规格 state 保持 needs_confirmation；不会通过选择自动发布。父版本“当前最新可见”由定义所有者判断。
6. 主线为 DefinitionCandidate 的 `provenance/conflicts/missing_categories/omitted_keys/research_id/research_revision/digest` 提供持久关联，不能只存 DefinitionDraftPayload 丢失原文、并列值、适用范围、具名选择和核验性质。保存真实研究→DefinitionRevision 引用；无第二套 Definition/Spec 表。
7. DefinitionRevision/Spec、研究消费关联、共同确认消费、Receipt/Audit/Outbox 同事务提交；owner 的任何拒绝或后续 Outbox 写失败全部回滚。本包不自己 commit，也不做 DB 内 LLM/网页/远程等待。

## 未注册内部动作

`start` 对应 canonical research.started；`ingest` 产生内部候选事件名 `discovery.sources_imported`，尚未进入共同事件/命令目录。研究观察录入、来源类别登记、字段核验记录、候选组选择/具名裁决候选与部分导入均须主线明确内部动作及其适用政策，不能从 T0/T1 名字自动取得 AI 权限或绕过共同回执。选择默认只进入读预览；若需要持久单独裁决，则先由主线冻结具名决定/事件语义。

## UI 与当前读取

- `ResearchStart` 的 scope/readiness 来自服务器；无范围/port 时禁用。`onStart` 保存真实研究后由父页面读取结果。
- `SourceImport` 只接主线已核验且有权限的 `SourceOption`，精确 Citation 不可在表单编辑。每条可带多个原位置；值、范围、单位/允差以字符串，条件逐行保存。不做前端浮点归一，不用零补值。回调返回实际后主线刷新研究。
- `SourcePackage` 只接 `inspect` 重核后的 Research；权限变化时传 `research=null` 与已净化原因，不能把旧原文或派生内容继续留在父页面。服务端先 fail closed，UI 隐藏只作展示。
- `DefinitionSelection` 传具名选择原因与整体 CandidateRequest，不传 actor/tenant/policy。目标产品及用途是服务器上下文只读信息。`CandidateReading` 显示真正服务器候选；无候选显示等待。
- 父页面在对象/来源/权限变更时丢弃旧 candidate 与共同确认，保留用户输入并重新展示实质差异。不会显示合成成功或本包虚构回执。

## 主线最小联合验证

先核对隔离 DB 与研究 scope，再执行持久化/RLS/并发 CAS、同 key 内容冲突、换 key 重复意图、进程重启读取、来源/原件权限及撤回、字段核验漂移、确认过期/更改/取消、父定义变化、未选来源失效和定义/审计/Outbox 失败回滚；确认消费与定义副作用各一次。源权限改变时的派生页面要实际净化。

HTTP/浏览器验证真实来源包→人工观察→并列冲突/未知→具名选择→共同预览/一次确认→产品定义所有者结果/回执，含弱网重复和实际 keyboard/小尺寸/双主题。OEM 不要求重做市场策略；无项目研究不创建虚假对象；缺单位/条件与正式发布阻断分别检查 AT-01/03/06 适用范围。上述 DB/HTTP/浏览器、G/N/P/Q 联合验收本包没有执行。
