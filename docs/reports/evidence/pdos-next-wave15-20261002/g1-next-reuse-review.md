# G1 研究 / OEM 下一闭环复用盘点

2026-10-02。只读盘点与接线建议，不改变当前 Wave15 质量候选、公共导航或唯一清单；本次未运行数据库、HTTP、浏览器、构建或测试。依据目标架构 §4、前台页面契约及执行方案 G1.1～G1.4，定向核对 discovery 包、当前公共接口和新导航。

**结论：先接“人工研究 / OEM 来源包 → 并列证据与缺项 → 内部定义草稿”。** 已有包覆盖这一段的纯规则和五个组件；主要工作是范围、持久化、可信来源读取与公共事务接线。竞品页面可复用分组比较；机会 / 实验尚无 pdos-next 持久对象，不能将导航占位或普通 Claim 算作已交付。

## 当前可复用对象与入口

| 接缝 | 已有资产 / 精确路径 | 可复用程度与边界 |
|---|---|---|
| 来源事实 | `pdos-next/server/pdos_next/contracts.py` 的 ArtifactPayload / ClaimPayload；`models.py` 的 Artifact / Claim；`service.py::source_for`；`web/src/components/workspace.tsx` 的 sources 面板 | 已有产品范围内登记原文、精确行 / quote、已知 / 未知 / 冲突与撤回历史。Claim 是有来源陈述，尚无研究参数、竞品身份、机会或实验语义；不能直接提升为已接受需求。 |
| 原件及定位 | `originals.py`、`original_security.py`；`web/src/lib/original-location.ts` | 复用扫描、当前安全决定、解析来源和 locator_map。Discovery Citation 还要求正文哈希、不可变原件版本 / 哈希和唯一 line / page / cell 映射；由服务器 SourceReader 补齐，不能由浏览器声称原件可用。扫描通过不等于规格原值或客户批准已核验。 |
| 研究 / OEM 来源包 | `domain/discovery/handlers.py::Discovery.start/ingest/inspect`；`schemas/discovery/contracts.py` | Research 固定 scope、用途、受众、questions / use_cases；PackageItem 分类、Observation 原文 / 规格 / 条件 / 适用范围、内容去重和不可覆盖身份可直接复用。OEM 类别完整性取服务器适用政策；类别齐备不等于技术有效。 |
| 竞品 / 客户并列证据 | `domain/discovery/rules.py::groups/conflicts/spec_unknowns`；`sources.py::PinnedSources` | 稳定 key 下逐字段比较值、原单位、方法、条件、适用范围，保留冲突；无单位换算、最新版胜出或成熟度推断。可作为比较算法，仍缺竞品对象 / 型号 / 版本与“可比口径”绑定，不能把同 key 的不同产品参数自动判为同一规格。 |
| 定义候选 | `Discovery.preview/handoff`；`schemas/discovery/contracts.py::DefinitionCandidate` | 保留全部并列观察、未选来源、缺类别、遗漏组、具名选择和 digest，生成现有 DefinitionDraftPayload。普通原文 / 翻译保持 pending；窄结构化 JSON 的全字段相等只证明对应关系。未知不补 0，结果仅内部草稿。 |
| 真实定义写入 | `domain/products/definitions.py::validate/apply_draft/list_definitions` 与 `domain/products/models.py` | 原 DefinitionRevision / Spec / Source 作为唯一写入所有者，保留同 Product 父版、最新可见版本冲突、私人来源限制及人工身份守卫。新接线应在公共 UOW 内写候选 provenance 固定关联，不能只保存 payload 而丢掉研究版 / 冲突 / 选择依据。 |
| 五个独立组件 | `web/src/components/discovery/index.ts` 导出 ResearchStart、SourceImport、SourcePackage、DefinitionSelection、CandidateReading | 可由新 wrapper 直接组合；callbacks / Context.readiness 必须接服务器事实，onPreview 进入共同确认，不再造第二个批准。现组件无公共 API、原请求持久恢复或权限失效控制器；这些由 wrapper 补。阅读里的 Artifact 身份宜用真实来源名称展示副本，原 Citation 不改。 |
| 后续工程 / 制造回接 | 现有产品定义、派生、项目计划、双配置、Build、成本 / 供应、验证结果入口 | OEM 内部定义保存后可引用真实固定版进入已有路径；无需重新做客户已决定的市场策略。研究实验也不强制实物 Build。制造可行性、成本未知、方法资格及正式发布仍按各自服务器能力判断，不由导入“完成”继承批准。 |

Discovery 的[既有交付报告](../pdos-next-discovery-20261002/result.md)记录 17 个包内候选文件、63 项纯 Python 与 11 项组件检查，候选摘要 `7ada664c5e900d0f85d919770a915c8764ee657a934366bd4a2acc6369b69b57`；其[集成说明](../pdos-next-discovery-20261002/integration.md)明确未接主线。这里引用历史包级证据，不宣称本次候选或 G1.1 联合验收已通过。

## 新导航的真实覆盖

`web/src/lib/workspace-navigation.ts` 当前“产品 / 研究 / 资料与事实”指向 sources、“原件”指向 originals；竞品对比、机会与实验、矩阵与路线图、反馈明确 `planned: true`。`workspace-experience.tsx` 相应占位仅跳回资料、派生或测试结果。`workspace.tsx` 已挂定义 / 派生等真实组件，未导入 discovery 组件；公共 `api.py`、`contracts.py`、`command_handlers.py`、BFF 路由亦未登记 discovery / research 操作。导航重组可作为入口壳复用，不能替代领域接线。

当前壳与 CommonCommand / Artifact 都以真实 Product 为范围：`Command.product_id` 必填，`Artifact.product_id` 固定外键，require_access 和 source_for 按产品读取。Discovery 的 Authority 则允许 Product 未绑定、要求独立 scope，定义 handoff 才要求真实 Product。因此：

- 已有真实产品的 OEM / 研究可先做最短接线，保持“无需 Project”；不要宣称覆盖尚未绑定 Product 的独立研究。
- 完整自主探索必须补真实 ResearchScope / 成员 ACL / 来源关联和命令范围合同。不得造一个虚拟 Product 或 Project 来满足现有必填字段；`audience=product` 在独立研究阶段的共享含义也须先冻结。
- 用户另一会话正拥有导航与公共入口；后续只由主线协调挂载，不把复用盘点变成同时修改 workspace 的授权。

## 最小闭环与先冻结接口

1. 服务器绑定真实 scope、human principal、用途、受众和 OEM 必需类别；保存 Research 版本。人工开始，不依赖真实 LLM、网页爬取或 CRM。
2. 选择当前可读原文 / 原件位置，保存来源包和观察；展示 raw_text、原单位 / 方法 / 条件、pending、冲突与缺项。SourceReader 返回可信 SourceSnapshot，重核来源当前 ACL / 撤回 / 安全 epoch / 原件身份与定位。
3. 逐组选择或保留未裁决；部分导入明确理由。研究绑定真实 Product 后生成固定 DefinitionCandidate，预览完整 provenance、遗漏 / 冲突及父定义版。
4. 同一公共事务写 DefinitionRevision 与候选关联、Receipt / AuditOutbox；执行前重算 candidate digest、全部来源和 Product / 父版。现定义只支持本人手工草稿，保持该边界，不自动发布或创建 Project。

**已有 DTO 可冻结复用：** ResearchStart、ImportBatch、Citation / Observation、Research、CandidateRequest、DefinitionCandidate、SourceSnapshot，以及五个 UI 的 Context / Callbacks。**仍需主线决定：** independent scope 的公开 DTO 与 ACL；研究命令 / 事件的实际注册及 T0 / T1 分级；ResearchPort 的不可变版本 / CAS 与内容语义去重；候选 provenance 的固定 Definition 关联；绑定研究来源到 Product 的真实授权关系。当前 `discovery.sources_imported` 是包内事件名称，不能仅因名称存在就宣称公共事件已接通。

建议读取 DTO 包含当前研究版、可读 source_options（名称 + 可信 Citation）、required_categories、逐动作 capabilities / blockers、required_source_read_set、目标 Product / 可读父定义选项和 candidate；公共确认返回完整 prepared command 原封提交。独立范围切换或权限失效清除派生内容，未知提交保留同 command / key，提交成功后读失败分别提示。按 scope / research 明确选择读取，不为首屏深读全产品历史。

## 机会 / 实验补位与并行归属建议

机会与实验首先需要有来源的机会、假设、方法 / 判据、实验记录 / 结果、具名取舍与固定定义回链；目前 discovery 只保留 questions / use_cases / observations，**没有这些版本对象、操作或决定记录**。下一小切片可先做人工、有来源的实验记录和结论候选，未知结果保持未知；不能将研究 Observation、现物理 TestRun 或 CAPA 假设直接改名当通用实验。投入决定 / Definition 发布属于 G1.4，须独立 Review / Decision / FreezePoint 与专业约束，不由实验结论自动通过。

| 并行包（建议，尚非施工授权） | 独占新增目录 / 文件 | 冻结依赖与共同边界 |
|---|---|---|
| A：研究宿主持久与可信来源端口 | `server/pdos_next/domain/discovery_execution/**`、`server/tests/discovery_execution/**` | 实现现 Discovery 的 ResearchPort / SourceReader；先交 scope、版本 / CAS、来源读取 DTO。公共 Context / Command、全局模型注册、RLS / 迁移和 source_for 不归该包自行改变。 |
| B：机会 / 实验最小纯域 | `server/pdos_next/domain/opportunity_experiments/**`、`server/pdos_next/schemas/opportunity_experiments/**`、对应 tests | 可先并行定义有来源的假设 / 实验 / 结论 DTO 和未知规则；只读引用固定 Research / Observation / Definition。新公开 operation 名、持久化和具名决定由主线冻结后接，不写研究或定义表。 |
| C：G1 前端 wrapper / 比较投影 | 新 `web/src/components/product/product-discovery.tsx`、`web/src/lib/product-discovery-view.ts` 及 helper tests | 组合已有 discovery 五组件；纯展示竞争对象与可比口径、原文名称和引用，接服务器能力、共同预览 / 原请求恢复。未冻 B 的实验接口时只明确未接入，不显示可执行按钮。既有 discovery 包和用户导航不改。 |

主线统一公共范围合同、迁移 / RLS / 模型注册、定义 provenance 写入接缝、命令与事件注册、API / BFF / 导航协调及受影响联合验证。先行冻结 A 的 scope / 来源 DTO 即可让 C 并行；B 不阻塞人工研究 / OEM → 定义草稿首闭环。验收需要真实隔离 PG / API 与页面覆盖权限撤回、原件失效、重复导入、并列冲突、部分导入、父版冲突和确认漂移；历史纯包通过不能代替这些主线证据。
