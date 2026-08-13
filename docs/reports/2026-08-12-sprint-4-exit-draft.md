# Sprint 4 Exit Gate 审计报告

日期：2026-08-12

状态：**Ready for human approval。** S4-1～S4-4 canonical 工作项、Sprint 4 纵向验收、完整质量门禁与本地运行时复核均已完成。根据执行纪律，本报告不自行批准出口；人工明确确认前不进入 Sprint 5，也不执行生产迁移、部署或外部系统变更。

## 审计依据

- 唯一执行依据：`docs/design/2026-08-09-preview-execution-plan.md` 的 Sprint 4 与项目级 DoD。
- 产品真值：`docs/specs/cehub-v3.2-preview/` 的 Quality、Memory、Agent、Event 与 SoR 边界。
- 永久安全红线：Agent 唯一写出口是 Finding；Accept/Reject 与 Apply 是两次人工动作；租户/项目范围由服务端绑定；`pdos_agent` 对业务表零写。
- 本次逐项比较产品意图、服务端 enforcement point、数据库权限和真实运行证据；checkbox 本身不作为实现证据。

## Intended vs. Implemented

| 范围 | 计划意图 | 已实现边界 | 验收结论 |
|---|---|---|---|
| S4-1 CAPA | Complaint→NCR→RCA→纠正/预防→有效性复核；质量 Owner 共同定义 | migration `0021_quality_capa` 建五张质量表；服务端状态机、复合外键、四眼、冻结有效性计划、ineffective 回流及同事务 Event/Audit 完整落地 | 已匹配；质量 Owner 已确认推荐 CAPA 契约，真实 HTTP/浏览器与 `pdos_agent` 零写测试通过 |
| S4-2 Memory | draft→verified→archived；仅 verified 进入检索与 AI；embedding 可替换 | migration `0022/0023`、状态机/四眼、当前内容哈希与 provider/model/dimension 绑定、verified-only security projection、Knowledge Search 和 Chat citation 已落地 | 已匹配；draft 0 命中→他人 Verify→命中→Archive 后 0 命中，并完成 CAPA→Memory→Chat 纵向验收 |
| S4-3 Phase 2 Agent | Engineering/Quality 只提供 BOM/变更与 Test/Complaint/CAPA 建议 | migration `0024`、静态 prompt、确定性路由、lease-bound 工程/质量投影与四种 risk-shaped Finding；Apply 只创建 Risk，不修改工程/质量 SoR | 已匹配；四类型 pending→accepted→applied、独立 Risk/Event/Audit 与真实受限 runtime 全绿 |
| S4-4 Context Builder | Multimodal 文档抽取产物 + User 角色视角接入 | migration `0025` 和 `run-context-v2`；trigger-bound internal/extracted 文档、确定性限额、无 PII 角色聚合、模型白名单投影与受限角色投影 | 已匹配；internal 进入模型，restricted/confidential/OCR/object key/PII/跨项目 0 穿透，四角色视角全绿 |

## Sprint 4 纵向验收

Sprint 4 的 canonical 出口要求已由同一条质量知识链证明，而不是把互不关联的模块测试拼接为结果：

1. Complaint 创建并 triage 为 NCR；
2. NCR 完成 containment、不可变 RCA 版本和独立 Quality 审批；
3. Corrective/Preventive Action 完成 evidence，冻结有效性计划；
4. 与前序责任人不同的 Quality reviewer 判定 effective，NCR 与 Complaint 关闭；
5. 关闭 NCR 生成 `knowledge_draft` Finding；人工 Accept 后第二次 Apply 创建 Memory draft；
6. 不同用户 Verify，verified Memory 才进入检索；
7. `/api/ai/chat` 命中该 Memory 并返回可追溯 citation；draft/archived、跨租户、跨项目均不命中。

这条链的领域/API 证据位于 `server/tests/test_quality_capa_api.py`、`server/tests/test_memory_api.py` 与 `server/tests/test_ai_api.py`；S4-2 完成记录固化了真实浏览器的 Verify/Search/Archive 行为。

## Context Builder v2 运行时证据

- 真实 `pdos_agent` 受限账号执行四组参数化 runtime：Project Intelligence=`project_manager`、Knowledge Lite=`engineer`、Engineering=`engineer`、Quality=`quality`。
- 每组均完成 lease claim→security-barrier projection→Context Builder→Structured Model Gateway→pending Finding→model invocation trace；四组全部通过。
- `DOCUMENT_UPLOADED` run 中 internal/extracted 片段进入模型；restricted 文本、对象键、上传人 PII、另一租户 Memory 与未列字段均未进入 provider messages。
- owner 与 restricted builder 共用 `run-context-v2` 严格 schema；run 原子保存 `context_version=run-context-v2` 与 schema version 2。
- migration `0025→0024→0025` 往返通过；存在 v2 持久化 run 时 downgrade fail-close，防止静默丢层；本地 `pdos_test` 最终版本为 `0025_context_builder_v2`。

## 真实 HTTP / 浏览器复核

隔离环境显式绑定当前 PDOS compose 的 `pdos_test`，没有连接开发或生产数据库：

1. Owner 经 setup/login 建立验收项目；
2. 通过真实 `/api/ai/analyze-document` 分别上传 internal 与 restricted XLSX，均返回 HTTP 201 且 `extraction_status=extracted`；
3. Project Workspace 文档页显示两份文档的 filename/classification/size/status，并明确不显示对象存储键；
4. 事件调试页以 project ID + `DOCUMENT_UPLOADED` 筛选，精确显示两条不可变事件和 `agent_dispatcher` consumer；
5. 页面文本不含对象键或 restricted 原文；Chromium console 为 0 warning / 0 error；
6. 浏览器会话、临时 API/Web、验收租户数据与临时脚本均已清理。

## 完整质量门禁

- Server：324 tests 全绿；Ruff、format、mypy（97 source files）、Python compile 全绿。
- Web：32 files / 111 tests 全绿；ESLint、TypeScript、webpack production build 全绿。
- S4-4 聚焦：Context Builder、projection、runtime contract、dispatcher/executor、migration/security 共 62 项全绿；真实受限四角色 runtime 复验为 4/4 通过。
- Alembic：本地 `pdos_test` 唯一版本 `0025_context_builder_v2`。
- 默认 Turbopack production build 仅因沙箱禁止内部端口绑定而失败；相同源码的 webpack production build 完整成功，没有放宽运行或生产安全配置。

## 安全与回滚

- 新增表/视图未扩大 Agent 业务写权限；`pdos_agent` 对 User、Project Member、Document 业务表仍不可直接读取敏感列，对所有业务表零写。
- Multimodal 只接受当前 run 的 trigger-bound 文档；classification/extraction/project/tenant 由数据库真值判定，模型参数无政策权威。
- User Context 只有静态 Agent role lens、人工决策约束和 active project role count，不包含 user ID、username、display name、email 或个人偏好。
- 结构化 context 继续追加在冻结 system prompt/tool 定义之后；Phase 1/2 prompt 与工具前缀未重排。
- migration `0025` 的 downgrade 只在没有持久化 v2 run 时允许；线上回滚策略仍是应用镜像前滚/切换，不执行破坏性的生产数据库 downgrade。

## 生产状态

本轮没有执行生产部署、生产 migration 或 ECS/Nginx/DNS 变更。生产环境是否应用 Sprint 4 的 migration `0021`～`0025`、安全 SQL 与新镜像，需要在 Sprint 4 Exit Gate 通过后另行获得明确生产授权并按部署运行手册执行。

## Exit 决议请求

本报告建议：**通过 Sprint 4 Exit Gate，并把唯一执行指针移动到 S5-1 钉钉连接器。**

当前仍停在人工 Gate。只有收到明确的“确认 Sprint 4 Exit Gate，进入 Sprint 5”后，才会启动 S5-1；该确认本身也不自动授权任何生产或外部系统变更。
