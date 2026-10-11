# 0418 品类生命周期计数权限只读复核

主线 s0_0418 是 root 报告的 head。本轮只读源码与已有证据，没有连接主库/私库、运行模型或重跑无变化测试。此前结果中的 0416 是当时检查点的报告，保持历史原文。完整小型 gate SQL、Category policy、触发器清单与源码哈希在 `0418-category-clock-source-audit.json`；它是本轮审计快照，不替代已冻结候选 manifest。

## 结论与触发条件

源码层面仍成立：`schema_s0_0001.py:4` 的 Category WITH CHECK 要求实际 owner_id=actor 且 actor=requester；`schema_s0_0407.py:3` 的 lifecycle_reference_gate 是 SECURITY INVOKER，NULL product 分支在实际 Category FOR UPDATE 与 lifecycle_objects pending/隔离守卫之后执行 Category.lifecycle_epoch + 1。0410 的 definer advance_change_dependency_clock 是另一个派生计数入口；到 0418 的现行源码没有改此 gate 或 Category policy。

- **已实际观察**：marked 私库 51698 的 0404–0409 公共 fixture，app 角色+实际 Agent writer/human requester+NULL product 的合成 Receipt，Category UPDATE 被 RLS 拒绝（42501），Call/Receipt 整 UOW 回滚。明确测试是 `postgres_execution_binding_cases.py:386`；过程报错是 `postgres-ports-candidate.log:10`，最终负例保留在 76 项。
- **当前主线可复现条件（静态推导，未实跑）**：非 owner 的 active human M、actual ordinary Grant can_write=true 且 NULL/未来 expiry、actor=requester=M，品类级新 evidence.artifact.register（product_id=NULL、正确 Category revision、新请求键/新语义、可创建 visibility）。category_scope 权限通过后，service.py:927 构造 Artifact，:1027 flush 的 artifact_versions lifecycle_reference 触发器先更新 Category clock，WITH CHECK owner!=M 拒绝；即使只写 Receipt，:412 flush 同样触发。负责人本人满足该 CHECK；产品范围走 Product 分支，与已通过的产品端口不冲突。
- **B7 Agent 条件**：实际 AgentRun/来源/技能/模型/当前资格接线之后，writer agent != category owner 且 actor!=requester 的 Category clock 同样会触发限制。当前 service.py:432/450 仍只认可旧 Run，AgentRun-only 新命令会更早被 FORBIDDEN_SCOPE 拒绝；不能宣称已跑到当前公共 Agent 的 Category UPDATE。
- 同请求/同意图原回执恢复在 service.py:763–807 已早退，不做新业务/clock 更新；维护修复不应改变当前读取足够的恢复规则。

## 建议由公共 owner 维护的最小入口

只给 **Category.lifecycle_epoch 派生计数的窄 trigger owner** 权限，保留 Category 普通业务 UPDATE RLS、owner/T1/T2 和所有原来源/pending/隔离检查。建议拆出与 advance_change_dependency_clock 同类的 clock-only SECURITY DEFINER trigger，固定 pg_catalog/public search_path；以实际 NEW/OLD 与受控 TG_TABLE_SCHEMA/TG_TABLE_NAME allowlist 得到 tenant/category/NULL product，核对实际精确 scope，仅增加该 Category.lifecycle_epoch。不得提供模型/HTTP 可调用的参数式维护入口，不授予 pdos_agent 直接 DML，不修改 owner/name/revision/status 等字段。

不要直接把整个 lifecycle_reference_gate 改为 definer：其中 lifecycle_objects 查询目前依赖 invoker RLS。它应继续做原 guard；clock-only trigger 在同 UOW 内完成派生维护，任何失败与领域对象/Receipt/Outbox/Call 一起回滚。保留 evidence.lifecycle.% 回执的当前排除与既有 clock 次数语义，避免重复增量。

当前 category_scope.py:35 仅 get Category，:42–57 lock=True 时锁 Principal/Grant；service.command_scope:215 对 CategoryScope.id=None 不锁 Category。B7 公共 adapter 在 M2 prepare 前要先获得实际领域 Category/Product 锁，再按 Run→Call（刷新 actual epoch）进入同一 Session，避免 clock trigger 到末尾才获取 Category 造成反序。prepare/finish 不独立 commit；root 最终资格与当前 route 仍由共同 owner 执行。

## 静态触发器清单

共 107 个当前静态 trigger，均为 lifecycle_reference、BEFORE INSERT OR DELETE OR UPDATE、FOR EACH ROW，来源 schema_s0_0001.py:4。0002 的 upgrade 删除 grants 上的该 trigger；版本文件中的 grants CREATE 只是 downgrade，未计入。没有从归档链计算有效清单。完整记录见 JSON。

action_receipts, actual_configurations, artifact_versions, bom_lines, bom_revisions, build_authorization_decisions, build_current_authorizations, build_current_execution_assessments, build_execution_assessments, build_lots, build_operational_current, build_operational_facts, build_readiness, build_starts, builds, capa_current_observations, capa_current_verification_rules, capa_named_verification_reviews, capa_observation_facts, capa_remediation_links, capa_verification_evidence, capa_verification_rule_facts, change_approval_records, change_graph_captures, change_implementation_captures, change_implementation_records, change_order_records, change_request_currents, change_request_versions, claim_consumptions, claims, controlled_change_coverage_currents, controlled_change_coverage_facts, controlled_change_policy_currents, controlled_change_policy_facts, controlled_change_selection_currents, controlled_change_selection_facts, cost_current_inputs, cost_estimates, cost_input_snapshots, cost_source_captures, definition_revisions, definition_sources, definition_specs, engineering_configurations, manufacturing_baseline_document_links, manufacturing_preparation_currents, manufacturing_preparation_versions, measurement_import_captures, operational_material_holds, operational_resource_occupancies, original_scan_requests, original_scan_results, original_security, parts, plan_proposals, plan_revisions, process_revisions, product_variants, professional_authority_current, professional_authority_facts, project_product_links, project_tasks, project_work_packages, projects, quality_current_issues, quality_current_policies, quality_event_failure_links, quality_failure_maps, quality_issue_versions, quality_policy_facts, runs, sample_allocations, sample_current_readiness, sample_readiness_facts, sample_run_usages, sample_units, sample_usage_sentinels, supply_current_snapshots, supply_kit_projections, supply_snapshots, supply_source_captures, task_dependencies, test_measurements, test_resource_current, test_resource_facts, test_resource_reservations, test_result_actions, test_result_projections, upload_attempts, uploaded_originals, variant_revisions, verification_actual_method_applicabilities, verification_actual_method_batches, verification_current_actual_methods, verification_current_formal_requests, verification_current_preparations, verification_current_runs, verification_formal_requests, verification_handoff_facts, verification_launch_facts, verification_method_applicabilities, verification_preparations, verification_run_identities, verification_run_versions, verification_window_proposals, work_requests

## 冻结证据核对与 B7 未决

`source-manifest.json` 的 34 个文件重新只读核验，hash_mismatches=[]，source_digest=`701785a12e32c159e212a944c1c51e1a968cbc32b8acbda6f1de2b7536638a62`。`final-private-candidate.log` 为 76 passed / 12.87s，准确分解 29 actual PostgreSQL + 47 pure；`graph-resume-pure.log` 另为 11 passed / 1.90s，并有 Ruff passed。不相加为一套，不替代此前 217 项或正式出口。

仍待 root B7：主库 0700–0716 汇合与公共 migration/metadata；真实 Context.agent_call_id/AgentRun/check_run/当前资格/route；受控注册 domain adapter 的同 Session Call+领域对象+Receipt+Outbox；已完成只读恢复与跨 Run 语义复用形式；HTTP→Temporal→注册图、真实 worker/配置/SecretPort/预算。公共整次撤回 owner 目前 Claim 与 original_id=NULL 的独立 Artifact；M3 G0 product_manager 消费属于 M3。真实模型调用保持 0，合成回复/资格/回执 fixture 不构成真实资格。
