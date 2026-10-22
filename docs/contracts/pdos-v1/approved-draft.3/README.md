# N0-01 共同对象合同 · 可执行候选

版本：`1.0.0-draft.3`，日期：2026-09-10。来源：[完整设计合同](../../design/2026-09-10-pdos-complete-design-contract.md)第7、9–13、15、19及25节。活动项仍为[N0-01](../../../tasks/ai-native-integrated-todo.md)。

用户要求“按照新的设计开始执行”。当前候选包含共同基础、产品/计划衔接、版本有效性/时间操作三片，执行新增合同的本地实现与验证，继承已批准的安全及业务语义；候选字段未接入生产路由，不代表完整N0-01冻结、业务功能上线或阶段出口通过。无新迁移、数据库连接、真实模型调用或外发。共同选择已收拢为[六项冻结提案](n0-freeze-proposal.md)，待系统负责人裁决。

## 1. 可以直接使用的产物

- [共同对象OpenAPI组件](common-objects.openapi.json)：由Pydantic模型生成的字段类型、必填性、枚举、长度/精度、引用组件；`paths={}`，不会把尚未实现的命令宣称为可调用API。
- [当前实现盘点](implementation-inventory.json)：97张表的列/约束/FK、11namespace、59个迁移（含0000脚手架）、69事件及真实静态Agent路由/no-route、七角色动作、215个API操作。只说明本地代码，不说明数据库已经升级、运行接线或生产现状。
- [来源与产物摘要](manifest.json)：绑定设计、旧草案、当前schema/权限/事件/运行、API/领域/迁移及生成器源文件。修改来源后可重新生成并检查漂移。
- [业务字段校验器](../../../server/app/contracts/common_objects.py)、[运行记录校验器](../../../server/app/contracts/runtime_records.py)、[正反例测试](../../../server/tests/test_common_object_contracts.py)。

在仓库的`server`目录执行：

```sh
.venv/bin/python -m scripts.export_common_contracts
.venv/bin/python -m scripts.export_common_contracts --check
.venv/bin/pytest -q tests/test_common_object_contracts.py
```

`--check`仅比较，不更新文件。导出只导入SQLAlchemy metadata、迁移图和FastAPI路由声明，不创建engine、不发请求、不运行lifespan、不读取业务行。产物可随代码评审，不能用来推断生产参数或业务数据。

## 2. 字段合同与验收追溯

本片使用稳定的`N0C-`编号，补充原设计章节定位；不更改原107条要求或65项工作编号。下表中的校验是进程内的输入/跨字段一致性校验，实际ACL、FK、并发锁与批准校验仍须在后续领域事务实现。

| 合同ID | 设计来源 | 模型与已验证规则 | 实施接线归属 |
|---|---|---|---|
| N0C-001 | §9.1/15 | ScopeRef/ScopedRecord/SourceRef：tenant scope匹配、来源同tenant、正版本或as-of+digest；额外字段拒绝 | N0-01/02、N1-01 |
| N0C-002 | §7 | ScopedWorkItem：非项目工作、分派/完成/接收证据；项目动作保留Task | N1-01、N3-04 |
| N0C-003 | §10 | ReviewRecord：DCP/TR独立，finalized才有结果/批准；conditional有条件 | N1-07、N4-06 |
| N0C-004 | §9.3/11 | ScheduleNode/ScheduleSource：一种typed source，kind/tenant/project一致；独立里程碑无源实体 | N2-01 |
| N0C-005 | §6/7 | PlanCandidate/PlanNode/PlanDependency：稳定key、未知责任/工期保留、估时有依据、孤儿/重复/环路拒绝 | N2-03/04 |
| N0C-006 | §11 | TimeRecord：四时间分轴，基线/承诺有批准，Forecast有算法，Actual有实绩来源；不在节点重建四组真值 | N2-01/06/07 |
| N0C-007 | §11 | WorkCalendar/ResourceCapacity：时区、日历版本、明确单位/容量和来源；旧项目resources不充共享容量 | N2-02、N6-01 |
| N0C-008 | §11 | SupplySnapshot：外部来源/as-of/新鲜期、数量单位，unknown=null，真实0可表达 | N5-01/02 |
| N0C-009 | §9.3/12 | Metric/MetricsDocument：稳定key、原值/规范值/单位/工况/阈值/规则/来源、缺证据不能给结论 | N4-01/02 |
| N0C-010 | §12.1 | SampleConfigurationRevision：六项配置、修订与冻结时点；无法恢复的旧配置不能抄当前值 | N4-01 |
| N0C-011 | §15 | AuthorizationEnvelope：主体/运行/lineage/政策/目的/时效，tenant run还需绑定锚点 | N0-02/03 |
| N0C-012 | §15 | ContextManifest：逐revision、parent、版本束和观察集合；明确缺项，不能自指或重复观察 | N0-03 |
| N0C-013 | §15/16 | Observation：工具/来源/ACL/taint/摘要/分页/失败码；正常0结果与失能区别 | N0-03及领域工具 |
| N0C-014 | §15/20 | CompactionRecord：原观察、来源ACL依赖、精确事实/批准/未决/省略及回读 | N0-03 |
| N0C-015 | §19 | RunControl：控制与正文分离；等待有checkpoint并释放worker，完成有具体outcome | N0-03 |
| N0C-016 | §7/13/19 | OperationReceipt：候选digest/幂等键、审阅/应用人及时间、目标映射、Event/Audit；应用和实际执行分开 | N0-03、N2-04 |

模型对象冻结采用不可变字段及嵌套tuple；这是进程内防误修改，不是数据库不可变保证。`model_construct/model_copy`可绕过Pydantic验证，领域接线不得用于不可信请求。JSON Schema不能表达全部跨字段规则，必须执行对应Pydantic验证器与服务端事实复核。

`contract_digest`是经过模型验证、包含默认值、JSON键排序的载荷摘要；不做内容相似或语义去重，不把它当批准令牌。时间/Decimal语义规范化政策仍需后续领域合同明确定义；不同输入表示不承诺同摘要。Manifest自身digest的计算范围与持久化幂等由N0-03落实，不能用包含自身digest的整对象哈希代替。

## 3. 四项开放建模的具体落地建议与代码差异

| 决定 | 当前真实代码 | 本片按新设计准备的方案 | 数据库/运行约束与兼容 |
|---|---|---|---|
| DC-01 namespace | 实际11个，Meeting在project，Evidence独立 | 保留现有归属；时间/资源/前期工作入project，市场/定义入product | 不创建旧草案的meeting/schedule schema，不搬表；每次迁移按真实head分配 |
| DC-02 排程引用 | 无schedule_nodes；Task依赖是单独关系 | 源kind+单一typed引用，正式节点与PlanCandidate临时key分开 | 迁移时显式可空FK列+CHECK恰好一个，并对tenant/project/source构造复合FK；独立milestone例外。不能只有字符串+应用检查 |
| DC-03 角色/职责 | project_members没有project_role；实际是租户Role+成员/代理范围 | 复用7 Role；专业职责独立，不机械增加DQE/SQE/IE权限角色 | 如落nullable project_role，NULL继续旧行为；非NULL只取租户权限与项目限制的交集。委托还需双方有效授权交集；不因专业或persona扩权 |
| DC-04 metrics/配置 | metrics是JSONB数组；配置upsert；Run没有configuration_revision_id | JSONB数组保留，独立schema_version；新增不可变配置revision供当次Run引用 | MetricsDocument仅是传输/校验信封，DB仍存metrics数组，不把现有数组改对象。旧值保持legacy，不静默转换；历史未知配置用unknown迁入记录，不把现在frozen_at当历史实测时点 |

本片推荐DC-02的物理实现为显式FK：task_id→tasks、gate_id→gates、build_id→build_batches、test_run_id→test_runs、certification_id→certifications，tooling_id待N5相应表合同；所有目标补必要`UNIQUE(tenant_id,project_id,id)`后，使用同三列复合FK。尚无tooling表时不放开可持久化tooling节点，先保留候选/unknown。API合同中source是一种，持久层拆FK列，禁止两个来源同时成立。服务必须核对对象存在/当前权限与source版本，不能依赖请求自报的tenant/project。

其余已核实旧草案差异：

| 历史草案 | 当前事实/处理 |
|---|---|
| 75表、head0033，预排0034～0058 | 当前97表、head0058；这些编号已有真实内容，不能重用 |
| Meeting draft/minutes_pending/closed | 当前scheduled/in_progress/completed/cancelled；前期DCP/TR不是Meeting subtype的结论 |
| 导入parsing/partially_confirmed | 当前parsed/confirmed/failed，解析运行状态另轴 |
| CCR旧状态简写 | 当前received/impact_analyzed/reply_drafted/reply_approved/accepted/rejected/cancelled；保留实际回复/客户/工程变更过程 |
| Decision可用一段备注标完成 | 当前complete_follow_up仍写完成备注；真实执行回链按N0-04补齐，不能因已有API就视为解决 |
| Resource项目allocation_percent | 不是全租户共享资源身份/容量/预约；按N2-02增量引入后保存旧ID映射 |
| 旧Context v2“直接升v3” | 旧数据只读适配；无法恢复授权字段记legacy_unknown，新运行须生成真实授权 |
| Event通用entity_id直接用于排程 | Event是事件引用；正式排程必须有关系完整性，不共用其宽松引用 |
| Agent创建任意业务draft再单动作转正 | 已被后续双动作合同替代；本片没有修改Agent权限或旧Finding出口 |

## 4. 物理与兼容设计待接线点

所有正式新业务表继承UUID、非空tenant、tenant复合唯一/FK、UTC时间、状态CHECK、业务+Event+Audit同事务。现有Event/Audit行号是BIGINT，回执保留正整数；外部event_id保持原字符串语义。发布正文与可变控制关系分开；只靠`CHECK`或Pydantic frozen不能证明发布不可变。最终逐组对应见[物理字段与兼容映射](physical-contract-map.md)。

| 对象组 | 建议物理归属/写入主体 | 核心持久化约束与迁入 |
|---|---|---|
| ScopedWorkItem | cehub_project，人工领域服务 | scope注册目标由服务端解析；完成历史保留，未完转Task记录唯一旧ID→Task映射，一个活动执行真值 |
| DCP/TR | cehub_project，具名评审领域服务 | 独立评审id/kind/round及冻结sources/policy；结果失效控制独立，不覆写历史结果；Gate按版本消费 |
| PlanCandidate/正式计划 | 模型正文仅Finding；cehub_project存人工应用操作/基线 | Case→Project现有唯一转换；批准引用候选digest；Task/边/基线/映射同事务；失败不激活项目 |
| 四时间 | cehub_project独立版本/快照族 | Baseline、Forecast、Commitment、Actual各自来源；节点缓存只投影；旧due不自动升格批准 |
| 日历/资源/容量/预约 | cehub_project，领域服务 | 资源身份跨项目复用；容量按版本和窗口，正式reserve再加锁/校验；情景不占容量 |
| 供给快照 | cehub_supplier，授权采集服务 | external id/as-of/digest去重；BOM需求/分配按Build独立，ERP零反写 |
| 配置revision | cehub_product，人工/授权原值导入 | UNIQUE(tenant,sample,revision_no)，Run复合FK到当次revision；原current配置保留兼容指针 |
| Manifest/Observation/Compaction | cehub_ai，可信运行窄接口 | UNIQUE(run,revision_no)、UNIQUE(run,sequence)、同digest幂等/异digest冲突；追加只读、保留来源ACL依赖 |
| RunControl | cehub_ai，可信worker | generation防过期续写、checkpoint、累计lineage预算；可变lease不写进冻结正文 |
| OperationReceipt | 业务操作真值cehub_project，AI仅引用 | tenant+动作+幂等key唯一，digest冲突409；对象/事件/审计同事务，执行/接收后另回链 |

这里是可评审的映射，不注册任何新数据库表。正式物理字段、迁移顺序/回填和受限账号正反例在依赖相应合同的实施前收口；不把schema导出当数据库迁移完成。

## 5. 产品与正式计划衔接增量

第二片新增对象字段及操作不形成第二条实施队列；仍在N0-01内。完整字段约束见生成OpenAPI，SoR/Owner/FK/兼容见[对象归属字典](object-ownership.json)（第三片扩充至35个），操作/事件/状态/错误见[逻辑操作合同](logical-operations.json)。历史验证见[第二片记录](../../reports/2026-09-10-n0-01-product-planning-contract-validation.md)。

| 合同ID | 设计来源 | 本轮可执行内容 | 实际接线归属 |
|---|---|---|---|
| N0C-017 | §7/9 | ProductHierarchy完整层级、父级/唯一编号/租户；MarketSpace、ResearchTask、DesiredOutcome真实立项前对象 | N1-01/02/04、N6-04 |
| N0C-018 | §7 | Opportunity/Solution三方案、Outcome锚点及评分口径；实验四维假设/方法/证伪/实际结论 | N1-04 |
| N0C-019 | §7 | 九区Canvas、策略方案比较、专业约束、发布依据；假设与批准分轴 | N1-05 |
| N0C-020 | §7/12 | Definition/稳定SpecItem、功能含排除、未知判据、当前必需发布条件、引用与版本 | N1-06/07、N4-02 |
| N0C-021 | §7 | Case→Project唯一转换、WorkItemTransfer保留历史/只迁未完、计划digest绑定批准与回执 | N2-04 |
| N0C-022 | §7/21 | active项目Adoption独立兼容记录，原七态/历史批准不改；补齐有真实操作回执 | N2-04 |
| N0C-023 | §9/11 | 共享ResourceIdentity与带日历/容量版本的Reservation；情景不占容量，预约/释放各留痕 | N2-02、N6-01 |
| N0C-024 | §2/9 | ProjectRoleAssignment复用7 Role，nullable项目角色与专业职责分开；角色限制交集由N0-02接线 | N0-02 |
| N0C-025 | §13 | 首批8个逻辑命令、6类严格事件载荷、错误/幂等/事务合同；请求不接受自报操作者/批准事实 | 各所属领域N项 |
| N0C-026 | §10 | 7套目标状态转换；禁止发布后改正文、越过实验/评审、完成工作被迁移重开 | 各所属领域N项 |

产品已发布正文的替代/撤回不复用draft状态；需要独立的有效性控制记录。现有Gate/Task/Issue/Risk/Meeting/Decision等沿盘点中的真实枚举和领域服务，不把这7套新目标状态机覆盖到旧列。事件名称和payload版本只在候选目录，后续在实际生产者与消费者落地时再注册，不能把未接入消费者的目录当主动AI已实现。

工程单位使用独立Unit文本类型，保留`°C/%/m³/s/kg/m^3`；稳定编号才使用Key。指标值、单位、判据来源及规则版本分别存在，自动换算/通过判断仍必须经过引擎和专业政策。

## 6. 版本与时间操作收口

| 合同ID | 设计来源 | 本轮可执行内容 | 实际接线归属 |
|---|---|---|---|
| N0C-027 | §9/10/21 | VersionValidity独立控制修订；替代同scope/type且版本递增，发布正文保留 | N1/N4领域及N7 |
| N0C-028 | §15/19/25 | RuntimeReleaseBundle固定代码/迁移/能力/schema/prompt/tool/投影/政策/资格/golden版本；v2只读不伪造授权 | N0-03、N7 |
| N0C-029 | §11/13 | 基线应用、预测重算、承诺确认、实绩记录/更正、供给捕获、有效性变更7命令和6事件载荷 | N2/N5及版本消费者 |
| N0C-030 | §7/11/13 | 计划验证/情景评估2查询；缺输入不可伪造可计算日期，计划valid与阻塞一致 | N2-03/05 |
| N0C-031 | 当前events writer/§13 | SourceRef事件引用、CommandResult/Receipt/转换/因果回链对齐真实整数行号；外部事件字符串需受权解析 | N0-03及领域应用 |

[第三片验证](../../reports/2026-09-10-n0-01-freeze-candidate-validation.md)记录本次实际结果。候选当前共88个OpenAPI组件、35个对象归属、15个逻辑变更命令、12种严格事件载荷、2个查询与7套目标状态机。查询是合同声明，未实现排程计算或注册模型工具。

## 7. 边界与下一步

N0-01保持`[~]`。现有97表/69事件/215 API/59迁移盘点不变，三片合同共77项测试，含旧兼容回归120项通过。实际运行、数据库和员工效果尚未由这些纯合同测试证明。

下一步是DC-01～05及DC-09共同部分的裁决与冻结记录，详见六项提案；无批准人/时间记录前不宣称N0-01完成。N0-02可独立准备现有能力/权限/预算盘点，依赖这些差异的实际变更须在裁决后实施。具体领域扩展、容量/时间计算和实时授权处理仍在原N项实现；N0-02统一逐能力范围、候选/人工出口、预算/费用/保留/出站政策。

安全边界不以本片测试替代：SourceRef内tenant相等不证明真实同租户；ApprovalRef结构齐全不证明人已批准；同一人相同时间的两个字段不证明真的进行了两个动作；冻结模型不证明数据库不能更新；循环检查不证明日期/资源引擎已实现。以上实际路径必须分别验收。无生产权限申请；当前待裁决的是清单明确要求的共同合同实质差异。
