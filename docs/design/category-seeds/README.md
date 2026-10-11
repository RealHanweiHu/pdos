# 品类种子资料（category seeds）

> **草稿 v0.2，C/D 业务口径已由用户确认** · 2026-10-08 · 参数、测试方法及具体法规适用仍待专业确认。种子研究内容来源性质保持 `ai_draft`；用户确认的决策单独记录，不把研究内容改成人工来源（架构 v1.1 §02.3a）。

## 1. 用途

为 PDOS 首批两个品类提供可导入的种子：规格字典（ParameterVersion）、品类测试模板骨架、法规认证、用户与场景骨架、竞品库字段。依据：

- `docs/design/2026-10-08-pdos-complete-target-architecture-v1.1.md` §02.3（SpecItem）、§02.3a（品类知识、规格字典、立项提案、客户资料边界）、§05.8（立项视图规则）；
- `docs/design/2026-10-05-preproject-redesign.md` §3.1、§3.5；
- 原工程只读参考：`server/app/domain/product_categories.py`（`ParameterSave`、`validate_parameter`、`category_test_template`）、`server/migrations/versions/0425_category_foundation.py`、`server/app/domain/competitors.py`。

技能包与 M3 合同引用本目录的 json 文件，字段名按下文约定保持稳定。

## 2. 文件

| 文件 | 内容 |
|---|---|
| `README.md` | 本说明及已确认的 C/D 决策记录 |
| `auto-tire-inflator.json` | 汽车充气泵机读版（31 个充气参数、31 个测试项、43 条法规目录条目） |
| `auto-tire-inflator.md` | 汽车充气泵审阅版 |
| `bicycle-pump.json` | 自行车打气筒机读版（30 个锂电形态参数、30 个测试项、44 条法规目录条目） |
| `bicycle-pump.md` | 自行车打气筒审阅版；手动/CO₂ 已纳入边界，专用字典与工况待补 |
| `sources.md` | 引用来源清单（56 条编号来源，含 URL、核验方式、核验日期） |

md 是给人审阅的表格版，json 是机读版；两者由同一份数据生成，内容一致，有出入时以 json 为准。

## 3. 统一约定

| 约定 | 内容 |
|---|---|
| 品类标识 | `auto-tire-inflator`（汽车充气泵）、`bicycle-pump`（自行车打气筒） |
| 参数引用 | 字典条目用 `parameter_id` + `version`（从 1 开始）；测试模板、提案/定义的 SpecItem、竞品指标用 `parameter_id` + `parameter_version` 引用 |
| `key` | v1 中 `key` = `parameter_id`。导入原工程时库内 `parameter_id` 为 UUID，以 `key` 对应 |
| 逐字引用 | `key`、`unit`、`conditions` 必须与字典同版本逐字一致（原工程 `validate_parameter` 和库触发器按字符串比较）；工况不同另列待决项，不硬比 |
| 品类隔离 | `parameter_id` 只在品类内唯一。两个品类同名参数（如 `max_pressure`）测试工况不同，**不是同一参数，不跨品类比较** |
| `direction` | `higher` 越大越好 / `lower` 越小越好 / `target` 目标区间 / `neutral` 无方向（与原工程 CHECK 约束一致） |
| `benchmark_weight` | `high` / `medium` / `low`，对标权重建议，附理由 |
| 数据性质 | `measured` 实测 / `claimed` 宣传 / `inferred` 推断 / `unknown` 未知（与 `CompetitorMetric.nature` 一致）；字典里的 `data_nature_hint` 只提示该参数常见数据性质 |
| 条目状态 | 参数使用 `ai_draft` / `expert_pending` / `confirmed` / `unknown`（对应 SpecItem 的 AI起草 / 待专家 / 已确认 / 未知）；本稿参数只有前两种。C/D 的 `user_confirmed` 单独记在决策记录，不是参数或法规资格 |
| 形态覆盖 | 品类用途边界与字典覆盖范围分别记录；自行车现有字典/测试只覆盖锂电草稿，手动/CO₂ 不自动采用电动泵工况或 `required` 参数 |
| 法规状态 | 原 `status` 保留来源目录状态；`source_state`（来源）、`applicability_state`（具体配置适用）、`compliance_state`（合规证据）分别记录。全部适用性待认证负责人确认，合规证据未评估 |
| 要求性质 | `statutory` 法定 / `customer_channel` 客户渠道 / `voluntary_reference` 自愿参考；目录分类为 `ai_draft`，不是专家适用结论 |
| 测试模板项 | 字段与原工程 `category_test_template` 输出一致（`key`、`title`、`parameter_id`、`parameter_version`、`unit`、`conditions`、`direction`、`method`、`acceptance_criteria`、`state`），另加 `test_id`、`record_fields`；全部 `state = expert_pending`，`specifications_frozen = false` |
| 修订 | 参数版本不可改；修订产生新版本，旧版本保留，旧条目由人工映射 |
| 缺值 | 缺项和不可比条件保持“未知”，不补造测试标准或指标；不填市场数据与真实竞品数据 |

json 结构：

```
{ schema, schema_version, status, draft_label, origin, generated_on, source_ids_used, sources_file,
  categories: [ { category_id, name_zh, name_en, draft_label,
                  boundary { definition, includes[], excludes[], criteria[], criteria_note, edge_cases[],
                             classification_rule, decision_record },
                  dictionary_conventions { baseline_condition_B0, standard_tires, pressure_unit_note,
                                           coverage_note, coverage_gaps[], form_groups?, ... },
                  parameters[] { parameter_id, version, key, label, label_en, value_type, unit, unit_notes,
                                 direction, conditions, verification_method, acceptance_criterion,
                                 benchmark_weight, benchmark_weight_reason, data_nature_hint,
                                 applicability, origin, status, expert_open_points[], source_ids[] },
                  not_applicable[],
                  test_template { common_record_fields[], default_sample_plan, specifications_frozen, coverage_note, items[] },
                  regulations { notes[], decision_policy, coverage_gaps[], customer_requirements { scope, record_fields[], items[] },
                                items[] { region, coverage, requirement_kind, classification_state,
                                          domain, object, instrument, applicability, status, source_state,
                                          applicability_state, compliance_state, source_ids[] } },
                  scenarios { user_groups[], use_scenarios[], jtbd[], buying_criteria[], regions_and_channels },
                  competitor_fields { record[], metric[], price_quote[], certification[] } } ] }
```

## 4. 两个品类的关键差异

| # | 维度 | 汽车充气泵 | 自行车打气筒 |
|---|---|---|---|
| 1 | 标准测试工况 | 205/55 R16 汽车胎，0→36 psi 全充与 26→36 psi 补气 | 700×25C 公路胎 0→100 psi（记 80 psi 中间值）与 29×2.25 山地胎 0→30 psi |
| 2 | 压力与流量特性 | 目标压力几十 psi，补气时间为主指标，`max_pressure` 权重中 | 高压低流量，`max_pressure` 权重高，零背压流量几乎无参考意义 |
| 3 | 气门与连接 | Schrader 为主，Presta 经转换嘴 | Presta 为主，单列 `presta_connection`、`valve_core_retention`；螺纹泵头不兼容 Schwalbe Clik Valve |
| 4 | 便携性 | 车载存放，重量权重中；新增 `storage_retention`（长期放车内）、`power_cord_length`（12 V 有线款） | 随车随身，重量/体积权重高；新增 `mount_options`、`display_resolution`；防水与跌落权重更高 |
| 5 | 产品形态 | 含锂电、12 V 点烟器有线、双供电、多功能泵和组合机，按供电/功能分组 | 含锂电电动、手动、CO₂，分别比较；当前 30 项字典/测试仅覆盖锂电草稿 |

## 5. 导入前须知

- **只追加**：导入时每个参数建为 version 1；以后修订产生新版本，不改旧版本。
- **来源性质**：全部为 `ai_draft`。原工程 `category_knowledge.origin` 的 CHECK 只允许 `human_shared` / `human_anonymized`，与 v1.1 §02.3a 要求的 `ai_draft` 不一致；法规、场景等知识条目须经人确认后才能按原工程入库，或先在新工程补上 `ai_draft` 取值。
- **校验已通过**：参数键格式、名称 ≤128、单位 ≤64、条件 ≤1024、方法与判据 ≤2048、单品类 ≤60 个参数、方向取值，均按原工程 `ParameterSave` 与 0425 迁移约束检查。
- **测试模板**：全部 `expert_pending`；原工程 `category_test_template` 在方法与判据都非空时会标 `ready`，导入后须保持待专家状态，直到专家确认。
- **竞品字段**：与 `server/app/domain/competitors.py` 一致；新增建议字段 `segment_tags`（品类矩阵分组用）待确认。

## 6. 待确认汇总

- **参数测试条件**：汽车 18 个参数共 22 个待专家确认点，自行车 14 个参数共 13 个；明细见各品类 md §7 和 json `expert_open_points`。
- **品类边界 C 已确认**：见下方决策记录。手动/CO₂ 专用参数和工况、搭电/补胎液及兼用场景专用参数与测试骨架待专业确认；已有参数和测试判据没有因此获得确认。
- **法规 D 口径已确认**：六市场为知识覆盖范围，各提案选择实际市场，认证负责人确认适用性，考虑持续销售，客户/渠道要求纳入。汽车 43 条、自行车 44 条为来源目录，不是具体产品的完整合规矩阵；全部具体配置适用性及新增形态覆盖待认证负责人核对，合规证据未评估。
- **市场数据**：六市场的知识覆盖已确认；购买标准排序、细分占比及各市场渠道差异仍待研究，不填市场数据和真实竞品数据。

<a id="cd-confirmed"></a>

## 7. C/D 决策记录（用户 2026-10-08 已确认）

本会话用 Grill me 逐项确认 Q1–Q9，最终汇总经用户回复“好的”确认并授权同步种子资料。本节记录业务决策；v1.1 的权限、来源、私有客户资料及具名签核边界继续适用。

| 编号 | C：品类边界 | 已确认口径 |
|---|---|---|
| C1 | 分类原则 | 按用途划界，供电、结构及产品形态作为品类内分组；与我方当前自研范围分开 |
| C2 | 汽车泵形态 | 包含锂电、12 V 有线及双供电 |
| C3 | 自行车形态 | 包含电动、手动（落地式/便携式）、CO₂，参数与工况分别比较 |
| C4 | 汽车/自行车等多功能泵 | 统一归汽车品类，按市场对标；其他用途记为兼用场景，不再按主图或主气门在两个品类间归属 |
| C5 | 滑板车/平衡车 | 作为兼用场景，工况单列；不单独建品类。摩托车继续作为汽车品类兼用场景 |
| C6 | 补胎液套件与充气＋搭电组合机 | 归汽车品类；附加功能要求单列，整套产品评估覆盖全部功能 |

| 编号 | D：法规与认证 | 已确认口径 |
|---|---|---|
| D1 | 知识覆盖 | 欧盟、美国、加拿大、日本、澳大利亚、中国大陆；英国、韩国保留储备资料，全球运输按实际路线评估 |
| D2 | 产品实际市场 | 每份立项提案明确销售市场、客户/渠道与配置；覆盖六市场不等于每个型号六地同时可售 |
| D3 | 判定责任 | 认证负责人确认法规适用结论；来源已核实、适用性已确认、合规证据已通过分别记录 |
| D4 | 时间范围 | 考虑持续销售期间的法规变化、生效时间与过渡要求；不预先替所有提案决定统一全球结构 |
| D5 | 要求范围 | 法定要求、客户/渠道要求、自愿技术参考都纳入并分别标注 |
| D6 | 客户特殊要求 | 客户开发产品的额外认证、测试和特殊要求挂对应提案/变体，关联规格、测试与证据；客户原件私有，品类共享须人工确认并去标识 |
| D7 | 配置判定 | 按实际本体、电池、充电系统/适配器、包装/标签、无线/联网、移动电源、搭电、照明、补胎液、手动/CO₂ 等形态分别评估；研究尚不完整的保持待确认 |

用户原答要点：Q1“按用途划界”；Q4“汽车/自行车等 多功能泵 按照汽车泵来划分。这个对标市场就好”；Q5“作为兼用场景”；Q6“汽车品类”；Q7“作为覆盖范围，每个提案立项再明确”；Q8“考虑持续销售”；Q9“需要”（并指出客户开发产品存在额外要求）。认证判定责任按 Q3“认证负责人”。

本次只确认 C/D 口径，种子参数 `version = 1` 和方法/判据保持原草稿，所有测试项仍为 `expert_pending`、`specifications_frozen = false`。未导入数据库、未授予真实模型或产品合规资格。同步与静态一致性证据见 [结果记录](../../reports/evidence/pdos-next-m3-20261008/category-seed-cd/result.md)。
