# N0-02 权限、触发和组件采用合同

版本`1.0.0-draft.3`，2026-09-10。继承已批准N0-01/DC-01～05/09与既有D25/D26；本文件具体化N0-02采用规则，待集中冻结。所有“目标/新增”均不是现有权限或接口已经生效。

## 1. 主体与七类范围

| 入口/范围 | 服务端绑定及实时判断 |
|---|---|
| 登录人立即请求 | 从当前会话解析tenant/user及当前角色；按目标对象当前ACL绑定run，输入ID/句柄只供查找，不授权 |
| 业务事件 | 采用已批准订阅/服务策略的具名service principal与最小授权对象集；事件作者只留触发来源，不借其Role执行 |
| 定时任务 | 使用任务策略中明确的服务授权、生效范围和用途；执行/恢复时复检策略及主体有效性，不能用创建者的历史权限无限运行 |
| tenant/portfolio | 由当前权限解析显式项目/产品锚点集合；tenant相同不能推出可看全租户，计数/排序/摘要同样先鉴权 |
| market_space/product_line/opportunity/product_definition | 解析真实对象及父子关系、当前scope grant和资源版本；立项前不造Project；子对象有权不推出父域全部可见 |
| project | 复用实际Project及成员关系，项目角色NULL沿旧行为；非NULL取租户Role权限与项目限制交集。转换/迁入保持原来源、批准和唯一映射 |
| 委托 | 同时复检委托人与受托人当前有效授权/范围/期限；记录两者身份，权限取交集。专业persona、事件作者、模型句柄或旧缓存均不授权 |
| 具名专业工作项 | 被分派人只获得办理该项和读取获准输入的窄范围；不自动获得整个产品工作台或其他项目权限。接收/验证仍有独立责任规则 |

每个tool、model egress、disclosure、export、apply都重验当前ACL与来源派生链；冻结是授权上限，不延长已撤销权限。源对象失效/超用途时移除派生材料并重建或停止；新公开研究观察可在受权run追加，新增内部范围开关联run并继承lineage预算/截止时间。审批、会话票据、存储key、凭据与无关PII不入模型。

## 2. 角色、动作与作用域的具体映射

七个Role不变，专业职责不增加权限角色。下面是目标动作注册合同，不是直接扩张当前Role枚举或现有数据库授权。每次还须满足上述scope、当前状态和适用业务职责；有Role只是动作资格，不等于在任意对象有权。

| 动作族 | 角色候选 | 额外范围/事实限制 | 施工 |
|---|---|---|---|
| 当前finding.view/review/apply | 沿现有owner/admin/project_manager/engineer/quality | review固定载荷，apply是另一人工动作并重验类型/来源/目标/领域权限；同一人可办两个动作，不因此满足专业四眼规则 | N0-03 |
| 新product_management.view/edit | owner/admin/project_manager | 需要明确产品scope访问/编辑授权；不把所有租户项目成员映射为产品管理编辑者 | N1-01 |
| 新product_definition.publish | owner/admin/project_manager | 精确产品scope、发布条件及适用专业/商业批准；系统管理员身份不伪造专业批准 | N1-06/07 |
| 新scoped_work_item.view/execute | owner/admin/project_manager/engineer/quality | 指派/参与该工作项或具备scope管理授权；只读获准输入；完成不代接收 | N1-01/N3-04 |
| 新scoped_work_item.assign | owner/admin/project_manager | 目标scope的管理权限，合法接收方和职责；不能借分派扩大其全部ACL | N1-01 |
| 新review.professional.submit | owner/admin/project_manager/engineer/quality | 当轮具名席位、来源/政策版本、专业职责与适用独立性，不能把Role当专业资格 | N1-07/N4-06 |
| 新test_run.record/test_run.complete/report_import.confirm | owner/admin/project_manager/engineer/quality | 当前项目可达，Run/样机/用例同scope与版本，录入原始实绩/导入原值；Quality只新增这些窄权限，不获整套product_engineering.edit | N0-04 |
| baseline/commitment/resource/financial批准 | 现有角色中具备对应领域明确授权的具名人员 | 必需领域政策/金额阈值/责任待配置则不能正式批准；纯计算或比较不增加审批 | N2/N5/N6对应领域 |

[现有接线盘点](runtime-adoption-inventory.json)逐条给出9个真实人工动作的Action、候选Role、Python符号、实际API合同和文件摘要；其中逐次Run与导入当前仍用PRODUCT_ENGINEERING_EDIT，尚未获得目标窄权限。当前ProjectAccess支持代理成员可达，FindingService仍检查直接成员；N0-03统一为已批准的双方交集政策，不悄悄沿最宽实现。

## 3. 人审、硬闸及确定性路径

[能力矩阵](capability-policy-matrix.json)内14项业务硬闸逐项对应完整设计§2：Baseline、Commitment、Gate、DCP、TR、BOM Freeze、ECN、供应商选定、高/严重Issue关闭、真实外发/外部写、历史删除/覆盖、正式金额批准/承诺、产品定义发布、项目执行批准。不得由模型工具直接办理；按相应职责及适用四眼政策检查，不在每个子步骤重复加一层通用审批。

已有Finding的真实应用白名单只有RiskSuggestionPayload→Risk、KnowledgeDraftPayload→Memory、TestPlanChangePayload→TestPlan。新研究/机会/实验/策略/定义/初始计划/会议/变更/CAPA/交接/资源提案各用专业载荷和相应领域事务；未知类型拒绝，不把它压成Risk后宣称完成。N0-03提供可验证的类型适配注册接口，领域N项负责实际适配、原子性和效果。业务操作与Event/Audit同事务，幂等键+同载荷摘要复用，变化载荷冲突；应用成功和业务执行/接收完成另轴回链。

DecisionBrief只读时直接展示来源、共识、异议/代价、未决和建议；正式业务动作必须生成相应Finding，再接受/独立应用并经过适用领域硬闸。共识、模型confidence、会议结束或Brief生成都不是批准。

确定性规则候选、原值导入、计算、人工表单继续沿已批准路径。报告模型仅建议未知列映射，原始单元格由确定性解析保真，人工核对确切映射/预览后确认；已确认同指纹映射可零模型复用。reports.preview_import只读已授权批次，不能新建、确认或伪造实测值。当前原值导入的模型映射建议不得成为通用业务草稿直写出口。

## 4. 触发与预算时钟

| 策略 | 合并/优先级 | 对外时间要求 |
|---|---|---|
| user_request | 立即排队，interactive | ≤5秒可见排队/失能；执行受当前profile剩余额度和绝对截止约束，不等待15分钟事件窗口 |
| milestone | 0秒合并，milestone | 从触发起≤180秒产出结果/no_action或明确失能/失败；排队和执行一起计时，不能先等180秒再开始 |
| frequent_edit | 900秒合并，background | 适用于连续BOM/文档编辑；显式用户请求仍用立即策略 |
| scheduled | 到计划时间排队，background | 按任务策略到期，不借新run重置lineage预算和绝对期限 |
| control | 撤权/取消/策略失效立即优先处理 | 停新调用/披露/apply，释放安全可释放资源；错误清理零模型 |

盘点已给全部69个当前事件明确候选策略及理由：保留现有模型route/no-route集合，不以本轮登记新增模型触发；现有有路由的阶段/Gate/测试失败/Issue/供方延期/Complaint/NCR/变更采用milestone，BOM创建/条目与文档上传采用frequent_edit。用户/模型治理/委托撤销类控制按影响刷新授权；AI_FINDING_CREATED等未路由事件不形成自触发循环。新增领域事件随生产者/消费者所在N项新增版本化合同与负例。

当前dispatcher仍统一15分钟窗口、要求project_id；该事实已与目标区分。N0-03按具名策略接优先队列、scope/capability/事实版本去重、可见状态和停止原因；里程碑必要时取min(profile剩余活动额度, 180秒剩余时钟)并按时终止。明确失败是状态诚实，不是SLA成功；非故障超时仍记SLA失败。

每次调用原子预留tenant+lineage+attempt额度；工具/能力profile与run剩余额度取交集，不能借工具更大profile扩大运行。所有重试、席位、恢复/关联run同账本，等待人工释放worker，活动额度暂停但绝对时钟继续。实际已超预估的用量照实结算并阻止继续；响应未知保留预留待对账，不能记0或重发规避。

## 5. 组件采用与资格

盘点对13个旧key逐项核对实际prompt JSON版本、context/handler/model output Python符号和文件SHA-256；通用模型资格只含provider/model/suite，不能等同于新capability+schema+tool+context用途资格。源码存在不等于当前生产部署或该能力验收通过。

27项新语义各有具名context/prompt/model output/handler/quality suite的待实现项、复用旧key及所属N项；已有14工具和Brief的可执行DTO可复用，其他专业扩展在相应领域冻结。新能力默认disabled，只有字段/schema/prompt/handler、权限/来源/预算/停止/恢复、真实capability模型资格、领域回归及采用记录都就绪，才可按版本推进shadow/live。公共N0-03不等全部领域能力，不能为提前勾选而复制通用Risk输出或假golden。

已存在的Gate readiness、测试计划验证、原值映射三类确定性组件列出实际符号；排程/共享容量/齐套/成本/专业指标引擎保留对应N项。Engine不隐藏LLM，不以只读计算改正式Baseline/Commitment/容量预约；结果带真实算法/输入快照/单位/日历、缺项和计算上限，领域版本采用前补齐精确参数。

迁移与采用：新版本并存→真实来源/未知项回填→当前能力兼容验证→资格与采用记录→按能力启用。旧版本/历史Finding/run只读兼容，不批量改成新授权；disabled不影响已经合法应用的业务历史，但停用能力的待应用Finding须拒绝。v2新run沿N0-01批准规则继承lineage，不热换在途bundle。任何丢失审计/实绩的downgrade拒绝；运行失败退回兼容代码，未知费用和外部回执保留待对账。
