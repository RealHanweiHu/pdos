# pdos-next · M3 实施合同：品类研究到立项（S1 第一个闭环）

日期：2026-10-08。**状态：草案；原待定问题 Q1–Q10（§9）与工具名单 v0.2（§4）已由用户 2026-10-08 定案并落入正文；同日与技能包草稿做一致性收尾（§2.2、§2.6、§2.7、§5.3、§5.4、§10）；同日按确认稿 §8 P7 的 7 项细则与 P8 收尾三项补入正文（§2.9、§2.13、§2.14、§3.1、§3.4–§3.6、§4、§5.4、§5.5、§7.2、§8、§10）；同日按 P9 新增 `evidence.claim.withdraw`（§3.1、§3.6–§3.8、§4、§5.4、§10）；其余部分待用户审阅。** 本稿不改代码、不改迁移。

**性质**：细化 [v1.1](2026-10-08-pdos-complete-target-architecture-v1.1.md) §09.2 路径 A 的施工合同。只细化，不加严、不扩范围（v1.1 §00.4）。需要加严、新增操作或拿不准的点，列入 §10 未解决项，由用户拍板后再改正文。

**依据**：v1.1 §00.3、§02.1–§02.4、§02.3a、§02.9、§02.14（I21–I24）、§03.3、§03.12、§03.14、§05.3/§05.4/§05.8、§06（含 §06.1 隔离子任务、§06.3 公开研究）、§07.5、§07.11、§08.3/§08.6/§08.7/§08.11、§09.2、附录 A/B；[设计确认稿](2026-10-08-pdos-next-design-confirmation.md) C1–C14 与 §8 决策 P1–P9（P5 工具名单 v0.2、P6 本合同 Q1–Q10 结论、P7 合同与技能包 7 项细则、P8 收尾三项，下文记作 P7-1 至 P7-7、P8-1 至 P8-3；P9 新增 `evidence.claim.withdraw`）；[S0 实施计划](2026-10-08-pdos-next-s0-refactoring-plan.md) §4.1、§5；[立项前改造方案](2026-10-05-preproject-redesign.md) §3–§5；[小Pai 执行计划](2026-10-07-xiaopai-product-execution-plan.md) M3 退出判据。

**并行产出共用约定**：品类示例 `auto-tire-inflator`（汽车充气泵）、`bicycle-pump`（自行车打气筒），种子资料在 `docs/design/category-seeds/`；技能包草稿在 `docs/design/skills-draft/<key>.md`。本合同只按键名引用，不复述其内容。

**沿用的 pdos-next 约定**（只取命名与流程，不依赖行号；相关文件正由 S0 重构）：命令信封 `Command{command_id, idempotency_key, operation, category_id, product_id?, expected_revision, source_read_set, payload}`，操作名 → payload 类登记在 `PAYLOADS`；档位由服务器封闭登记（`T1_OPERATIONS`、`T2_OPERATIONS`）；T1 先 `commands/preview` 取 `confirmation_token` 再执行，T2 取 `approval_token` 且只许具名本人、无 run；`Row` 基类带 `tenant_id/created_at`，作用域列自动加 `(tenant_id, category_id[, product_id])` 复合外键；领域行与 `action_receipts`、`audit_entries`、`outbox_events`、`request_keys` 同事务；错误为 `{code, message, detail.reason}`。

## 0. 原工程已知缺陷与对策

| 原工程缺陷 | 本合同对策 | 位置 |
|---|---|---|
| 作者可自批 G0（提交时未排除负责人） | 领域层检查 + 数据库 CHECK 与复合外键兜底；评审人下拉不列本人 | §2.9、§3.3、§3.4 |
| 提案是否私有取决于模型给的入口标签（`entry_kind=odm`） | payload 不含可见性；一律私有创建；有效可见性由服务器按实际引用的私有来源计算；改共享只经负责人在页面执行 `proposal.share`，小Pai 只准备（§9 Q9） | §2.5、§3.6 |
| AI 研究笔记以 `human_shared` 落库 | 来源（origin）由服务器按执行身份判定，payload 无 origin；人确认 AI 内容后仍是 `ai_draft`，另记 `confirmed_by` | §2.0 |
| 品类资料一改，在审提案就无法批准（`sources_match` 阻断） | 提交时固定品类背景快照（对象 ID + 版本）；之后品类变化只提示不阻断 | §3.4、AT-53 |
| 列表字段写死 `max_length=20` 等业务上限 | 只保留请求大小与分页上限 | §2.0、§4 |

## 1. 范围与依赖

### 1.1 M3 交付（v1.1 §09.2 路径 A）
小Pai 对话澄清 → 品类（共享知识、规格字典）→ 公开研究（子任务台账、片段核对）→ 立项提案（客户需求、自主新品、派生迭代）→ G0 立项评审 → 建项目（绑定型号定义 v1，待决问题转任务/风险）。

| 交付 | 内容 |
|---|---|
| 品类 | 品类键与初始资料组；品类知识（只追加、撤回链、去标识沉淀与证明）；规格字典（参数版本） |
| 立项提案 | 三入口、一案一页；条目级编辑（T0 / T1 / 人工）；待决问题；方案对比；风险；决策记录；默认私有与人工共享 |
| G0 | 负责人提交（T1）；评审人具名决定（T2）；批准后同事务生成型号或变体、型号定义 v1、项目、项目待办 |
| 建项目收紧 | 删除 `project.create` 过渡 T1 入口（决策 P2），建项目只随 G0 |
| 小Pai | 新建品类对话、品类内立项对话、Grill me、候选与一次确认、过程面板、工具名单 v0.2（§4）、技能包 ↔ 工具绑定（§5.4）、客户原件与导入文件隔离抽取（§4.2） |
| 证据登记 | 抽取行与公开观察登记为 Claim、关联到提案条目（`evidence.claim.record`、`evidence.link.create`，T0） |
| 视图 | 立项视图第一批：定位图、规格对标、功能配置、定义成熟度（含冻结前阻断项清单，§9 Q4） |
| 平台 | 型号 ↔ 平台关联（T1），平台不存在时同一命令顺带新建（§9 Q5） |

### 1.2 依赖 B1–B3
| 依赖 | 提供方 | M3 用法 | 10/08 只读核对 |
|---|---|---|---|
| Category、Grant（以品类为根）、ObjectAudience | B1 | 范围根、成员、指定受众；G0 评审资格读 Grant 的 `product_manager` 能力（§9 Q1） | 已有 `categories`、`grants(can_write, expires_at, access_epoch)`、`object_audiences`；Grant 尚无能力字段 |
| 以品类为第一键的 RLS 与判定函数 | B1 | M3 新表复用 | 计划中（S0 V3） |
| `category.create`（最小版）、`category.member.grant`（T2） | B1 | M3 扩展 create 的 payload；grant 小Pai 只准备 | 已有 `category_scope.py` |
| 共同命令、请求内证明、回执/审计/Outbox、错误目录、可注入时钟 | B2 | 所有 M3 命令 | 已有 `request_proof.py`、`errors.py` |
| Product、DefinitionRevision、`definition_specs`、变体派生 `variants.py` | B3 | G0 生成型号/变体与定义 v1 | 已有 |
| Project、ProjectProductLink、建项目过渡入口 | B3 | G0 建项目；M3 收紧 | 已有；`project.create` 在 T1 集合 |
| 原件上传、扫描、解析、定位 | B3 | 客户 RFQ 原件挂到提案，导入的评论、退货文件挂到品类或提案；`evidence.artifact.read` 按定位分页读解析结果 | 现要求 product_id 非空 |
| Claim、EvidenceReference 与 `evidence.claim.record` / `evidence.link.create`（附录 A，T0） | B3（证据模块） | 抽取行、公开观察登记为 Claim 并关联提案条目（§2.14） | 未核对；B3 未建齐时 M3 在本号段补 |
| 配置/BOM、三方差异 `domain/products/variants.py`（S0 §6.2 唯一实现） | B3 | `product.baseline.read` 返回 BOM；`calc.derivation_diff` 包装该实现 | S0 计划中 |
| 模具（Tooling）、认证资料 | B6（制造）/ B3（定义与证据） | `product.baseline.read` 返回模具与认证引用 | 未核对；对象未建或无记录时如实返回空，见 §4.1 |

M3 开工前须由主会话在公共文件补齐的缺口（按 S0 §4.1，公共文件只由主会话修改；未补则作为 M3 第一批交主会话）：

| 缺口（10/08 代码） | 影响 | 需要的结果 |
|---|---|---|
| `action_receipts` 唯一键为 `(tenant, product_id, intent_digest)` | 品类级命令 product_id 为空，意图去重失效（I16） | 按 `(tenant, category_id, intent_digest)` 去重，或 NULLS NOT DISTINCT |
| `confirmations` 与预览以型号及其 revision 为确认主体 | 提案、品类级 T1/T2 无法预览 | 主体改为 `(subject_type, subject_id, subject_revision)` |
| `uploaded_originals`、`artifact_versions` 的 product_id 非空 | 立项前客户原件无处挂 | 允许为空（S0 §5.1 已写品类级对象可空） |
| `ai.run.revert` 只按单条回执撤回 | AT-55 需整次运行撤回 | payload 支持 `run_id` |
| Grant 只有 `can_write`，无能力字段 | G0 评审资格无法表示（§9 Q1） | B1 Grant 表增加能力 `product_manager`，经 `category.member.grant`（T2）授予；**须改 S0 B1，由主会话转告 Codex** |

### 1.3 依赖 M2
| 依赖 | M3 用法 |
|---|---|
| Agent 图（prepare_context / model / route / tools / verify / finalize）；interrupt 与 Temporal signal 恢复 | 立项对话、Grill me、T1 候选等待；verify 节点回填计数（§4.4） |
| 工具注册表：由命令登记表生成，ToolSpec 含 tier、operation_key、taint、parallel_safe | M3 新命令登记后自动成为工具；工具名单 v0.2 见 §4 |
| `skill.load` 与技能包配置；未加载技能时拒绝其写工具 | §5.4 绑定 |
| 隔离子任务（§06.1：只读、不给写工具、只交回结构化结果） | `research.fanout` 的子任务；M3 的 `evidence.extract` 复用同一机制（§4.2） |
| 公开研究：`research.search` / `research.read` / `research.fanout`、台账、片段子串核对、覆盖说明由代码生成 | 品类候选、自主新品提案；接口见 §4.3 |
| `research.snapshot.register` 与 PublicWebSnapshot | 知识与竞品引用（字段要求见 §2.4） |
| ProviderDataAgreement 与服务器端出站检查 | 客户资料进模型（含 `evidence.extract` 子任务）；查询词过滤 |
| 会话、SSE 事件流、过程面板事件 | §5.5 |
| 取消释放预算、对账出口 | AT-60/61 在立项对话中复跑 |
| TenantSkillEnablement 与 T0 资格检查 | 试点 T0；M3 只做资格检查，资格登记界面留 M4（§9 Q3） |

### 1.4 明确不做
- 规格冻结 `product.definition.publish`、专业协审、定义转需求、G1（项目内工作，§03.14）。AT-06 第三句由定义成熟度视图列出阻断项验收（§9 Q4）。
- 立项视图第二、三批（含品类矩阵）；现有型号目标细分/目标价的编辑入口（随品类矩阵做）。
- 技能包目录与资格登记界面（M4，§9 Q3）、MCP 连接器接入（M7）、本地全文索引与爬虫。
- G0 决定撤回、提案撤销（v1.1 有状态、无操作，§9 Q7 定本期不做）。
- 私有提案的待决问题分派给受众以外的专家（§9 Q6）。
- 同一型号修改（走 ChangeRequest）；报价与客户沟通（留在 CRM）；Excel 批量导入器（存量型号用已有型号创建 + `product.definition.draft`，条目 origin=imported）。
- 不新增顶层错误码、业务数量上限或时间窗。

## 2. 领域对象与表

### 2.0 共同约定
| 约定 | 内容 |
|---|---|
| 作用域 | 品类内表都有 `tenant_id, category_id`（NOT NULL）复合外键到 categories；挂型号的同时带 product_id 复合外键；RLS 第一键为 category（§7.2） |
| 只追加 | 标"只追加"的表用 BEFORE UPDATE OR DELETE 触发器拒绝改删；纠正靠追加新版本或撤回记录 |
| Current 落库 | 每条谱系一行当前态（current_version、状态），与追加行同事务维护（§08.11-1） |
| 署名与来源（provenance） | 每个内容版本行：`origin`（human / ai_draft / imported）、`writer_id`（AI 时为小Pai 身份）、`run_id`（AI 写入必填）、`confirmed_by`（人经 T1 确认 AI 内容时填写）、`receipt_id`。origin 由服务器按执行身份与路径判定，payload 不含 origin（I23） |
| 人工值 | 当前版本 origin=human，或 confirmed_by 非空。小Pai 直写（T0）不得取代，只能转 T1 候选 |
| 金额与数量 | numeric(38,12)；币种 char(3)、口径、时点分列；缺值为 NULL，不填零 |
| 版本 | `revision` / `version` int > 0；命令按 expected 版本校验 |
| 长度与条数 | 不设业务条数上限；单字段长度只受请求大小约束 |

### 2.1 Category（B1 已建 + M3 补）
B1 已有：id、tenant_id、name、purpose、owner_id、revision、status。M3 补 `key`（text，小写连字符，如 `auto-tire-inflator`；租户内唯一；创建后不改）与 `created_by_run_id`（uuid null）。品类边界、用户与场景、地区、研究问题（含品类候选中的显式假设）都存为知识条目（§2.2），修改走追加，不另设品类更新操作。

### 2.2 CategoryKnowledge
`category_knowledge_entries`（只追加）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id、tenant_id、category_id | uuid | |
| lineage_id、version | uuid、int | 同一条知识的谱系；UNIQUE(tenant, lineage_id, version) |
| action | text | add / supersede / withdraw |
| kind | text | boundary / segment / competitor / voice / regulation / research_question |
| content | jsonb | 按 kind 的 Pydantic 结构校验 |
| regions | text[] | 适用地区 |
| source_refs | jsonb | 只允许品类可见来源：快照（id + 定位 + 原文片段）、品类可见原件定位、具名人工陈述；不得引用私有原件或私有提案（I22） |
| withdraw_reason | text null | action=withdraw 时必填 |
| provenance 列 | — | §2.0 |

`category_knowledge_current`：PK(tenant, lineage_id)；category_id、kind、current_entry_id、current_version、status（active / withdrawn）、origin。索引 (tenant, category_id, kind, status)。

content 要点：**competitor** = brand、model、metrics[{parameter_id, parameter_version, value / lower / upper / text, unit, condition_note, nature: measured / claimed / inferred / unknown, source_ref}]、prices[{amount, currency, observed_on, price_type: retail / promo / unknown, includes_tax, includes_shipping, channel, region, source_ref}]、features[{parameter_id, parameter_version, value, nature, source_ref}]（nature 与 Claim 性质的对应见 §2.14）；**voice** = 分组标签、样本量（代码统计）、代表片段（须为所引快照或品类可见原件在定位处的正文子串；导入的评论、退货文件经 `evidence.extract` 读取，P7-4）、来源平台；**segment** = 细分、JTBD、购买标准、渠道、地区；**research_question** = question、assumption（可选，结构同 §2.6 assumption；品类候选的显式假设在 category.create 时以此保存，品类不另设假设种类）。

### 2.3 ParameterVersion（规格字典）
`parameter_versions`（只追加）：

| 字段 | 类型 | 说明 |
|---|---|---|
| id、tenant_id、category_id | uuid | |
| parameter_id、version | uuid、int | 稳定参数 ID；UNIQUE(tenant, parameter_id, version) |
| key、name | text | UNIQUE(tenant, category_id, key, version) |
| value_type | text | number / range / text / boolean / enum |
| enum_values | jsonb null | enum 时 |
| unit、standard_condition、method、acceptance_criterion | text null | 未知为 NULL，不补造（§02.3a） |
| direction | text | higher / lower / target / neutral |
| replaces_version、change_note | int null、text | 修订时指向旧版本并写原因 |
| provenance 列 | — | |

`parameter_current`：PK(tenant, parameter_id)；category_id、key、current_version。
旧版本永不改。旧条目由人逐条改引用（`proposal.item.patch`），不自动映射。不同 (parameter_id, version, unit, 工况) 一律不当同口径（AT-51）。

### 2.4 PublicWebSnapshot（M2 建，M3 核对字段）
M3 需要：id、tenant、category_id、url、final_url、title、summary、retrieved_at、正文（markdown 或受控存储键）、content_hash、provider、credibility、status、registered_by_run_id、receipt_id。片段核对只对正文做子串匹配。M2 未建齐时，M3 在本号段补列。

新建品类的对话发生在品类存在之前。已定（§9 Q8）：读取结果先留在运行作业库（只存引用与内容哈希），`category.create` 确认时在同一事务里登记为该品类快照（§3.5）；若 M2 已有同等方案，以 M2 为准。

### 2.5 Proposal（头表，可变）
| 字段 | 类型 | 说明 |
|---|---|---|
| id、tenant_id、category_id | uuid | UNIQUE(tenant, category_id, id) |
| owner_id | uuid | = 创建请求者；M3 不提供改负责人 |
| title | text | |
| entry_kind | text | customer_request / new_product / derivative；只决定小Pai 方法，不决定可见性 |
| target_kind | text | new_product / new_variant |
| baseline_product_id、baseline_definition_id、baseline_definition_revision | uuid、uuid、int null | derivative 或 new_variant 时必填（CHECK） |
| customer_identities | jsonb | 客户名称与别名（客户需求入口）；用于出站过滤与去标识检查；随提案受众读取 |
| visibility | text | private / category / audience；默认 private；只有 `proposal.share` 能改 |
| private_source_count | int | 引用的私有来源数，服务器维护 |
| effective_visibility | text | private_source_count > 0 时为 private，否则 = visibility；RLS 读它 |
| status | text | draft / in_review / approved / returned / rejected / withdrawn（withdrawn 本期无入口） |
| revision | int | 每次保存递增 |
| current_submission_id | uuid null | in_review 时指向提交 |
| context_hint | bool | 引用的品类资料有新版本或已撤回；只提示，不阻断 |
| created_by_run_id | uuid null | |

索引：(tenant, category_id, status)、(tenant, category_id, owner_id)。

### 2.6 ProposalRevision 与条目
| 表 | 性质 | 字段要点 |
|---|---|---|
| `proposal_revisions` | 只追加 | proposal_id、revision（UNIQUE(tenant, proposal_id, revision)）、changed_items[{item_id, version}]、actor_id、run_id、receipt_id、document_digest |
| `proposal_items` | 当前态 | PK(tenant, item_id)；proposal_id、kind、current_version、removed、sort_key |
| `proposal_item_versions` | 只追加 | item_id、version、kind ∈ section / option / risk / decision_note / difference / commercial_target / assumption；content jsonb（按 kind 校验）；source_refs；provenance |
| `proposal_spec_items` | 只追加 | item_id、version、SpecItem 列（§2.7）、provenance |
| `proposal_questions` | 只追加 | item_id、version、OpenQuestion 列（§2.8）、provenance |
| `proposal_sources` | 可变链接 | proposal_id、source_type（original / snapshot / knowledge / definition）、source_id、source_version、privacy（private / shared）；变化与 private_source_count 同事务 |

content 要点：**section** 的 key = worth_it（证据摘要）、target_customer_market_channel、features_in_out（含明确不做的）、certification_regions、launch_window、summary；**commercial_target** = target_price、cost、volume，各自 amount、currency、basis、as_of、source，缺值 NULL；**option** = name、summary、rough_cost{low, high, currency}、cycle{low, high, unit}、tradeoffs、kind（new / status_quo / do_nothing）、sources；**difference**（派生）= area ∈ specification / bom / certification / tooling / cost / other、item_ref（覆盖路径：参数版本、BOM 行、认证项、模具或成本项引用，other 写简短路径说明；v1.1 §02.4）、change（added / removed / changed）、baseline、proposed、propagation（direct：改动本身或计算工具直接给出 / inferred：传导推断，impact 须写推断链）、impact、sources；`calc.derivation_diff` 只算前四类，cost 的数值来自 `calc.cost_subtotal`；**decision_note** = 取舍与理由；**assumption**（显式假设，v1.1 §05.4）= statement（内容）、basis（依据：来源引用，或"用户未答"等说明）、validation（待验证方式与回看时机）、related_item_ids（关联条目）；假设不是事实，按普通条目随提案修订、随 G0 固定副本。

### 2.7 SpecItem（提案与型号定义共用）
同一组列（一个 ORM mixin + 一个 Pydantic 模型）用于 `proposal_spec_items` 与 `definition_specs`。

| 字段 | 类型 | 说明 |
|---|---|---|
| item_key | text | 引用参数时 = 字典 key；未映射的自由键保留并标"未映射" |
| parameter_id、parameter_version | uuid、int null | 复合外键到 parameter_versions，且须同品类 |
| value_type | text | 同字典 |
| value、lower、upper、tolerance | numeric(38,12) null | lower ≤ upper；tolerance ≥ 0 |
| text_value | text null | |
| unit | text null | 引用参数时须等于字典 unit；不同则拒绝，差异写成待决问题 |
| condition_note | text null | 与标准工况不同时填写；有值即不与标准工况同口径比较；不写例外 |
| verification_method | text null | 验证方法（v1.1 §02.3"判定/验证方法"之验证） |
| acceptance_criterion | text null | 判定判据（通过条件，v1.1 §02.3"判定/验证方法"之判定）；来源给出时填写，未给出为 NULL，不补造 |
| modality | text null | must / should / may / prohibited / unstated；只按原文措辞（客户需求条目），不由语气推断；其他来源为 NULL |
| exceptions | jsonb | 原文例外与适用范围：[{text（逐字）, applies_to（变体、地区、工况或时段）}]；空 = 原文无例外；不并入值或 condition_note |
| applicable_variants | jsonb | 空 = 全部 |
| source_refs | jsonb | 快照/原件定位、知识谱系 + 版本、具名人工决定 |
| item_status | text | ai_draft / confirmed / expert_pending / unknown |
| availability | text | known / unknown / conflicted / not_applicable（not_applicable 须写理由） |
| owner_id | uuid null | 条目负责人 |

规则：AI 直写或 AI 候选的 item_status 只能是 ai_draft / expert_pending / unknown，confirmed 只能由人写（§05.4）；confirmed 需有值（或不适用加理由）和至少一个来源，具名人工决定可作来源；"10–20 条关键规格"只在成熟度视图提示，不作提交条件。`definition_specs` 现有 state、nature 列由 SpecItem 列取代；若 B3 已按 v1.1 建好，M3 只补参数版本外键与 provenance。

### 2.8 OpenQuestion
`proposal_questions` 的列：question、owner_id（必填）、due_date（date，必填）、related_item_ids、status（open / answered / carried）、answer、supersedes_item_id（改派时指向旧问题）。G0 批准后 status=carried，并记录去向（`project_open_items.id`）。

### 2.9 ProposalSubmission / ProposalDecision（G0）
`proposal_submissions`（只追加）：id、tenant、category_id、proposal_id、revision、owner_id、reviewer_id、frozen_document（全部当前条目的固定副本）、document_digest、context_refs[{type: knowledge / parameter / snapshot / definition, id, version}]、option_count、no_alternative_reason、receipt_id。
约束：CHECK(reviewer_id <> owner_id)；UNIQUE(tenant, proposal_id, revision)；UNIQUE(tenant, id, owner_id, reviewer_id)（供决定表复合外键）。

`proposal_decisions`（只追加）：id、tenant、category_id、proposal_id、submission_id、owner_id、decided_by、outcome（approved / returned / rejected）、rationale、selected_option_item_id、dispositions[{subject_type: question / spec_item, subject_id, kind: task / risk, owner_id, due_date, note, audience_added（服务器判定、payload 不含：该负责人原不在型号受众内、由本决定加入型号与项目受众时为真，P7-2）}]、project_owner_id、project_owner_audience_added（同上，针对项目负责人，P8-2）、signer_grant_snapshot（签署时授权与 `product_manager` 能力，§03.12、§9 Q1）、review_digest、created_product_id、created_definition_id、created_project_id、receipt_id。
约束：UNIQUE(tenant, submission_id)；复合外键 (tenant, submission_id, owner_id, decided_by) → submissions(tenant, id, owner_id, reviewer_id)；CHECK(decided_by <> owner_id)。不可改写。

### 2.10 PromotionProof（只追加，私有）
`promotion_proofs`：id、tenant、category_id、knowledge_entry_id、source_proposal_id、source_proposal_revision、source_item_refs（私有回链只在这里）、deidentified_by、deidentified_at、checks{refs_clean, filenames_clean, identities_clean, overlap_warnings}、receipt_id。只有源提案的读者可读（§7.2）。共享知识行不存任何回链。

### 2.11 Platform / PlatformProductLink
`platforms`（租户级，跨品类）：id、tenant、code（租户内唯一）、name、description、provenance。平台只由 `platform.link.create` 顺带新建（§3.6、§9 Q5），不另设创建操作。`platform_product_links`（只追加）：tenant、category_id、product_id、platform_id、version、action（attach / detach）、compatibility、platform_version、reason、provenance；UNIQUE(tenant, product_id, platform_id, version)。`platform_link_current`：PK(tenant, product_id, platform_id)；current_version、attached。

### 2.12 Product / Definition / Project 补充字段
| 表 | 补充字段 | 说明 |
|---|---|---|
| products | target_price、target_price_currency、target_price_basis（retail / promo / unknown）、target_price_includes_tax、target_price_as_of、import_status（imported_unreviewed / reviewed / null）、parent_product_id | G0 从提案 commercial_target 写入 |
| product_target_segments | tenant、category_id、product_id、segment_lineage_id、segment_version | 指向 kind=segment 的知识 |
| definition_revisions | source_proposal_id、source_submission_id、source_proposal_revision、g0_decision_id、sealed | G0 生成的 v1 sealed=true，触发器禁止修改；后续修订生成 v2 |
| projects | trigger_type（proposal / customer_request / parent_product）、trigger_id、g0_decision_id | 收紧后 g0_decision_id NOT NULL |

### 2.13 G0 转入项目的任务与风险（§9 Q2 已定）
现有 `project_tasks` 必须挂计划与工作包，而 G0 时还没有计划。新表 `project_open_items`（G0 批准时在同一事务生成）：tenant、category_id、product_id、project_id、kind（task / risk）、title、owner_id、due_date、status（task 初始 assigned，risk 初始 open）、source_question_id 或 source_spec_item_id、g0_decision_id。G1 计划可引用它。分派不等于承诺（AT-34），所以任务初始为 assigned。处置负责人、项目负责人不在私有提案受众内时，由同一决定加入该型号与项目的受众（P7-2、P8-2，§3.4），因而能读到自己的待办与项目。

### 2.14 Claim 与证据关联（B3 证据模块建，M3 核对字段）
`evidence.claim.record`、`evidence.link.create` 是附录 A 已有的 T0 操作，M3 用于：把 `evidence.extract` 的抽取行和公开研究的观察登记为 Claim，再关联到提案条目或品类知识。M3 需要的字段：

| 对象 | 字段要点 |
|---|---|
| Claim | id、tenant、category_id、proposal_id（来源为私有原件，或登记运行接触过私有资料时必填，见下）、source{kind: artifact / snapshot, id, version, locator, quote}、nature（observed / extracted / computed / inferred / decided，§02.9）、vendor_claimed（bool，默认 false；只在 nature=extracted 时可为真，P7-5）、availability（§02.9）、content（按技能输出 schema：parameter_id / version、value / lower / upper、unit、condition_note、modality、exceptions、verification_method、acceptance_criterion、text）、privacy（服务器判定，payload 不含，见下）、extraction_ref（抽取作业或台账行）、provenance 列 |
| 证据关联 | id、tenant、category_id、evidence{type: claim / snapshot / artifact, id, version, locator}、target{type: proposal_item / knowledge_entry / definition_spec, id, version}、relation（按 B3 证据模块定义）、provenance 列 |

规则：quote 须是来源正文在 locator 处的逐字子串（确定性代码核对）；关联到提案条目时按 Claim 的来源（原件或快照）计入 `proposal_sources` 与 private_source_count。B3 未建齐时，M3 在本号段补列。
- **可读范围（P7-6）**：来源为私有原件，或登记它的运行接触过私有资料（服务器按运行上下文判定，与 §3.5 private_context_run 同一判定），Claim 为私有：带 proposal_id，可读范围 = 提案受众（proposal_reader），随提案保持私有；来源是公开快照也不按来源推定为品类可读。提案经 `proposal.share` 改为共享时，这些 Claim 随提案受众一起变为可见，因此共享预览逐条列出它们并做身份检查，负责人确认后才执行（P8-3，§3.6）。其余 Claim 按来源（快照来源品类成员可读）。私有 Claim 不能关联到品类知识等共享目标（I22）。
- **数据性质映射（P7-5）**：§2.2 competitor 的 measured（实测）→ observed；claimed（宣传）→ extracted 且 vendor_claimed=true（来源是品牌、厂商或卖家对自家产品的声称，如官网规格、零售页标称）；inferred（推断）→ inferred；unknown（未知）不对应任何性质，保持 availability=unknown。客户需求、用户原话等其他原文抽取为 extracted、vendor_claimed=false。视图按此区分实测、宣传、推断、未知（§6.3）。

## 3. 命令

### 3.0 共同规则
| 规则 | 内容 |
|---|---|
| 入口 | `POST /v1/categories/{category_id}/commands` 与 `.../commands/preview`；`category.create` 例外（§6.2）。页面、小Pai、事件用同一命令 |
| 可信上下文 | tenant、actor、requester、run、grant、cancel_epoch 由服务器绑定；payload 不含 origin、owner；visibility 只在 share 中出现 |
| T0（小Pai） | 需：已加载对应技能包、当前授权、"租户 × 技能包 × 模型版本"资格。缺资格返回 QUALIFICATION_REQUIRED，小Pai 改出 T1 候选 |
| T1 候选 | 小Pai 生成 ConfirmationBatch（独立组 + 依赖）→ interrupt → 人打开确认框（内容来自服务器 preview）→ 一次确认执行。执行者是人；payload 带 `prepared_by_run_id`、`candidate_digest`，服务器核对该运行属于同一请求者与品类。AI 起草的内容 origin=ai_draft、writer=小Pai、confirmed_by=人 |
| 人工直接编辑 | origin=human |
| T2 | 只由具名本人凭 approval_token 执行，ctx.run_id 必须为空；小Pai 只准备材料 |
| 幂等 | 同 (actor, idempotency_key) 同载荷直接返回原回执，只核当前读权限，不因确认过期而失败（§08.3）；同键不同载荷 DUPLICATE_INTENT_CONFLICT；服务器另算意图摘要，换 key 不能重复写 |
| 校验范围 | 请求内一次证明：直接来源 + 版本/水位比较；完整重证只在 G0 决定提交前一次（§08.11） |
| 有效期 | 只有 T1 确认令牌有有效期（沿用 B2 设定）；其他都在提交时比版本 |
| 同事务 | 领域行 + 当前态 + 回执 + 审计 + Outbox；事件载荷只放 ID 与版本，不放客户正文 |
| 错误 | 只用 §08.7 的 16 个顶层标识，原因放 detail.reason（§3.8） |

### 3.1 命令总表
| 操作 | 档位 | 谁执行 | 前置条件 | 事务内写入 | 事件 |
|---|---|---|---|---|---|
| research.snapshot.register | T0 | 小Pai（M2 定义） | 品类写权；地址与出站守卫 | 快照 | research.snapshot_registered |
| category.knowledge.add | T0 | 小Pai（有资格）或品类写者 | 来源都品类可见；AI 运行无私有上下文 | 知识行 + 当前态 | category.knowledge_added |
| proposal.item.patch | T0 | 小Pai（有资格）或提案写者 | 提案 draft / returned；不取代人工值 | 条目版本 + 当前态 + 修订 + 来源计数 | proposal.item_patched |
| product.definition.item.patch | T0 | 小Pai（有资格）或定义写者 | 目标定义 draft 且 sealed=false | definition_specs 新版本 | definition.item_patched |
| evidence.claim.record | T0 | 小Pai（有资格）或对象写者 | 来源可读；quote 为逐字子串；私有判定（§2.14、§3.6） | Claim | claim.recorded |
| evidence.link.create | T0 | 小Pai（有资格）或对象写者 | 证据与目标都可读；私有证据不关联共享目标 | 证据关联 + 来源计数 | evidence.linked |
| evidence.claim.withdraw（P9） | T1 | 人一次确认（小Pai 可预填）：私有 Claim 由所在提案负责人，品类可读 Claim 由品类写者 | Claim 可读；未被已签署的 G0 决定或封存定义消费 | 撤回记录（只追加）+ 关联失效 + 引用条目标记来源已撤回 | claim.withdrawn |
| category.create | T1 | 人（候选可预填） | 人工确认共享内容已去客户身份 | 品类 + 负责人授权 + 初始知识/参数/快照 | category.created |
| category.knowledge.promote | T1 | 能读源提案的人 | 去标识确认 + 检查通过 | 知识行 + 当前态 + PromotionProof | category.knowledge_promoted |
| category.knowledge.withdraw | T1 | 品类写者 | 当前版本匹配 | 撤回行 + 当前态 | category.knowledge_withdrawn |
| category.parameter.publish | T1 | 品类写者 | 当前版本匹配；key 不冲突；私有上下文运行准备的候选过身份检查（§3.5） | 参数版本 + 当前态 | category.parameter_published |
| proposal.create | T1 | 品类写者（成为负责人） | 入口与基线一致 | 提案 + 条目 + 问题 + 来源 + 受众 | proposal.created |
| proposal.question.create | T1 | 提案写者 | 问题负责人能读提案 | 问题版本 + 当前态 + 修订 | proposal.question_created |
| proposal.share | T1 | 仅负责人本人，仅页面；小Pai 只准备（§9 Q9） | 无私有来源；私有上下文 Claim 过身份检查并经负责人确认（§3.6） | 可见性 + 受众 | proposal.shared |
| proposal.g0.submit | T1 | 仅负责人本人；小Pai 只准备 | §3.3 | 提交副本 + 状态 | proposal.g0_submitted |
| platform.link.create | T1 | 型号写者（候选可预填） | 型号可见；平台已存在或随本命令新建（§9 Q5） | 链接版本 + 当前态（+ 新平台） | platform.linked |
| proposal.g0.decide | T2 | 仅本次具名评审人；小Pai 只准备 | §3.4 | 决定 + 型号/变体 + 定义 v1 + 项目 + 项目待办 | proposal.g0_decided、project.created |
| category.member.grant | T2 | 品类负责人（B1）；小Pai 只准备 | B1 规则；可授予 `product_manager` 能力（§9 Q1） | B1 | category.member_granted |
| project.create | T2（随 G0） | 无独立入口；小Pai 只准备 | — | 只在 g0.decide 内 | project.created |

### 3.2 proposal.item.patch（T0 / T1 / 人工）
payload：proposal_id；ops[{op: upsert / remove, item_id | null, kind, base_version | null, content}]；source_refs。T1 路径另带 prepared_by_run_id、candidate_digest、confirmation_token。

| 项 | 规则 |
|---|---|
| 并发 | 按条目 base_version 比较，不比整份提案；无关条目变化不冲突（§08.11-2） |
| 不覆盖人工值 | 小Pai 直写的目标是人工值 → CONFIRMATION_REQUIRED（reason=human_value_protected），小Pai 改出 T1 候选（AT-35） |
| 条目状态 | AI 不得写 confirmed → VALIDATION_FAILED（reason=ai_cannot_confirm） |
| 参数 | 参数版本须同品类；unit 与字典一致，否则 VALIDATION_FAILED（reason=parameter_unit_mismatch） |
| 私有来源 | 引用私有原件后 private_source_count 增加，有效可见性随之变为 private，页面说明原因 |
| 锁定 | in_review / approved / rejected 时拒绝 → VERSION_CONFLICT（reason=proposal_locked） |
| 待决问题 | kind=question 只改 answer、status；AI 写的回答保持 ai_draft，不能把问题置为 answered |
| 运行撤回 | `ai.run.revert`（T1）按 run 追加补偿版本：只恢复"当前版本仍是该运行所写"的条目；人改过的保留并在回执列明；人经 T1 确认过的内容不随运行撤回 |
| 意图摘要 | (proposal_id, item_id, base_version, content 摘要, writer) |

### 3.3 proposal.g0.submit（T1，仅负责人）
payload：proposal_id、expected_revision、reviewer_id、no_alternative_reason（方案少于 2 个时必填）、confirmation_token。

| 检查 | 失败 |
|---|---|
| 执行者是提案负责人本人（人、无 run） | NAMED_DECISION_REQUIRED（reason=owner_only） |
| 状态 draft 或 returned，revision 一致 | VERSION_CONFLICT |
| reviewer_id ≠ owner_id（领域检查；数据库 CHECK 兜底） | VALIDATION_FAILED（reason=reviewer_is_owner） |
| 评审人是品类有效成员，且其 Grant 带 `product_manager` 能力（仅 can_write 不够，§9 Q1） | FORBIDDEN_SCOPE（reason=reviewer_not_eligible） |
| worth_it 段落非空 | VALIDATION_FAILED（reason=narrative_missing） |
| option 条目 ≥ 2，或填写 no_alternative_reason（AT-54） | VALIDATION_FAILED（reason=options_insufficient） |

写入：`proposal_submissions`（固定副本、context_refs、digest）；status=in_review；current_submission_id；评审人注意项。评审人因提交获得该提案读权限（§7.2 proposal_reader），不另写受众行。
不检查：规格条数、条目是否全部确认、品类资料是否最新。未知项可以带入 G0（AT-06）。

### 3.4 proposal.g0.decide（T2，仅评审人）
payload：proposal_id、submission_id、expected_revision、outcome、rationale、selected_option_item_id、dispositions[]、project{name, owner_id（默认提案负责人）}、new_identity{name}（默认提案标题）、approval_token。

| 检查（完整重证，只做这一次） | 失败 |
|---|---|
| 执行者 = 本次提交的 reviewer_id，人、无 run、≠ 负责人 | NAMED_DECISION_REQUIRED（reason=reviewer_only） |
| 提案 in_review 且 current_submission_id 一致 | VERSION_CONFLICT（reason=submission_superseded） |
| 评审人此刻仍是有效成员并带 `product_manager` 能力（写入 signer_grant_snapshot） | FORBIDDEN_SCOPE（reason=reviewer_not_eligible） |
| rationale 非空 | VALIDATION_FAILED |
| approved：有方案时须选定一个 | VALIDATION_FAILED（reason=option_not_selected） |
| approved：固定副本中每个 open 问题、每个 item_status 为 unknown / expert_pending 或 availability 为 unknown / conflicted 的规格条目（含 ai_draft，确认稿 P11）都有处置（task 或 risk、负责人、期限）；not_applicable 不需要 | VALIDATION_FAILED（reason=unknown_without_disposition） |
| 处置负责人、项目负责人是品类有效成员（二者都不必在提案受众内，§9 Q6 只约束 G0 前的问题分派；受众外的随决定加入受众，P7-2、P8-2） | VALIDATION_FAILED（reason=assignee_not_member） |
| 基线定义仍可读（new_variant / derivative） | SOURCE_UNAVAILABLE |
| outcome=approved：提案自身引用的原件在评审期间已撤回（§9 Q10） | SOURCE_STALE（reason=original_withdrawn）；评审人改为退回，负责人处理来源后重新提交 |
| 品类资料自提交后有变化 | 不阻断；评审页提示；决定按提交时 context_refs（AT-53） |

approved 在同一事务内完成（全部是本库写入，无网络等待；不经 Outbox 拆分）：
1. 写 `proposal_decisions`；提案 status=approved。
2. target_kind=new_product：建型号（同品类；可见性继承提案有效可见性，私有时受众 = 负责人、评审人，加上不在提案受众内的处置负责人与项目负责人，P7-2、P8-2），写目标价与目标细分。new_variant：用 B3 `variants.py`，以基线定义为固定父版派生变体（受众规则同上）。
3. 建 `definition_revisions` v1：sealed=true，记录来源提案、提交版本与 g0_decision_id；`definition_specs` 从固定副本逐条复制，item_status 原样保留（AI 草稿仍是 ai_draft）。
4. 建项目：trigger_type（自主新品 = proposal，客户需求 = customer_request，派生 = parent_product）、trigger_id、g0_decision_id；ProjectProductLink 绑定定义 v1（I02）；型号私有时，项目受众写入同一批人。
5. 按处置建 `project_open_items`；对应问题 status=carried；由本决定加入受众的处置负责人在 dispositions 中记 audience_added=true（P7-2），项目负责人记 project_owner_audience_added=true（P8-2）。
6. 回执 result 列出所有新对象 ID 与因本决定加入受众的处置负责人、项目负责人（预览同样列出）；Outbox：proposal.g0_decided、project.created。

returned：写决定，status=returned；负责人修改后重新提交（新 submission）。rejected：终态。
幂等：UNIQUE(submission_id)；同令牌同载荷重放返回原回执。G0 不产生规格冻结、专业签名、BOM 批准或客户承诺（§03.14）。

**建项目收紧（P2）**：本命令验收后，从 T1 集合与 PAYLOADS 删除 `project.create`，回执里的"过渡入口"标记随之消失。S2–S4 测试夹具改为走 G0 路径或领域夹具，夹具不暴露为 API。

### 3.5 品类、知识与字典
**category.create（T1）**：payload：key、name、purpose、groups{knowledge[]、parameters[]、snapshot_refs[]}、deidentified_confirmed（必须为真）、prepared_by_run_id、candidate_digest、idempotency_key、confirmation_token。groups 是可取消勾选的独立组，都依赖品类本身。写入：品类、负责人授权（按 B1）、初始知识（AI 起草的 origin=ai_draft）、初始参数版本、研究快照（从运行作业库在同一事务登记为新品类快照，核对内容哈希，§9 Q8）。拒绝：key 已存在 → VALIDATION_FAILED（key_taken）；未确认去标识 → CONFIRMATION_REQUIRED（deidentification_not_confirmed）；引用私有来源 → VALIDATION_FAILED（private_source_in_shared）。

**category.knowledge.add（T0）**：payload：kind、content、regions、source_refs、supersedes{lineage_id, expected_version}（纠正时）。origin 由服务器判定。小Pai 的运行上下文含私有资料（客户原件或私有提案）时拒绝 → FORBIDDEN_SCOPE（private_context_run），这类内容只能走 promote。引用片段不是快照正文子串 → VALIDATION_FAILED（quote_not_in_snapshot）；引用品类可见原件（如导入的评论、退货文件）时片段不是该定位正文子串 → VALIDATION_FAILED（quote_not_in_source）。取代人工条目转 T1。竞品指标的参数版本须属本品类。

**category.knowledge.promote（T1，去标识沉淀）**：payload：source_proposal_id、source_proposal_revision、source_item_refs、kind、content（去标识后）、deidentified_confirmed（必须为真）、confirmation_token。执行者是人且能读源提案；小Pai 可起草去标识稿作为候选。服务器检查 content 不含来源链接、源提案原件文件名、customer_identities 中的名称，不通过 → VALIDATION_FAILED（identity_not_removed，detail 列出命中项）。与私有原件的原文重叠只在预览中提示，由人判断，不设阈值、不自动拦截。写入：知识行（AI 起草稿 origin=ai_draft、confirmed_by=人）+ PromotionProof。

**category.knowledge.withdraw（T1）**：payload：lineage_id、expected_version、reason。追加 withdraw 行；当前态 withdrawn；证明保留；不阻断在审提案；引用它的草稿提案出 context_hint。

**category.parameter.publish（T1）**：payload：parameter_id（新参数为空）、expected_current_version（新参数为 0）、key、name、value_type、enum_values、unit、direction、standard_condition、method、acceptance_criterion、change_note。新版本 = 当前 + 1；只插入，不改旧版本；引用旧版本的草稿提案出 context_hint。候选由接触过私有资料的运行准备（prepared_by_run_id 指向的运行，判定同 private_context_run）时，预览与确认执行都做与 promote 相同的身份检查（P7-7）：key、name、enum_values、unit、standard_condition、method、acceptance_criterion、change_note 不得含来源链接、该提案原件文件名、customer_identities 中的名称；预览列出命中项，执行时不通过 → VALIDATION_FAILED（identity_not_removed，detail 列出命中项）。

### 3.6 提案其他命令
**proposal.create（T1）**：payload：title、entry_kind、target_kind、baseline_product_id、baseline_definition_revision、brief、customer_identities、source_refs（已上传到本品类的私有原件、快照、知识）、groups{items[], questions[]}、context_refs（继承的品类资料与参数版本）、prepared_by_run_id、candidate_digest、confirmation_token。payload 没有 visibility，一律私有创建（§02.3a）；owner = 请求者，写入 object_audiences；private_source_count 由服务器按来源类型计算，与 entry_kind 无关；AI 起草条目不得为 confirmed。

**proposal.question.create（T1）**：payload：proposal_id、expected_revision、question、owner_id、due_date、related_item_ids、supersedes_item_id（改派）、confirmation_token。问题负责人须能读该提案；有效可见性为 private 时只能是负责人或评审人，不能分派给受众以外的专家（§02.3a 受众规则，§9 Q6），违反 → VALIDATION_FAILED（reason=assignee_not_audience）；专家在 G0 后经 `project_open_items` 接手。

**proposal.share（T1，仅人工）**：payload：proposal_id、expected_revision、visibility（category / audience）、audience_ids、deidentified_confirmed（有私有上下文 Claim 时必须为真）、confirmation_token。只由负责人本人在页面执行；小Pai 只准备材料（打开共享框、说明影响），不预选、不执行（§9 Q9，与附录 A"仅人工"一致）。带 run 的调用 → NAMED_DECISION_REQUIRED（reason=owner_only）。有私有来源时拒绝 → VALIDATION_FAILED（reason=private_sources_present）。**私有上下文 Claim（P8-3）**：预览逐条列出该提案中由接触过私有资料的运行登记、共享后会对新受众可见的 Claim（§2.14），并对其 content 与 quote 做与 promote 相同的身份检查（不得含来源链接、该提案原件文件名、customer_identities 中的名称），列出命中项；执行时不通过 → VALIDATION_FAILED（identity_not_removed，detail 列出命中项）；未勾选确认 → CONFIRMATION_REQUIRED（deidentification_not_confirmed）。命中的 Claim 由负责人用 `evidence.claim.withdraw`（T1）逐条撤回后再共享（P9）；也可经 `ai.run.revert` 撤回整次运行。

**platform.link.create（T1）**：payload：product_id、platform_id | null、new_platform{code, name, description} | null、action、compatibility、platform_version、reason、expected_link_version、confirmation_token。platform_id 与 new_platform 二选一；给 new_platform 时同一事务先建平台再建链接，不新增操作名（§9 Q5）；code 已存在 → VALIDATION_FAILED（reason=platform_code_taken）。小Pai 可出候选，人一次确认。

**evidence.claim.record（T0）**：payload：source{kind: artifact / snapshot, id, version, locator, quote}、nature、vendor_claimed、availability、content、extraction_ref、proposal_id（只作核对，以 Run 绑定的提案为准）。服务器核对来源可读、quote 是该定位正文的逐字子串（否则 VALIDATION_FAILED，reason=quote_not_in_source）；vendor_claimed 只在 nature=extracted 时可为真（payload schema 校验，P7-5）。privacy 由服务器按 §2.14 判定，payload 不含：来源为私有原件，或运行接触过私有资料时，Claim 记入 Run 绑定的提案，可读范围 = 提案受众，来源是公开快照也一样（P7-6）；接触过私有资料却未绑定提案的运行登记 → FORBIDDEN_SCOPE（private_context_run）。私有提案运行中 price_band、jtbd、review_pain_clustering 用本命令登记新观察，记录随提案保持私有（P7-3）。一批抽取行可在一个命令内登记（不设条数上限，只受请求大小约束）。

**evidence.link.create（T0）**：payload：evidence{type, id, version, locator}、target{type, id, version}、relation。证据与目标都须可读；私有证据关联品类知识等共享目标 → VALIDATION_FAILED（reason=private_source_in_shared）；关联提案条目只追加来源，不改条目值，因而不受"不覆盖人工值"限制。

**evidence.claim.withdraw（T1，P9）**：payload：claim_id、expected_version、reason、confirmation_token。用途：单条撤回登记错误或夹带客户身份的 Claim（例如 `proposal.share` 因 `identity_not_removed` 被挡时），不必撤回整次运行。事务内：追加撤回记录（原 Claim 保留，状态为 withdrawn）；该 Claim 的证据关联失效；引用它的提案条目和品类知识在 source_refs 上标记"来源已撤回"，条目值不变（人工值不被覆盖），由负责人决定后续修订。已被签署的 G0 决定（`proposal_decisions.review_digest` 所含）或封存定义消费的 Claim 不能撤回 → UNDO_BLOCKED_BY_DEPENDENCY（reason=consumed_by_decision）。在审提案引用的 Claim 可以撤回，处理与原件撤回相同：评审页提示，批准在 g0.decide 完整重证时得 SOURCE_STALE（reason=claim_withdrawn），退回并重新提交后可批准（§9 Q10）。执行者：私有 Claim 为所在提案负责人，品类可读 Claim 为品类写者；小Pai 只能预填候选（列出命中项与受影响条目），由人一次确认。

**product.definition.item.patch（T0）**：规则同 §3.2；目标定义须是 draft 且 sealed=false。G0 v1 之后先用已有 `product.definition.draft` 起 v2。

### 3.7 事件消费与撤回
| 事件 | M3 内的消费者 |
|---|---|
| category.knowledge_added / _withdrawn、category.parameter_published | 只给实际引用该谱系或参数的草稿提案置 context_hint（精确扇出，§08.11-9） |
| proposal.g0_submitted | 评审人注意项 |
| proposal.g0_decided | 负责人注意项；Temporal signal 唤醒等待中的小Pai 运行 |
| proposal.question_created、project.created | 问题负责人、项目负责人注意项 |
| source.withdrawn（`evidence.source.withdraw`，T2） | 引用该原件的在审提案：评审页提示；批准在 g0.decide 完整重证时被阻断（§3.4、§9 Q10） |
| claim.withdrawn（`evidence.claim.withdraw`，T1，P9） | 引用该 Claim 的提案条目与品类知识的负责人注意项；在审提案同 source.withdrawn |
| claim.recorded、evidence.linked、platform.linked | 只进活动记录，不产生注意项（T0 低打扰，AT-31） |

撤回方式：AI T0 写入（含 Claim 与证据关联）用 `ai.run.revert`（整次运行）；单条 Claim 用 `evidence.claim.withdraw`（T1，P9）；品类知识用 `category.knowledge.withdraw`；参数版本不撤回，只发布新版本；G0 决定撤回、提案撤销本期不做（§9 Q7）。

### 3.8 错误类别用法
| 顶层码 | M3 中的 detail.reason 示例 |
|---|---|
| FORBIDDEN_SCOPE | not_member、reviewer_not_eligible、private_context_run、skill_not_loaded、run_category_mismatch、isolated_subtask_only |
| NOT_FOUND | 对象不存在或无权得知；私有提案对非受众一律 NOT_FOUND |
| VALIDATION_FAILED | reviewer_is_owner、options_insufficient、narrative_missing、unknown_without_disposition、option_not_selected、ai_cannot_confirm、parameter_unit_mismatch、quote_not_in_snapshot、quote_not_in_source、identity_not_removed、private_source_in_shared、private_sources_present、key_taken、platform_code_taken、assignee_not_member、assignee_not_audience |
| VERSION_CONFLICT | base_version_moved、proposal_locked、submission_superseded |
| CONFIRMATION_REQUIRED | human_value_protected、token_missing_or_expired、deidentification_not_confirmed |
| NAMED_DECISION_REQUIRED | owner_only、reviewer_only、ai_cannot_decide |
| QUALIFICATION_REQUIRED | no_t0_qualification |
| SOURCE_UNAVAILABLE / SOURCE_STALE | baseline_unreadable、original_withdrawn、claim_withdrawn（P9） |
| UNDO_BLOCKED_BY_DEPENDENCY | consumed_by_decision（`evidence.claim.withdraw`，P9） |
| 其余（DUPLICATE_INTENT_CONFLICT、CANCELLED_RUN、RATE_LIMITED、INTERNAL_ERROR、EXTERNAL_OUTCOME_UNKNOWN、MISSING_REQUIRED_EVIDENCE） | 按 B2 通用语义 |

## 4. 读模型与工具（工具名单 v0.2）

本节工具名单取代原名单（用户 2026-10-08，确认稿 §8 P5）。技能包只能引用名单内的工具（§5.4）。

共同规则：范围由运行或会话绑定（品类，必要时到提案），参数里的 category_id 只作核对；`category.list` 例外（新建品类会话尚无品类，按请求者在租户内的有效授权过滤）。游标分页，page_size 默认 50、最大 200（只是分页上限），返回 next_cursor 与 as_of 水位；不设"最多 N 条来源"之类业务上限，需要完整集合时翻页读完（§08.11-7）；私有内容只对受众返回，共享读取（知识、竞品、视图）从不包含私有提案内容。

### 4.0 名单总表
| 类别 | 工具 | 档位 / kind |
|---|---|---|
| 读 | category.list、category.read、category.knowledge.list、category.parameters.list、category.competitors.list、platform.read、proposal.read、proposal.items.read、product.baseline.read、evidence.search | READ / read |
| 客户原件与隔离 | evidence.artifact.read（只在隔离子任务中可用）、evidence.extract（隔离子任务入口） | READ |
| 公开研究（M2） | research.search、research.read、research.fanout | READ / research |
| 计算 | calc.market_size、calc.opportunity_score、calc.cost_subtotal、calc.spec_compare、calc.price_band、calc.derivation_diff | READ / compute |
| 写 T0 | research.snapshot.register、category.knowledge.add、proposal.item.patch、product.definition.item.patch、evidence.claim.record、evidence.link.create | T0；无资格时同内容转 T1 候选 |
| 写 T1 | category.create、category.knowledge.promote、category.knowledge.withdraw、category.parameter.publish、proposal.create、proposal.question.create、platform.link.create、evidence.claim.withdraw（P9） | T1；只产出候选，人一次确认 |
| 只准备 | proposal.share、proposal.g0.submit、proposal.g0.decide、category.member.grant、project.create | 只出材料，无执行工具（§4.5） |
| 其他 | skill.load | M2 |

### 4.1 读工具
| 工具 | 输入 | 输出 | 范围与过滤 |
|---|---|---|---|
| category.list（新增） | name_query（名称或键的部分匹配）、status（B1 品类状态，默认全部可见状态）、cursor | id、key、name、purpose、status、owner、请求者权限（读 / 写 / product_manager）、型号数、revision | 只列请求者有有效 Grant 的品类，供新建品类时查重；不可见品类不列出（键冲突仍由 category.create 返回 key_taken） |
| category.read | — | id、key、name、purpose、owner、revision、各 kind 知识数、参数数、型号数 | 品类成员 |
| category.knowledge.list | kind、status（默认 active）、origin、region、include_history | 当前版本：lineage、version、kind、content、origin、status、source_refs | 品类成员 |
| category.parameters.list | parameter_ids、include_history | 当前或全部参数版本 | 品类成员 |
| category.competitors.list | parameter_ids、brand、nature | competitor 条目；指标按 (parameter_id, version, unit, 工况) 分组；价格口径字段 | 品类成员 |
| platform.read（新增） | 单个：platform_id；列表：code、name_query、product_id、category_id；include_history | 平台 id、code、name、description、provenance；关联：product_id、category_id、compatibility（兼容范围）、platform_version、current_version、attached；include_history 时含关联历史版本 | 平台本体：同租户且有任一有效品类授权（§7.2）；关联只返回请求者可见的型号，私有变体对非受众不出现（AT-05） |
| proposal.read | proposal_id | 头信息、有效可见性及原因、状态、revision、条目计数、问题摘要、提交/决定摘要、context_hint | 提案受众 |
| proposal.items.read | proposal_id、kinds（默认全部，含 spec 与 question）、item_ids、question_status、include_history | 条目当前版本与 provenance、是否人工值；**已有待决问题**（question、owner_id、due_date、status、answer、related_item_ids），供 gap_check 去重 | 提案受众 |
| product.baseline.read | product_id、definition_revision（默认最新已发布；无则 G0 v1；再无则最新草稿并标明）、areas（默认全部） | **已发布定义**（定义头、SpecItem 列表、状态与来源）、变体；**BOM**（该定义对应配置的 BOM 版本与行）；**认证**（定义中的认证与销售地区条目、已登记的认证资料引用）；**模具**（已登记的模具/模穴引用与版本）；**平台引用**（当前关联、兼容范围、平台版本）。各区块带来源版本；某区块无对象或无记录时返回空并标 unknown，不补造 | 型号可见者；私有变体只对受众 |
| evidence.search | query、scope（category / proposal）、kinds（snapshot / original / knowledge / claim） | 对象、版本、定位、隐私等级；knowledge 带条目内容（同 category.knowledge.list）；claim 带已登记的 content 与 quote；**original 与 snapshot 都不返回正文片段**，只返回命中定位（原件另带解析状态）与该定位上已登记的 Claim；读原文一律走隔离子任务：原件 `evidence.extract`，网页 `research.fanout`（P7-1、P8-1） | 先按 ACL 过滤再召回（§07.7）；scope=proposal 才含该提案私有原件与私有 Claim（§2.14） |

### 4.2 客户原件、导入文件与隔离抽取
客户原件与导入的评论、退货文件（含客户投诉）都和网页一样是不可信外部内容（P7-4）。按 v1.1 §06.1，读取它们走隔离子任务：子任务不给写工具，只交回结构化结果；带写工具的主循环不读原件原文，只看抽取行（`evidence.search` 对原件和网页快照都只给定位与已登记 Claim，P7-1、P8-1）。

| 工具 | 输入 | 输出 | 范围与规则 |
|---|---|---|---|
| evidence.artifact.read（新增，READ） | artifact_version_id（须在派发时绑定的原件清单内）、locator（起点：页 / 段 / 表格行段 / 单元格）、cursor、page_size | 按定位的内容块[{locator, text 或 cells}]、解析状态（解析失败、OCR 区域带不确定性）、content_hash、next_cursor | **只在 `evidence.extract` 派发的隔离子任务中注册**；主循环调用 → FORBIDDEN_SCOPE（reason=isolated_subtask_only）；分页读完，不设业务条数上限 |
| evidence.extract（新增，隔离子任务入口） | proposal_id（提案范围；与 Run 绑定核对；品类范围为空）、artifact_version_ids（提案范围默认该提案挂载的全部原件；品类范围须显式列出）、row_schema（调用技能声明的行结构，如 rfq_extraction 的需求行、review_pain_clustering 的用户声音行）、focus（可选：参数版本或问题） | 结构化行[{row_id, artifact_version_id, locator, quote（逐字片段）, 行结构字段（parameter_id / version、value / lower / upper、unit、condition_note、modality、exceptions、verification_method、acceptance_criterion 等，对应 §2.7）, status: ok / partial / unreadable, error}]；代码生成的覆盖说明（已读、未读、解析失败的原件与定位范围）；作业 ID | 提案范围：提案受众，只能抽取本提案挂载的原件；品类范围：只能抽取本品类内品类可见的导入文件（如公开评论导出、我方渠道退货原因），客户投诉等私有文件须挂到对应私有提案、在提案范围抽取（P7-4）。子任务只有 `evidence.artifact.read`，无写工具、无研究工具；quote 由代码核对为该定位正文的子串，不通过的行剔除并列入覆盖说明；子任务所用服务商须已登记该数据类别的签约协议（§07.5）。行不落库为事实，主循环经 `evidence.claim.record`、`proposal.item.patch` 写入；同步部分超 3 秒转后台并返回作业 ID |

### 4.3 公开研究（M2 提供）与 M3 的接口
| 工具 | 在 M3 中的用法 | 返回 |
|---|---|---|
| research.search | 主循环可用，只取线索；查询词出站前按服务商协议与 customer_identities 过滤（§06.3、AT-57） | 线索（网址、标题、摘要、服务商） |
| research.read | 只打开本轮搜索结果或用户消息中的网址；读取原始网页只在 fanout 子任务中进行，主循环只看台账与已登记 Claim，`evidence.search` 也不向主循环返回快照正文（§06.3、P8-1） | 正文与快照引用 |
| research.fanout | 主循环入口；按品牌或来源类型拆并行子任务，子任务只有 search 与 read | 台账行：品牌、型号、parameter_id 与版本、值、单位、工况、原文片段、快照与定位、status（ok / partial / unavailable）、错误；覆盖与失败说明由代码生成 |

| M3 消费点 | 接口约定 |
|---|---|
| 参数版本 | 派发子任务时附 `category.parameters.list` 的当前参数版本；台账行按其填 parameter_id 与版本，未映射的写自由键 |
| 台账行 → 品类知识 | `category.knowledge.add` 的 source_refs 引用快照 id + 定位 + 片段；片段不是快照正文子串 → quote_not_in_snapshot |
| 台账行 → 提案 / Claim | `proposal.item.patch` 的 source_refs；`evidence.claim.record`（source.kind=snapshot） |
| 快照登记 | `research.snapshot.register`（T0）；新建品类时先留运行作业库，`category.create` 同事务登记（§9 Q8） |
| 覆盖与失败 | 进入候选的 research{ledger_ref, coverage, failures}，由代码按台账生成，模型不复述 |

### 4.4 计算工具
| 工具 | 输入 | 输出 | 规则 |
|---|---|---|---|
| calc.market_size | segments[{name, 数量区间或人群×渗透率区间, 价格区间, currency, source_refs}] | low/high 区间、按币种分列、假设清单、缺项 | 缺输入返回 unknown，不补零 |
| calc.opportunity_score | criteria[{key, weight, score, rationale, source_refs}]（权重显式传入） | 总分、分项、权重来源、缺项 | 结果只作参考，不是任何关卡条件 |
| calc.cost_subtotal | lines[{label, qty, unit_cost, currency, as_of, source_ref}]、fx[{pair, rate, as_of, source_ref}] | 按币种小计；有汇率才折算；缺价行列出 | Decimal；不同币种无汇率不相加 |
| calc.spec_compare | subjects[{type: proposal / product / competitor, id}]、parameter_ids | 按 (parameter_id, version, unit, 工况) 分组的值表；nature；不可比原因；未知计数 | 只读输入对象的当前可见值 |
| calc.price_band（新增） | price_points[{amount, currency, observed_on, price_type, includes_tax, includes_shipping, channel, region, source_ref}] 或竞品谱系引用（由工具读当前版本价格）；bands[{low, high}]（显式分档）或 quantiles[]（显式分位点）；group_by（默认按全部口径字段）；fx[{pair, rate, as_of, source_ref}]；target_currency | 按口径分组的价格带：每组价格点数、最低/最高、分位值或各档计数、所含价格点；换算值标明所用汇率及其日期；缺口径或不可比的价格点单列 | Decimal；口径不同不合并；有显式汇率才换算，价格日期与汇率日期分别保留；缺值不补 |
| calc.derivation_diff（新增） | baseline{product_id, definition_revision}（默认基线已发布定义）；proposed{proposal_id, revision} 或 {product_id, definition_revision}；areas（specification / bom / certification / tooling，默认全部）；three_way{old_parent, new_parent, child}（可选，父版更新时） | 差异行[{area, item_key 或路径, baseline, proposed, change: added / removed / changed, 不可比原因, source_refs}]；三方模式另列双方都改的冲突项 | 包装 pdos-next 现有派生/三方差异引擎 `domain/products/variants.py`（S0 §6.2 唯一实现），不另写第二套；只读可见对象 |

计算工具返回引擎版本与输入摘要，结果不落库为事实；视图只读这些结果（§05.8）。同步部分 ≤ 3 秒，超出转后台并返回工作 ID。

**计数**：条数、占比、样本量（如 voice 样本量、各分组条数）由 Agent 图的 verify 节点按所引台账行、抽取行或 Claim 用代码回填；模型不自填计数，不另设计算工具。

### 4.5 写工具与只准备工具
| 档位 | 工具 | 说明 |
|---|---|---|
| T0 | research.snapshot.register、category.knowledge.add、proposal.item.patch、product.definition.item.patch、evidence.claim.record、evidence.link.create | 规格见 §3.1、§3.2、§3.5、§3.6；需资格、当前授权与已加载技能 |
| T1 | category.create、category.knowledge.promote、category.knowledge.withdraw、category.parameter.publish、proposal.create、proposal.question.create、platform.link.create（可顺带新建平台）、evidence.claim.withdraw（单条撤回 Claim，P9） | 规格见 §3.5、§3.6；工具调用只产出候选 |
| 只准备 | proposal.share（打开共享框、说明影响，不预选；列出将随共享可见的私有上下文 Claim，P8-3）；proposal.g0.submit（提交前检查结果与提交说明草稿，评审人由负责人在页面选）；proposal.g0.decide（缺口、方案对比、处置表草稿，标出会随决定加入型号与项目受众的处置负责人与项目负责人，P7-2、P8-2）；category.member.grant（授权申请材料）；project.create（在 G0 决定材料中起草项目名与负责人建议） | 没有执行工具；带 run 的执行一律 NAMED_DECISION_REQUIRED |
| 其他 | skill.load | M2；加载记录入回执 |

## 5. 小Pai 立项对话

### 5.1 入口与范围
| 入口 | 会话范围 | 预载技能 | 结果 |
|---|---|---|---|
| 全局"新建品类" | 个人，尚无品类 | category_framing | 先用 category.list 查重；品类候选 → category.create |
| 品类页"立项提案" | 该品类 | proposal_drafting | 提案候选 → proposal.create；或在辅助弹窗找已有提案 |
| 提案页右侧 | 该提案 | proposal_drafting、gap_check；有客户原件时 rfq_extraction | 条目编辑、问题候选、G0 提交准备（只准备） |
| 评审人打开 G0 | 该提案 | gap_check、option_comparison | 只准备决定材料（T2） |

个人对话默认私人。同名对象可能导致写错时，只问影响该动作的最小选择，其他只读工作继续。

### 5.2 澄清（Grill me）
- 只问会改变方向的问题，边问边研究。例："充气泵"先分汽车、自行车还是桨板，不混成一个品类。未明确的地区、价格等写成显式假设（§2.6 assumption 结构），不强迫先填表。
- 输出 schema：`Clarify{questions[1..3]}`，每条：id、question、why（会改变什么）、options[{value, label}]、recommended{value, reason}、allow_free_text、depends_on。每次最多 3 条由 schema 约束（v1.1 规定）。
- 弹窗回答；推荐答案带"推荐"标记但不预选，须用户主动选。答案与后续研究留在同一会话。
- 会话恢复时，未答问题以内嵌卡片显示，不自动重开弹窗；只有本次新到的 interrupt 且面板可见时才弹窗；面板隐藏时只显示角标。

### 5.3 候选结构
**CategoryCandidate**：key（建议值）、name、purpose、boundary{includes, excludes, split_from}、segments[]、scenarios、regions、research_questions、parameter_skeleton[]（key、name、value_type、unit、direction、standard_condition、method、acceptance_criterion，未知为空）、knowledge_drafts[]（kind、content、source_refs）、research{ledger_ref, coverage, failures}（覆盖与失败由代码根据台账生成）、assumptions[]（§2.6 assumption 结构，related 指候选中的边界、地区或参数 key；保存时作为 kind=research_question 的知识草稿，§2.2）。

**ProposalCandidate**：title、entry_kind、target_kind、基线引用、sections[]、commercial_target、spec_items[]（引用当前参数版本；状态只能 ai_draft / expert_pending / unknown）、options[]（2–3 个，可含"沿用现款"或"不做"）、differences[]（派生）、questions[]（问题、建议负责人、建议期限）、risks[]、decision_notes[]、context_refs、assumptions[]（proposal.create 时写成 assumption 条目）。客户需求入口每条需求来自 `evidence.extract` 的抽取行，带原件定位与逐字片段；规格类需求的措辞、例外、判据写入 SpecItem 的 modality、exceptions、acceptance_criterion，其他类需求保留在 Claim content。

### 5.4 技能包 ↔ 工具（按名单 v0.2）
按 `docs/design/skills-draft/` 各技能 front matter 的 allowed_operations（0.2.0-draft，10/08 同步）。

| 技能包 | 读 / 研究 / 计算 | 写（档位） | 产出 |
|---|---|---|---|
| category_framing | category.list（查重）、category.read、category.knowledge.list、category.parameters.list、research.search、skill.load | category.create（T1） | Grill me；CategoryCandidate（含显式假设） |
| public_research | category.read、category.knowledge.list、category.parameters.list、category.competitors.list、evidence.search、research.search / fanout（research.read 只在子任务内）、skill.load | research.snapshot.register、category.knowledge.add、evidence.claim.record（T0） | 台账、快照、知识草稿；提案上下文中的发现登记为 Claim（私有运行中只给提案受众，P7-6） |
| jtbd | category.read、category.knowledge.list、category.parameters.list、proposal.items.read、evidence.search、research.fanout、skill.load | category.knowledge.add、evidence.claim.record、proposal.item.patch（T0） | segment 知识草稿、提案叙述与 assumption 条目；私有运行中的新观察登记为私有 Claim（P7-3） |
| competitor_comparison | category.competitors.list、category.parameters.list、proposal.items.read、product.baseline.read、evidence.search、research.fanout、calc.spec_compare、skill.load | category.knowledge.add、evidence.claim.record、proposal.item.patch（T0）；category.parameter.publish（T1，私有运行准备的候选过身份检查，P7-7） | 竞品知识或 Claim（私有运行中只给提案受众，P7-6）、worth_it 竞品结论（对标表是视图）、通用新参数草稿 |
| price_band | category.read、category.competitors.list、proposal.items.read、product.baseline.read、evidence.search、research.fanout、calc.price_band、skill.load | category.knowledge.add、evidence.claim.record、proposal.item.patch（T0） | 按口径分组的价格带；私有运行中的新价格观察登记为私有 Claim（P7-3） |
| review_pain_clustering | evidence.extract（导入的评论、退货文件；子任务内只有 evidence.artifact.read，P7-4）、evidence.search、category.knowledge.list、category.competitors.list、category.parameters.list、research.fanout、skill.load | category.knowledge.add、evidence.claim.record、proposal.item.patch（T0） | voice 条目（样本量由 verify 回填）；私有运行中的归类依据登记为私有 Claim（P7-3） |
| proposal_drafting | category.read、category.knowledge.list、category.parameters.list、category.competitors.list、proposal.read / items.read、product.baseline.read、platform.read、evidence.search、calc.cost_subtotal、skill.load | proposal.create（T1）、proposal.item.patch、evidence.link.create（T0）、proposal.question.create（T1）、evidence.claim.withdraw（T1，P9） | 提案候选、条目编辑（含 assumption 条目）、Claim 关联 |
| rfq_extraction | evidence.extract（子任务内只有 evidence.artifact.read）、evidence.search（提案范围）、proposal.read / items.read、category.read、category.parameters.list、product.baseline.read、calc.spec_compare | evidence.claim.record、evidence.link.create、proposal.item.patch（T0）；proposal.question.create、category.parameter.publish（过身份检查，P7-7）、category.knowledge.promote（T1） | 逐条需求（含措辞、例外、判据）带原件定位与逐字片段；通用新参数草稿 |
| option_comparison | proposal.read / items.read、category.competitors.list、category.parameters.list、product.baseline.read、platform.read、evidence.search、calc.cost_subtotal、calc.spec_compare、skill.load | proposal.item.patch（T0） | option 与 risk 条目 |
| opportunity_scoring | category.read、category.knowledge.list、category.competitors.list、proposal.items.read、evidence.search、research.fanout、calc.market_size、calc.opportunity_score、skill.load | proposal.item.patch（T0） | worth_it 段落引用计算结果 |
| derivative_diff | product.baseline.read、platform.read、category.parameters.list、proposal.read / items.read、evidence.search、calc.derivation_diff、calc.cost_subtotal | proposal.item.patch（T0）；proposal.question.create、platform.link.create（T1） | difference 条目（规格 / BOM / 认证 / 模具 / 成本 / 其他，direct 或 inferred） |
| gap_check | proposal.read、proposal.items.read（含已有待决问题，用于去重）、category.read、category.parameters.list、product.baseline.read、platform.read、evidence.search、calc.spec_compare | proposal.item.patch、product.definition.item.patch、evidence.link.create（T0）；proposal.question.create（T1）；proposal.g0.submit / g0.decide 只准备 | 缺项与问题候选；新证据关联；G0 准备材料 |

T1 写工具调用只产出候选；只准备工具只出材料（§4.5）。未加载对应技能时，服务器拒绝其写工具（AT-58）。`evidence.artifact.read` 不进任何技能包的主循环白名单，只在 `evidence.extract` 派发的子任务中注册；`research.read` 只在 fanout 子任务中使用。

### 5.5 一次确认、保存与过程面板
- 候选出现后，对话进入等待（Temporal 持有，不占模型）。用户点"保存"→ 服务器 preview 显示将写入的内容、可选组、影响与未知项 → 确认一次 → 执行 → Outbox 发 signal 释放等待 → 跳转到对象页。
- 品类保存：确认框须勾选"共享内容已去除客户身份"。提案保存：确认框显示"私有（默认）"，不提供共享选项。
- 试点租户且有资格时，后续条目编辑、知识草稿和证据登记按 T0 直接写入，活动记录静默更新；无资格时同一内容作为 T1 候选。M3 只做资格检查（非试点租户拒绝、技能包或模型版本变更后失效），资格登记界面留 M4（§9 Q3）。创建品类和提案始终是 T1（附录 A）。
- 客户原件与导入的评论、退货文件：主循环调用 `evidence.extract`（P7-4），过程面板显示读取的原件、定位范围与代码生成的覆盖说明；小Pai 回复只引用抽取行、已登记 Claim 与其逐字片段（主循环看不到原件全文，`evidence.search` 对原件和网页快照只给定位，P7-1、P8-1）；原件本身在提案页的证据视图中查看。
- 标准品匹配：客户需求被现有型号完全满足时，小Pai 给出匹配结果并说明回到 CRM，不建提案、不建项目（AT-02）。
- 过程面板（M2 事件）：公开的处理思路摘要、实际搜索词与服务商、读取的来源与状态、代码生成的覆盖与失败、耗时。生成中展开，完成后收起，随回复保存；不显示模型内部推理原文。
- 模型失能时：人工编辑提案、提交、G0 全部可用；小Pai 显示失能，不用旧缓存冒充新结果（AT-45）。

## 6. 页面与 API

### 6.1 页面
| 页面 | 区块 | 主动作 | 不放 |
|---|---|---|---|
| 品类列表 | 可见品类、负责人、型号数 | 新建品类（打开个人小Pai） | 空驾驶舱 |
| 品类页 | 品类边界；共享知识（用户与场景、竞品库、用户声音、法规认证）；规格字典（当前版与历史）；型号列表（目标价、导入状态） | "立项提案"（打开品类小Pai）；补知识、发布参数版本、撤回知识 | 提案列表与新建表单（在小Pai 辅助弹窗查找）；品类矩阵（第三批） |
| 提案页 | 主位：叙述与关键规格；同一文档的视图：证据、规格对标、定位图、功能配置、用户声音、方案对比、待决问题、风险、决策记录、定义成熟度；状态与可见性条；右侧小Pai | 编辑、让小Pai 起草或查漏、新增问题、共享（负责人）、"提交 G0 立项评审"（唯一关卡） | 其他阶段关卡 |
| G0 评审（提案页内，仅评审人） | 固定副本、提交后品类变化提示、原件撤回提示（批准被阻断时写明原因，§9 Q10）、未知项处置表、方案选择 | 批准 / 退回 / 不立项（具名） | AI 代决按钮 |
| 型号页 | 定义版本（v1 链到来源提案与 G0 决定）、变体、平台关联、项目 | 继续定义（起 v2）、发起派生提案、关联平台（平台不存在时可在同一确认框新建，§9 Q5） | — |

前端遵循 UI 基线（shadcn/ui、Tailwind v4、Geist、双主题、Phosphor）。主动作只显示当前真实可执行的；不可执行时写具体原因（无权限、版本冲突、缺方案理由等）。

### 6.2 路由
| 方法与路径 | 用途 |
|---|---|
| GET `/v1/categories`（name_query、status）；POST `/v1/categories/preview`、`/v1/categories` | 列表与 category.list；category.create（扩展 B1 路由） |
| GET `/v1/categories/{cid}/platforms`、`/platforms/{platform_id}` | platform.read；关联只含请求者可见型号 |
| GET `/v1/categories/{cid}`、`/knowledge`、`/parameters`、`/competitors` | 品类页 |
| GET `/v1/categories/{cid}/proposals` | 辅助弹窗查找，只列可读提案 |
| GET `/v1/categories/{cid}/proposals/{pid}`、`/items`、`/questions`、`/submissions/{sid}`、`/decision` | 提案页与 G0 评审 |
| GET `/v1/categories/{cid}/products/{product_id}/definitions/{rev}`、`/platform-links` | 型号页（B3 已有路由补来源字段） |
| GET `/v1/categories/{cid}/views/{positioning / spec-benchmark / feature-config / definition-maturity}` | 立项视图第一批；参数 proposal_id、parameter_ids |
| POST `/v1/categories/{cid}/commands/preview`、`/commands` | 所有命令 |
| POST `/v1/categories/{cid}/originals` | 品类级上传（立项前客户原件与导入的评论、退货文件；默认私有，可见性按 B3 原件规则） |
| 会话、答复、SSE | 沿用 M2 路由 |

BFF：Next.js 同源透传；不写第二套业务校验；命令统一走"预览 → 确认"辅助函数；SSE 透传；错误按顶层码处理。每条路由映射注册命令或读模型，新增路由同步契约导出与 BFF 覆盖检查。

### 6.3 立项视图第一批
共同规则（§05.8）：实测、宣传、推断、未知分开显示（Claim 按 §2.14 映射：observed = 实测，extracted 且 vendor_claimed = 宣传，inferred = 推断，availability=unknown = 未知）；未知不画点，只写数量与原因；工况、单位、币种、日期不同就分组或提示，不硬比；每个点能钻到来源（快照或原件定位）；显示样本量，样本少只标注；我方现款与目标用强调色，竞品灰色；视图只读计算工具与证据，不另存为事实。私有提案的视图只给受众；共享视图不含私有提案。

| 视图 | 数据来源 | 绘制 |
|---|---|---|
| 定位图 | x = 价格（提案 commercial_target、型号目标价、竞品价格）；y = 所选参数版本的值；calc.spec_compare | 按（参数版本、单位、工况）与（币种、价格口径、日期）分组，不同组分面；实测实心、宣传空心、推断虚线 |
| 规格对标 | 提案 spec_items、基线型号定义、竞品指标；calc.spec_compare | 行 = 参数版本；列 = 目标、基线、竞品；不可比单元格写原因；未映射自由键单列 |
| 功能配置 | value_type 为 boolean / enum 的参数版本；提案 features_in_out；竞品 features | 行 = 参数；有 / 无 / 未知；未映射到字典的功能单列，不做文本硬匹配 |
| 定义成熟度 | 提案条目与问题的当前态 | 按 item_status、availability 计数；问题负责人与期限；方案数；关键规格条数（10–20 只提示）；提交前检查清单（§3.3 规则的结果）；**冻结前会被阻断的内容**：逐条列出 unknown、expert_pending、conflicted 及缺单位或工况的规格条目（只列出；M3 不执行冻结，具体冻结规则随项目内定义切片，§9 Q4）；不出综合分 |

## 7. 迁移

### 7.1 号段
M3 在 B8 之后开始，此时只有一个 head。建议从 `s0_0900` 起单调编号，预留 `s0_0900`–`s0_0999`；若届时实际 head 已越过，按实际 head + 1（AGENTS.md 不可协商项 3）。不把技能包、模型或工具版本写进约束或触发器。

| 修订 | 内容 |
|---|---|
| s0_0900_category_key、s0_0910_parameters、s0_0920_knowledge | categories.key 与 created_by_run_id（(tenant, key) 唯一）；parameter_versions 与 parameter_current；category_knowledge_entries 与 _current；只追加触发器 |
| s0_0930_snapshot_fields | 核对或补 public_web_snapshots 字段（M2 已齐则不建） |
| s0_0935_evidence_claims | 核对或补 Claim 与证据关联字段（§2.14；B3 已齐则不建） |
| s0_0940_proposals、s0_0950_proposal_items | proposals、proposal_sources、proposal_revisions；proposal_items、proposal_item_versions、proposal_spec_items、proposal_questions |
| s0_0960_g0、s0_0970_promotion | proposal_submissions、proposal_decisions（独立性 CHECK 与复合外键）；promotion_proofs；只追加触发器 |
| s0_0980_platforms | platforms、platform_product_links、platform_link_current |
| s0_0990_product_definition_project | products 目标字段、product_target_segments、definition_revisions 来源字段与 sealed 触发器、definition_specs 的 SpecItem 列、projects 触发物字段、project_open_items |
| s0_0995_project_g0_required | projects.g0_decision_id NOT NULL（P2 收紧；无真实数据，测试库按新链重建） |
| s0_0998_rls | M3 新表 RLS 策略 |

Grant 的 `product_manager` 能力（§9 Q1）属 B1 表，由主会话转告 Codex 在 S0 B1 迁移中加入，不占 M3 号段。

### 7.2 RLS 策略
B1 提供品类读、写判定函数（名称以 B1 为准，下称 category_reader / category_writer）。M3 增加 `proposal_reader(tenant, category, proposal_id)`：是品类读者，且满足其一：有效可见性 = category；当前主体是负责人或该提案任一次提交的评审人；有效可见性 = audience 且在 object_audiences 中。

| 表 | SELECT | INSERT / UPDATE |
|---|---|---|
| category_knowledge_*、parameter_*、public_web_snapshots | category_reader | category_writer（只追加表无 UPDATE） |
| proposals | proposal_reader(id) | category_writer；INSERT 时 owner_id = 当前主体 |
| proposal_* 子表、submissions、decisions | proposal_reader(proposal_id) | category_writer 且 proposal_reader |
| promotion_proofs | proposal_reader(source_proposal_id) | 同上 |
| Claim、证据关联（M3 补的部分） | 私有（来源为私有原件，或登记运行接触过私有资料，§2.14、P7-6）：proposal_reader(proposal_id)；其余：category_reader | category_writer（私有另需 proposal_reader） |
| platforms | 同租户且有任一有效品类授权 | 同左且可写 |
| platform_product_links、platform_link_current、product_target_segments | category_reader 且型号可见（B1/B3 型号受众） | category_writer |
| project_open_items | 项目可见（B3 规则） | category_writer |
| definition / projects 补列 | 沿用 B3 | 沿用 B3 |

应用连接不是表所有者、无 BYPASSRLS；AI 数据库角色对上述表零 DML。负向测试以应用角色直接查库验证（同 B1 做法）。

## 8. 验收

测试一律用显式 `TEST_DATABASE_URL` 指向独立临时库；"PG"指真实隔离 PostgreSQL 事务测试，"演示"指 §8.4 的合成案例。

### 8.1 路径 A"必须证明"
| 必须证明 | 测试与演示 |
|---|---|
| 未建项目也可研究；标准品匹配不建虚拟项目；客户未知参数不补造 | PG：建品类、加知识、建提案、提交，projects 无新增。演示 (b) 标准品匹配分支：无提案、无项目。RFQ 缺单位的需求落为 unknown 条目，unit 为 NULL |
| 品类为范围根；私有提案只有负责人与评审人可见；客户私有资料不进共享知识、对标与矩阵 | PG（应用角色直连）：非成员读写品类内各表被拒；私有提案对同品类非受众为 NOT_FOUND，RLS 也查不到；客户原件内容不出现在 knowledge.list、competitors.list、evidence.search(scope=category) 与视图中；主循环调用 evidence.artifact.read 被拒（isolated_subtask_only），主循环上下文只含抽取行；evidence.search(kinds=original / snapshot) 只返回定位与已登记 Claim、不含正文（P7-1、P8-1）；私有原件来源的 Claim 关联品类知识被拒；私有提案运行登记的快照来源 Claim 对同品类非受众不可见（P7-6） |
| 提案条目引用参数版本；不同工况或单位不同口径 | PG：unit 不一致被拒；spec_compare 把 v1/v2、不同单位、有 condition_note 的值分组并给不可比原因 |
| 一次确认（或试点 T0）产生真实记录与来源；AI 草稿署名、可按运行撤回、不覆盖人工值 | PG：category.create / proposal.create 的回执与 provenance（origin=ai_draft、writer=小Pai、confirmed_by=人）；有资格时 item.patch 直写成功且不新增注意项；小Pai 直写人工值得 CONFIRMATION_REQUIRED；整次运行撤回见 AT-55 |
| G0 评审人不能是负责人；批准后生成型号定义 v1 和项目 | PG：选本人为评审人被领域拒绝；只有 can_write、无 `product_manager` 能力的评审人被拒（reviewer_not_eligible）；绕过领域直接 INSERT 被 CHECK 与外键拒绝；批准后型号、定义 v1（sealed）、项目、项目待办同事务存在；故障注入时全部回滚；`project.create` 已无独立入口 |
| 引用片段可核；未签约服务商不收客户资料 | 立项对话中复跑 M2 用例：台账片段全部是快照子串；evidence.extract 行的 quote 全部是原件该定位的子串，篡改片段的行被剔除并列入覆盖说明；未登记服务商时含客户原件的模型调用（含抽取子任务）被拒并记回执；查询词含 customer_identities 时被拦截或改写 |
| 交互命令 p95 秒级 | §8.3 |

### 8.2 附录 B 场景
| 场景 | 测试与演示 |
|---|---|
| AT-01 无项目品类研究 | 同 §8.1 第 1 行；知识、证据、提案都有来源 |
| AT-02 标准品匹配不建虚假研发 | 同 §8.1 第 1 行标准品分支 |
| AT-05 跨客户平台复用 | 同品类两个客户提案 A、B：B 的负责人及其小Pai 会话读不到 A 的原件、条目、customer_identities；A 派生的私有变体关联平台后，非受众在平台关联与 platform.read 中看不到该变体；platform.link.create 带 new_platform 时平台与链接同事务建立，故障注入时都不存在 |
| AT-06 规格缺单位或条件 | unknown 条目可见；带未知提交成功；批准要求逐条处置；第三句按 §9 Q4：定义成熟度视图逐条列出冻结前会被阻断的条目 |
| AT-49 品类范围根 | 同 §8.1 第 2 行 |
| AT-50 去标识沉淀 | promote 正反例：含客户名或原件文件名被拒；共享知识行无回链；PromotionProof 只有源提案读者可读；私有提案运行准备的 parameter.publish 候选含客户名，预览列出命中、执行被拒（identity_not_removed，P7-7）；proposal.share 预览列出私有上下文运行登记的 Claim，其中含客户名时共享被拒（identity_not_removed），未勾选确认时 CONFIRMATION_REQUIRED（deidentification_not_confirmed），通过并确认后这些 Claim 对新受众可见（P8-3）；负责人用 evidence.claim.withdraw 撤回命中的 Claim 后共享成功，被撤回的 Claim 对新受众不可见、引用条目标记来源已撤回且值不变；被已签署 G0 决定消费的 Claim 撤回被拒（UNDO_BLOCKED_BY_DEPENDENCY），在审提案引用的 Claim 撤回后批准得 SOURCE_STALE（claim_withdrawn）（P9） |
| AT-51 规格字典版本 | 发布 v2 后 v1 不变；旧条目仍指 v1 并出 context_hint；人工改引用后进入新分组 |
| AT-52 G0 独立性与结果 | 同 §8.1 第 5 行；待决问题转为 project_open_items，负责人与期限保留，任务为 assigned；私有提案的问题分派给受众外的人被拒（assignee_not_audience，§9 Q6）；G0 处置分派给受众外的品类成员、项目负责人指定为受众外的品类成员，批准后二者同事务加入型号与项目受众、能读到自己的 project_open_items 与项目，dispositions 记 audience_added、决定记 project_owner_audience_added，预览与回执列出这些人，故障注入时一并回滚（P7-2、P8-2）；评审期间撤回提案引用的原件，批准得 SOURCE_STALE，退回并重新提交后可批准，品类资料变化仍不阻断（§9 Q10）；availability=unknown 或 conflicted 的 ai_draft 规格未处置时批准被拒（unknown_without_disposition，P11），not_applicable 不要求处置 |
| AT-53 品类资料变化与在审提案 | 提交后发布参数新版本、撤回被引用的知识；批准仍成功；决定的 context_refs 是提交时版本；评审页显示变化提示 |
| AT-54 方案对比 | 1 个方案且无理由时提交被拒；补理由后成功 |
| AT-55 AI 草稿撤回 | 一次运行写 5 条，人改其中 2 条；整次撤回后 2 条人工值保留、3 条恢复，回执列明；所有 AI 写入 origin=ai_draft |
| AT-56 研究引用可核 | M2 用例 + M3：knowledge.add 的片段不是快照子串时被拒；竞品价格点可钻到快照 |
| AT-57 出站与服务商协议 | M2 用例 + M3：客户提案上下文的数据类别标记生效，查询词按 customer_identities 过滤 |
| AT-58 技能包渐进加载 | 未加载 proposal_drafting 时 item.patch 被拒（FORBIDDEN_SCOPE，skill_not_loaded）；加载记录入回执；修改技能文件不产生迁移 |
| AT-59 MCP 授权 | M2 证明；M3 不新增 MCP 工具，只核对注册表中没有未授权的 MCP 写工具 |
| AT-60 用户取消 | 立项研究中取消：预算名额释放，运行取消终态，候选不保存 |
| AT-61 对账出口 | 候选确认提交后、signal 前杀 worker：按回执补记完成，对话恢复到已保存状态，不重复创建 |
| AT-62 性能与幂等重放 | §8.3；proposal.create、g0.decide 在确认过期后同键同载荷重放，返回原回执 |
| AT-63 试点资格 | M3 只做资格检查（§9 Q3）：夹具资格下，非试点租户 T0 被拒（QUALIFICATION_REQUIRED）；技能包或模型版本变化后资格失效；资格登记界面留 M4 |

共用保障在 M3 新命令上复跑：AT-31（T0 低打扰）、AT-32（category.create 取消勾选参数组，只写品类与知识）、AT-33（确认期间提案被他人改，只显示受影响条目差异）、AT-35（人工值）、AT-36（伪造"评审已批准"文字不能让小Pai 执行 g0.decide；客户原件及导入的评论、退货文件中的此类文字经 evidence.extract 只作为数据行）、AT-37（私有提案内容不进他人检索与记忆）、AT-38（运行中撤销品类授权，下一条命令被拒）、AT-39（伪造 category_id / tenant 被拒）、AT-40（同键不同载荷冲突）、AT-41（取消与 item.patch 并发）、AT-44（Worker 重启）、AT-45（模型失能）、AT-48（合成通过不宣称真实资格）。

新增工具（名单 v0.2）的单测：category.list 不列不可见品类；proposal.items.read 返回已有待决问题，gap_check 不重复建问题；product.baseline.read 无模具或认证记录时返回空并标 unknown；calc.price_band 口径不同不合并、无汇率不换算；calc.derivation_diff 与 `variants.py` 直接调用结果一致；计数字段由 verify 回填，模型自填值不被采用；evidence.extract 品类范围只抽本品类品类可见的导入文件（P7-4）；vendor_claimed 只随 nature=extracted 出现（P7-5）。

### 8.3 性能（决策 P3）
| 类别 | M3 路径 | p95 目标 |
|---|---|---|
| 读取 | 品类页、提案页、条目读取、读工具、视图（不含后台计算） | ≤ 1 秒 |
| 保存草稿 | 人工 proposal.item.patch、category.knowledge.add、T0 直写 | ≤ 1 秒 |
| 预览、T1 确认、提交 | 全部 T1 命令；g0.decide 的预览与执行 | ≤ 2 秒 |
| 重计算同步部分 | calc.*、视图计算 | ≤ 3 秒；超出转后台，立即返回工作 ID |
| 后台工作 | research.fanout、候选生成 | 报告首次回执时间与总耗时 |

每条路径至少 30 次单请求样本，记录 p50/p95、SQL 次数、失败率；快速失败不算提速。标准本地夹具结果不代表生产容量。

### 8.4 演示案例（合成或自有资料）
| 案例 | 流程 |
|---|---|
| (a) 自主新品 | 新建品类 `auto-tire-inflator`（Grill me 区分汽车/自行车/桨板）→ 公开研究 → 保存品类 → 自主新品提案 → 编辑 → G0 → 项目 |
| (b) 客户需求 | 在 `bicycle-pump` 上传合成 RFQ（私有）→ 抽取需求 → 标准品匹配分支 / 新变体提案 → 去标识沉淀一条知识 → G0 |
| (c) 派生迭代 | 以种子型号为基线 → 派生差异 → G0 生成新变体与项目 |

记录操作次数、主动时间、AI 草稿保留率（执行计划 M3 退出判据）。合成通过不宣称真实模型资格（AT-48）。

## 9. 已定问题（用户 2026-10-08）

原待定问题 Q1–Q10 全部按推荐采纳（确认稿 §8 P6），已落入正文；工具名单 v0.2 见 §4（确认稿 §8 P5）。合同与技能包的 7 项细则（确认稿 §8 P7，正文记作 P7-1 至 P7-7）与收尾三项（确认稿 §8 P8，记作 P8-1 至 P8-3）也已落入正文，落实位置见 §10 标"已解决（P7）""已解决（P8）"的行。新增 `evidence.claim.withdraw`（确认稿 §8 P9）见 §10 标"已解决（P9）"的行。G0 批准前值未知的规格也要处置（确认稿 §8 P11）见 §3.4。

| # | 问题 | 结论 | 正文落实 |
|---|---|---|---|
| Q1 | G0 评审人的"产品管理权限"怎么表示 | 评审人须有 Grant 上的 `product_manager` 能力，仅 can_write 不够；经 `category.member.grant`（T2）授予。**需改 S0 B1 的 Grant 表，由主会话转告 Codex** | §1.2、§3.3、§3.4、§7.1、§8.1 |
| Q2 | 待决问题转任务/风险放哪 | 新表 `project_open_items`，G0 批准时同事务生成，带负责人和期限 | §2.13、§3.4、AT-52 |
| Q3 | AT-63 归 M3 还是 M4 | M3 只做资格检查（非试点租户拒绝、技能包或模型版本变更后失效），用夹具资格验证；资格登记界面留 M4 | §1.3、§1.4、§5.5、AT-63 |
| Q4 | AT-06 第三句在 M3 怎么验 | M3 不做规格冻结；定义成熟度视图列出冻结前会被阻断的内容 | §1.4、§6.3、AT-06 |
| Q5 | 平台怎么建 | `platform.link.create` 可在平台不存在时顺带新建，不新增操作名 | §2.11、§3.6、§4.5、AT-05 |
| Q6 | 私有客户提案的待决问题能否分派给受众外专家 | 不能；只能是负责人或评审人，专家在 G0 后经 `project_open_items` 接手 | §1.4、§3.6、AT-52 |
| Q7 | G0 决定撤回、提案撤销 | 本期不做 | §1.4、§3.7 |
| Q8 | 新建品类时研究快照挂哪 | 先存运行作业库，`category.create` 在同一事务里登记为品类快照；M2 已有同等方案时以 M2 为准 | §2.4、§3.5、§4.3 |
| Q9 | `proposal.share` 给不给小Pai 执行 | 只给小Pai 准备材料，由负责人在页面执行（与附录 A"仅人工"一致） | §0、§3.1、§3.6、§4.5 |
| Q10 | 评审期间提案自身引用的原件被撤回，批准是否阻断 | 阻断批准（SOURCE_STALE），退回后重提；品类资料变化仍不阻断（AT-53） | §3.4、§3.7、§6.1、AT-52 |

## 10. 核对发现

| 发现 | 状态 | 说明 |
|---|---|---|
| `proposal.share` 工具档位：并行约定列为 T1 写工具，附录 A 写"仅人工" | 已解决 | §9 Q9 |
| AT-63 归属 | 已解决 | §9 Q3 |
| AT-06 冻结阻断 | 已解决 | §9 Q4 |
| 提案撤销与 G0 撤回：v1.1 有状态、附录 A 无操作 | 已解决 | §9 Q7，本期不做 |
| 平台无创建操作 | 已解决 | §9 Q5 |
| G0 待决问题无处落（`project_tasks` 必须挂计划） | 已解决 | §9 Q2 |
| 评审人资格表示 | 已解决，待实施 | §9 Q1；B1 Grant 表未加能力前，G0 提交的资格检查无法通过 |
| §05.4"试点草稿类写入可按 T0"与附录 A 中 category.create、proposal.create 为 T1 | 已解决 | 按附录 A，创建始终 T1 |
| 四处公共缺口：回执去重键、确认主体、原件 product_id 非空、整次运行撤回 | 未解决 | 10/08 代码现状，交主会话核对（§1.2） |
| B1 `create_category` 给负责人的授权写死 30 天有效期；v1.1 R9 只保留 T1 确认有效期 | 未解决 | 授权有效期应来自具名决定或明确政策；不在 M3 范围，交主会话 |
| `evidence.search` 在主循环返回原件（及快照）正文片段，与 §06.1 及名单 v0.2 的隔离理由冲突 | 已解决（P7） | P7-1：原件不返回正文片段，主循环只拿定位与已登记 Claim，读原文走 evidence.extract（§4.1、§4.2、§5.5、§8.1）；快照片段见下一行 |
| `evidence.search` 对 kinds=snapshot 仍返回快照正文片段（P7-1 只定了原件） | 已解决（P8） | P8-1：网页快照同样只返回定位与已登记 Claim，读网页原文一律走 research.fanout 子任务（§4.1、§4.2、§4.3、§5.5、§8.1；技能 README 与各技能 evidence.search 说明） |
| ToolSpec.tier 枚举（READ / T0 / T1 / T2-prepare-only）表示不了 T1"仅人工"操作的只准备工具（proposal.share、proposal.g0.submit） | 未解决 | 交 M2 定表示方式 |
| G0 处置负责人只要求是品类成员；私有提案生成的型号受众只有负责人与评审人，受众外的处置负责人可能看不到自己的 `project_open_items`（取决于 B3 项目可见规则） | 已解决（P7） | P7-2：同一决定把受众外的处置负责人加入型号与项目受众，dispositions 记 audience_added（§2.9、§2.13、§3.4、§4.5、AT-52） |
| G0 指定的项目负责人不是提案负责人且不在私有提案受众内时，同样看不到型号（P7-2 只定了处置负责人） | 已解决（P8） | P8-2：同一决定把其加入型号与项目受众，决定记 project_owner_audience_added，预览与回执列出（§2.9、§2.13、§3.4、§4.5、AT-52） |
| 提案共享后，私有上下文运行登记的 Claim 随提案受众变为可见（P7-6 的推论） | 已解决（P8） | P8-3：proposal.share 预览列出这些 Claim 并做 identity_not_removed 检查，负责人确认后才共享（§2.14、§3.1、§3.6、§4.5、AT-50；技能 README §6） |
| 共享被私有上下文 Claim 的身份命中挡住时，只能用 `ai.run.revert` 整次撤回所在运行（会一并撤回该运行写的、未经人改过的条目），没有单条 Claim 撤回操作 | 未解决 | 新增单条撤回属新增操作；待用户定是否需要 |
| 技能包草稿与本合同不一致（条目种类与 op、price_band 代算价格、rfq_extraction 未用 evidence.extract、未用 category.list / platform.read / calc.derivation_diff、§5.4 白名单差异、示例参数为占位） | 已解决（10/08 收尾） | 草稿已改用 §2.6 条目种类与 upsert / remove 及名单 v0.2 工具；§5.4 按各技能 allowed_operations 同步（多出的 category.parameter.publish、evidence.claim.record、platform.read、evidence.link.create 均为名单 v0.2 内工具，未与 v1.1 或本合同规则冲突；derivative_diff 去掉 calc.spec_compare）；补 SpecItem 的 modality / exceptions / acceptance_criterion（§2.7）、assumption 条目与品类假设的保存位置（§2.6、§2.2、§5.3）、difference 的 item_ref / change / cost / other / propagation（§2.6）；技能示例改用种子的 `parameter_id@version` 并注明品类 |
| 技能草稿的变通写法，合同未采纳 | 不采纳（理由） | ① gap_check 的"加标记" op：已由 evidence.link.create（只追加来源）+ AI 条目 upsert availability / item_status + 待决问题表达，新增 op 属扩范围；② 竞品行、用户声音条目：v1.1 §05.3 定为提案视图，数据在品类知识或 Claim，结论写 worth_it；③ option 的路线（派生 / 平台复用）字段：v1.1 只要求成本与周期，路线写 summary；④ difference 状态字段：待专家项以待决问题（related_item_ids 指向该条目）表达，v1.1 无此要求；⑤ worth_it 子段落：条目级 base_version 已防静默覆盖，技能只改本技能负责的部分 |
| 私有提案运行中登记的快照来源 Claim（public_research、competitor_comparison） | 已解决（P7） | P7-6：运行接触过私有资料时，其登记的 Claim（含公开来源）可读范围 = 提案受众，不按来源推定为品类可读（§2.14、§3.6、§7.2、§8.1；技能 public_research、competitor_comparison） |
| rfq_extraction 在私有提案运行中准备 `category.parameter.publish` 候选 | 已解决（P7） | P7-7：私有上下文运行准备的候选，预览与确认时做与 promote 相同的身份检查（identity_not_removed）（§3.1、§3.5、AT-50；技能 rfq_extraction、competitor_comparison） |
| price_band、jtbd、review_pain_clustering 在私有提案运行中的新公开观察 | 已解决（P7） | P7-3：三者加 evidence.claim.record（T0），记录随提案保持私有（§3.6、§5.4；三个技能的 allowed_operations 与正文） |
| 数据性质标签（§2.2 competitor 的 measured / claimed / inferred / unknown）与 Claim 性质（§2.14）的对应 | 已解决（P7） | P7-5：实测 → observed；宣传 → extracted + vendor_claimed=true；推断 → inferred；未知保持 availability=unknown（§2.14、§3.6、§6.3；技能 README §6） |
| 导入的评论 / 退货文件（含客户投诉）是否经 evidence.extract 隔离读取 | 已解决（P7） | P7-4：一律经 evidence.extract；品类范围只抽品类可见的导入文件，客户投诉挂私有提案后抽取（§2.2 voice、§3.5、§4.2、§5.4、§5.5；技能 review_pain_clustering） |
| Claim / 证据关联表、模具与认证对象在 B3、B6 的落地状态 | 未解决 | 10/08 未核代码，交主会话核对（§1.2、§2.14） |
| 研究快照是"读取即登记"还是主循环调用 `research.snapshot.register`（技能包草稿 README §7） | 未解决 | 归 M2 定；M3 接口两种都兼容（§4.3） |
| G0 处置只按 item_status 判断，availability 为 unknown / conflicted 的 AI 草稿规格可不处置即批准（2026-10-08 审查第 7 项） | 已解决（P11） | §3.4 改为两种条件任一即须处置；与成熟度视图阻断项口径一致 |
| 共享被单条私有上下文 Claim 的身份检查挡住时，只能整次撤回运行 | 已解决（P9） | 新增 `evidence.claim.withdraw`（T1），规格见 §3.1、§3.6；附录 A 与契约目录需同步（契约 JSON 由主会话改） |
