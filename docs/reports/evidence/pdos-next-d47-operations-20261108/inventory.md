# D47 未实现操作盘点（2026-11-08）

基点 `d6abcbf2`（迁移 head `s0_0861`）。来源：`contracts/operations.json` 中 `implementation: not_implemented` 的条目，对照 v1.1 附录 A、正文 §02–§08、确认稿、拍板表与现有代码。

## 数量核对

清单 D47 写的是 14 条，那是 11-01 的数字。其中 `my_work.query` 和 `provider.agreement.register` 之后已经以接口方式实现（`implemented_local_endpoint`），现在剩 12 条。`auxiliary-operations.json` 里没有 `not_implemented` 的条目。

## 盘点表

| 操作 | 档位 | 领域 | 需要的表与事件 | 验收场景 | 设计是否完整 | 本次处理 |
|---|---|---|---|---|---|---|
| `supply.commitment.record` | T0 需资格与授权 | 制造·供应 | 新表：供方承诺版本链与当前指针；事件 `supply.commitment_recorded` | AT-20（声称与实到分开，齐套不误判）、AT-19 | 完整。v1.1 §03.5、§04.10、§05.5；拍板表 §5.3 把 F25 列为“设计已覆盖，排期即可”（来源可为本人陈述，生成“承诺日+1 天”检查，供应面板按 BOM 行显示需求、承诺、实到）；本人陈述作来源属 §5.2 F15“按 v1.1 改回”，不是新口径 | **实现** |
| `work.forecast.refresh` | T0 确定性引擎 | 项目·计划 | 新表：预测重算记录与当前指针；事件 `forecast.refreshed` | AT-18、AT-19；AT-67 已分配未写入附录 B（P82 D181 的固定案例） | 完整。v1.1 §03.5 四种时间分开、I08；P82 D181 关键路径与浮时、延期只传给受影响的后继；P58 预测晚于承诺只显示差异；P41 第 10 项工作日历接通前按周一至周五并标“未扣节假日与停线”；P66 单列为“系统重算”、不可撤回。已有带浮时的引擎 `projects/planning/engine` | **实现**（不改基线、计划日期和承诺） |
| `npi.tooltrial.create` | T1 | 制造·试模 | 新表：轻量模具记录、试模记录；同事务形成 VerificationRequest；事件 `tooltrial.created` | AT-12、AT-13–15、AT-17 | 部分。P79 D97 已拍板“轻量模具记录，实现 `npi.tooltrial.create`，模具状态进 Build 准备度；验收以试模样件的测试与具名复核表达，不新增验收命令”。纯函数内核已在 `manufacturing/trials/handlers.py`。缺：模具记录的建立入口（附录 A 没有建模具的命令）；准备度规则要求 `tooling` 验收事实带 `named_decision_id`，而 D97 不许设模具验收命令，“试模样件的测试与具名复核”如何折算成准备度事实没有设计 | 不做，待确认（见 D305） |
| `npi.fixture.accept` | T2 | 制造·工装 | 新表：治具验收决定与当前指针；事件 `fixture.accepted` | AT-17 | 部分。准备度一侧的验收事实结构已定（`schemas/resource_readiness/contracts.py`）。缺：签核角色（冻结设计没写，只有非冻结的 wave28 记录写“制造”）；治具身份从哪来（现在没有治具登记表，资源来自受控导入）；撤销与有效期；设备验收是否共用本命令；附录 B 把 AT-17 标在 S4，操作在 S2 | 不做，待确认（见 D306） |
| `quality.capa.effectiveness.decide` | T2 | 品质·CAPA | 改 `quality_issue_versions` 检查约束；接入有效性决定；事件 `capa.effectiveness_decided` | AT-25、AT-23 | 部分。纯函数内核在 `quality/issues/handlers.py`（独立性、观察期、新 Run 证据、全覆盖原失败）。`quality.capa.verification.review` 不是有效性决定（辅助合同明写不替代）。缺：判“无效”后的修订命令；“延长观察”未冻结；`quality.issue.close` 不在任何合同；复核记录到有效性证据的适配 | 不做，待确认（见 D307） |
| `supply.alternate.approve` | T2 | 制造·供应 | 新表：替代料资格与具名批准；接入齐套引擎的 `alternates`；事件 `alternate.approved` | AT-21 | 不完整。§04.10 只写“AlternateQualification 绑定可替代范围和验证”。缺：签核角色（工程、品质还是采购）；需要的验证证据（TestRun 还是适用性评估）；范围（引擎按 Build，设计说“可替代范围”）；有效期与撤销；批准是否改 BOM（若改应走 `change.order.approve`） | 不做，待确认（见 D308） |
| `customer.sample.send` | T2 | 交付·客户 | 新表：客户样品交付授权与意图；事件 `customer.sample_send_authorized` | AT-28、AT-29、AT-30、AT-47 | 不完整。§04.12 列了绑定字段。缺：授权人角色；是复用外部移交管线（现有 `external_handoff` 要求放行包与工程、制造放行，不适合 EVT/DVT 样品）还是另建；收件方只能是外部标签（P87 第 9 项不建客户实体）。真实外发须你授权 | 不做，待确认（见 D309） |
| `customer.acceptance.record` | T2 | 交付·客户 | 新表：客户承认记录（覆盖与未覆盖范围）；事件 `customer.acceptance_recorded` | AT-26 | 不完整。§04.12、§08.8。拍板表 C11 的五类范围（外观、尺寸、性能、包装标识、认证资料）标“需（做时）”决策记录，尚无 P 号。缺：谁可登记；是否必须关联交付记录；条件承认的条件与有效期；签样门禁是否消费它 | 不做，待确认（见 D309） |
| `evidence.source.withdraw` | T2 | 证据 | 事件 `source.withdrawn` | AT-46、AT-42 | 冲突。已有 T1 辅助操作 `evidence.original.withdraw`（事件 `original.withdrawn`）实现了同样的效果，Q10 语义已经满足。两者档位不同、事件名不同；缺载荷、对象范围（原件、登记资料还是公开快照）、签核人 | 不做，待确认（见 D310） |
| `product.definition.update` | T1 | 型号·定义 | 事件 `definition.updated` | AT-04、AT-06、AT-51、AT-55 | 不完整。新版本已由 `product.definition.draft` 承担，条目编辑已由 `product.definition.item.patch` 承担。缺：本命令修改哪些字段、是原地改草稿还是建新版（数据库触发器只允许发布与封存两种迁移）、`in_review` 与协审命令 | 不做，待确认（见 D311） |
| `product.definition.publish`（规格冻结） | T2 | 型号·定义 | 改定义发布状态约束与触发器；事件 `definition.published` | AT-06、AT-04、AT-52 | 部分，且归属在 W6。确认稿 P43 定为第一个冻结点、归 D36。缺：发布权限、协审模型、G0 产生的已封存 v1 如何发布、状态词（`published` 与设计的 `released`） | 不做，归 D36 |
| `engineering.interface.update` | T1 | 工程·接口 | 无表无代码 | 无专属 AT；相关 AT-24 | 不完整。§04.2 只有字段清单。缺：接口对象的结构与建立入口（附录 A 只有 update）、确认状态词、设计责任人语义、与工程配置的绑定、影响传播规则、执行人 | 不做，待确认（见 D312；与 D49“接口合同与设计责任人”同源） |

## 本次实现的口径（都来自上表的设计依据，没有新增政策）

供应承诺登记：
- 一条承诺是独立的版本链：建立、修订（供方改期或改量）、关闭、重开。历史保留，供 D199 供方画像积累数据。
- 绑定固定 Build 与其固定需求里的真实物料；供方只记外部标识，不建供应商实体（P87 第 9 项）。
- 来源：具名本人可以用本人陈述（`time_basis=human_recorded`）或原文引用；小Pai 只能用原文引用（`source_claim`），并须当前 T0 资格与授权。
- 检查日 = 承诺日 + 1 天（F25）。到检查日仍未关闭的承诺进“我的工作”注意项，注意项是只读投影（§02.11），不另建待办。
- 承诺不计入库存与齐套（AT-20），齐套仍只按供给快照计算；面板按 BOM 行把需求、承诺、实到分三列显示。
- 维护人：建立人或项目负责人（与外部等待相同）。

预测重算：
- 读当前已应用计划的固定输入（工期上下限、依赖、日历）和关联任务的实际开始与提交时间，用 `projects/planning/engine` 计算，得到区间、浮时与关键路径。
- 只写新的预测记录与当前指针；不改计划版本、计划任务、基线和任何承诺。预测晚于承诺只显示差异（P58、I08）。
- 信息不足时输出未知或区间（AT-18）。日历是计划自带的工作日历；页面与回执标“未扣节假日与停线”（P41 第 10 项）。
- 意图指纹绑定服务器算出的输入摘要：输入没变，重放返回原回执；输入变了，须带新摘要发起新一轮。
- 活动记录单列为“系统重算”，不计为小Pai 的动作，也不提供撤回（P66）。
