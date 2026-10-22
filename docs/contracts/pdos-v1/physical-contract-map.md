# N0-01 物理字段与兼容映射

生效版本：`1.0.0`，由用户批准draft.3内容冻结；见[冻结记录](freeze-record.md)。本文件与生成的OpenAPI字段合同、object-ownership字典一起评审。它是后续Alembic实现的映射合同，不注册SQLAlchemy业务metadata、不执行DDL。现有97表/11namespace不搬迁；迁移号在真正实施时重新检查head后分配。

## 存储约定

新业务表的`id/tenant_id`为UUID，`version`为正整数，时间为TIMESTAMPTZ，数值为明确精度NUMERIC，原值为TEXT；公用Quantity候选精度为(24,8)，具体领域需不同精度时以独立字段schema版本声明，不靠隐式四舍五入。现有表的真实类型优先兼容，不能把这些约定批量应用到旧表。

事件/审计是明确例外：现有`events.id`与`audit_log.id`为BIGINT，写入器返回整数行号；`events.event_id`是VARCHAR(128)，按source+event_id幂等。回执使用`event_row_ids/audit_row_ids`正整数，因果关联用`causation_event_row_id`，不迁移旧事件标识为UUID。SourceRef中kind=event使用已鉴权的内部行号；业务对象使用UUID。旧`{kind:event,reference:<external event id>}`需在当前tenant/project及source可判定范围解析后适配，歧义拒绝，不任选一行；这不修改旧引用正文。

所有正式关系使用tenant复合FK；项目内同时使用project，目标补必要复合唯一键。跨scope来源集合是冻结取证清单，不冒充正式关系FK；解析器按kind白名单加载当前对象/来源ACL。正式排程、选择的Solution、Case转换、Run配置等关键关系必须提取到可约束列/关系表，不能只放JSONB。

## 首批共同对象的列和约束

下列名称为候选物理名称，可通过一次明确的合同修订调整；不预占迁移编号。具体其余业务字段与required/nullable由OpenAPI对应模型逐字段消费。

| 合同模型 | 物理表/字段映射 | 数据库约束及写入守卫 |
|---|---|---|
| ProductNode | product.product_nodes：id/tenant/version/code/name/level/parent_id/lifecycle；region/channel关系；definition_id/version引用 | tenant+code唯一；parent复合FK；按level校验父级并检查环路；definition引用同tenant |
| MarketSpace/ResearchTask/DesiredOutcome | product.market_spaces/research_tasks/desired_outcomes；scope_kind/ref_id、owner、state、source快照；来源另有版本引用 | 真实scope注册对象存在/ACL；无虚拟Project；启动与完成guard按字段合同 |
| Opportunity/Solution/Experiment | product.opportunities/solution_candidates/experiments；outcome/parent、solution所属opportunity、selected_solution_id；VUVF维度、protocol版本和result另列 | (tenant,opportunity,solution)FK；selected必须属于本机会；Outcome树一致/无环；方案与实验结果分别留痕 |
| ProductStrategy/Definition/SpecItem | product.*_versions保存稳定logical_id+version及发布正文；definition_items按版本和item_key；状态/发布字段与有效性控制分开 | (tenant,logical_id,version)唯一；published写保护；条目跨版保持稳定key；旧Requirement/Case主关联不删，多对多另加关系表 |
| ScopedWorkItem | project.scoped_work_items：scope、action_type、owner/receiver、due、输入来源/输出/判据、state、证据及接收 | 当前必需责任与接收guard；project scope仍Task；用户引用tenant复合FK；旧Task.project_id继续非空 |
| WorkItemTransfer | project.work_item_transfers：operation、source_item_id/version、disposition、target_task_id、remaining_work、evidence | 来源唯一映射；已完成/取消只保留历史；迁移后源执行关闭入口与目标执行开启同事务，不能两边都活动 |
| DCP/TR | project.review_versions + review_rounds/result/validity；kind独立dcp/technical_review，source版本、policy、outcome | Meeting只是资料来源；Gate消费者复核当前有效结果/来源/轮次；冻结历史不回填 |
| CaseProjectConversion | 优先复用现有Case↔Project唯一关系；增project.case_project_conversions记录调用、版本和整数Event/Audit行号 | 同tenant、case唯一、project唯一；恢复重复返回相同项目；禁止重定向历史Finding |
| InitialPlanApplication | project.initial_plan_applications + node mappings；candidate_digest、conversion、execution_approval、baseline、receipt | 审阅/批准摘要一致；一个批准单元内Task/依赖/Baseline/映射/Event/Audit/receipt原子；失败保留approved未应用 |
| ProjectContractAdoption | project.project_contract_adoptions：contract/policy、现状快照、原status、保留批准、missing、state、remediation_receipt | (tenant,project,contract_version)唯一；只改兼容状态，不改Project七态；旧日期不能回填成获批基线 |
| ScheduleNode | project.schedule_nodes：task_id/gate_id/build_id/test_run_id/certification_id/tooling_id各可空，milestone无源 | CHECK恰一FK或milestone全空；各(tenant,project,target_id)复合FK；禁止events式自由entity/id充正式来源；tooling未实现前不接受正式tooling节点 |
| ScheduleDependency | project.schedule_dependencies：pred/succ节点、fs/ss/ff/sf、lag数值/单位、跨项目关系 | 两端同tenant，项目内FK及跨项目双方授权；写入时环路检查、并发串行化；影响/反馈引用不入执行图 |
| TimeRecord | project.schedule_baseline_versions/forecast_versions/commitment_versions/actual_versions + node_times；四类独立表，node缓存仅投影 | (tenant,project,logical_id,version)唯一；基线/承诺有审批，Forecast服务计算，Actual有原证据；更正新增版本；current pointer更新不覆盖正文 |
| WorkCalendar | project.work_calendar_versions：logical_id/version、timezone、weekday、holiday、工时；例外日历按后续N2字段扩展 | 发布版本不可覆盖；每条节点/容量绑定实际日历版本 |
| ResourceIdentity/Capacity/Reservation | project.resource_identities/capacity_versions/reservations；旧resources增量映射；calendar/capacity/version/window/unit及预约/释放receipt | 身份跨项目共享；(tenant,resource,version)；reserve锁当前容量、两侧授权与版本复核；proposal无正式占用；release幂等不双退 |
| SupplySnapshot | supplier.supply_snapshots：source/external_id/as_of/fresh_until/digest/quantity/unit；来源指针和授权捕获记录 | 源快照去重；unknown为NULL；Build分配另表约束不重复占用；不产生ERP写事务 |
| MetricsDocument | quality.test_runs保留metrics JSONB数组；增metrics_schema_version，稳定key/原值/规范值/单位/判据/规则/出处 | 不把数组变成对象；必要索引另加；旧未规范指标留legacy，不能编造转换或实测值 |
| SampleConfigurationRevision | product.sample_configuration_revisions：sample/revision及六项配置、source/digest/frozen_at；test_runs增configuration_revision_id | (tenant,project,sample,revision)唯一；Run到同样机revision复合FK；旧unknown有迁入标识，当前配置指针不能改旧Run含义 |
| ProjectRoleAssignment | project.project_members增nullable project_role；专业职责单独user/project responsibility记录及生效窗口 | 枚举复用现有Role；NULL保留旧行为；非NULL权限交集，委托也不扩双方实际权限；DQE/SQE/IE标签不授权 |
| VersionValidity | 首个产品消费者放product.*_validity_revisions；其他领域按所属表复用合同形状，不用通用自由多态FK替代领域关系 | 对冻结版本的tenant复合FK；control_revision单调且引用前版；replacement同逻辑对象且版本更高；按领域授权；只追加控制历史和更新current指针 |
| Authorization/Manifest/Observation/Compaction | ai.run_authorizations/context_manifests/run_observations/context_compactions，复用agent_runs/model_invocations；release、scope与来源索引 | run/revision、run/sequence唯一；冻结正文、同key同digest复用/异digest冲突；可信窄接口；当前ACL/lease每次复验 |
| RunControl/RuntimeReleaseBundle | ai.run_control/runtime_release_bundles + component pins；旧运行态兼容映射 | generation乐观锁/lease fence；wait持久checkpoint；lineage账本不重置；bundle不可在途热换；资格/golden只引用人工发布 |
| OperationReceipt | project.domain_operations及目标映射、Event/Audit行号；AI记录引用 | tenant+operation+幂等key唯一；不同digest冲突；event/audit同事务；应用状态和实际执行/接收独立 |

## 不可恢复历史与发布回退

1. 新建对象以新合同版本开始；旧对象保持已有状态与历史来源。缺字段只在明确适用的新动作入口校验，不能把旧active项目回退重新立项。
2. 发布正文只读，替代/撤回新增VersionValidity。来源无权/失效时先阻断依赖动作并重算；不能删旧批准或把“已发布”改回draft。
3. 本地旧Context v2在新适配中可读；无法恢复授权上限时为legacy_unknown，不伪造新的可执行授权。继续任务创建真正受权的新run，保留旧lineage关系与累计预算；不通过复用旧scope获得新权限。
4. 每次实际迁移按expand→有来源回填→兼容读取→完整性核验→收紧约束推进；downgrade若会丢正文/审计/实绩必须拒绝，使用兼容代码回退或新补偿迁移。失败原子性与受限账号正反例在实际实施的pdos_test环境验收。
5. N0-01冻结的是字段、归属、兼容及这些必需约束；不是声称FK/并发/角色边界已经部署或通过数据库验收。那些证据保留为所属N项实现验收。
