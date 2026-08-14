# Sprint 5 Exit 与全量切换发布候选报告

日期：2026-08-13
结论：**生产写冻结与 dry-run 证据有效，但 release `2ccefa1d2fe6567be4af8370b67aed9164aadd1d` 因 CEHub 导入 Project API 500 已失效；生产切换为 NO-GO，必须先合并修复并用新 release 重跑 verify/dry-run。**

## 1. 已完成范围

- S5-2：冻结 EBOM 的 ERP handoff 执行体、durable outbox、人工交付/对账/重放；ERP API 未冻结时明确降级，不发生自由外部调用。
- S5-3：认证外部 Event→CRM Requirement draft→独立人审；Supplier/Cost/Resource 收尾，26 个业务/AI 实体落库。
- S5-4：Supplier / Executive Intelligence 的版本化静态 prompt、确定性路由/预检、受限数据库投影与 Finding 人审链。
- 切换资产：CEHub 全部项目（含 archived）的只读 inventory capture/verify、双 fingerprint 批准、全量 dry-run/apply/replay、主入口、只读归档、观察和前向回滚契约。

S5-1 真实 DingTalk password-free login、群通知、审批和 card smoke 按人的指令延期。canonical checkbox 保持未勾选，生产必须继续 `PDOS_DINGTALK_DELIVERY_ENABLED=false`；本报告不把延期例外伪记为通过。

## 2. 最终审查修复

- 修复跨 Issue/Risk/Task 聚合的多表笛卡尔乘积，改为相关子查询，精确验证 2/3/4 条计数。
- `SUPPLIER_DELAY_REPORTED` 在写 Event/Audit 前确定性验证同租户 active Supplier、canonical UUID/ISO date 与严格延期关系。
- migration `0029_crm_entities` 在 CRM/Supplier/Cost/Resource 任一表有数据时拒绝有损 downgrade。
- 全量切换不再把当前已知 4 个未归档项目当作完整范围；生产只读盘点覆盖全部历史项目，Data Owner 先批准 inventory fingerprint，再批准五类内容 source fingerprint。
- 操作手册固定成功迁移不自动删除、不事故 downgrade；应用回滚保持 schema 前向，CEHub 写权限恢复需要新的生产授权。

## 3. 质量门禁

- Server：388 tests passed，全部数据库测试显式连接本机隔离 `pdos_test`（57432）。
- Python：Ruff check、246 files format check、严格 mypy 213 source files、compileall 全绿。
- Web：37 files / 126 tests，ESLint、Next typegen、TypeScript 全绿。
- Next.js webpack production build：33 个页面生成成功。默认 Turbopack 在当前受限运行环境因内部构建进程尝试绑定端口失败；webpack 复验没有源码或类型错误。
- 依赖：916 个锁定 registry 版本通过官方 OSV 两批审计，0 known vulnerabilities。
- Git：`git diff --check` 通过；用户原有 `.env.example`、`.env.production.example` 与 `server/tests/test_root_contract.py` 模型目录改动不属于本候选，不应混入 Sprint 5 提交。

## 4. 生产 Gate 状态

1. [x] PR #4 合并后的最终 release `2ccefa1d2fe6567be4af8370b67aed9164aadd1d` 已在 ECS 构建候选镜像并完成 CEHub 全量只读 inventory capture；未部署、未迁移、未写目标库。完整证据见 `docs/reports/2026-08-13-sprint-5-production-inventory-capture.md`。
2. [x] Data Owner 已批准 inventory fingerprint `a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d` 与有序全量项目 `WqWcl0wK,aBnbEdQG,xY8-PGbc,zGpNH0Xq`，并绑定目标 tenant `e340c240-d8f0-429c-aac5-69ab9b42fac5`、actor `4bdba865-c5b1-4ca1-aa85-be467e1fad42`。
3. [x] CEHub 写冻结、inventory verify 与完整 dry-run 已获批并完成；旧应用真实新连接读取可用、永久表零行写探针被 PostgreSQL `25006` 拒绝，dry-run `target_writes=0`，目标 11 表前后 count/内容 SHA-256 完全相同。证据见 `docs/reports/2026-08-13-sprint-5-production-full-dry-run.md`。
4. [x] 候选 `status` 的有界日志门禁发现真实 `/api/projects` 500；根因为迁移项目合法 `development_case_id=NULL` 与读模型冲突。`2cce...` 已失效且从未部署，证据见 `docs/reports/2026-08-13-sprint-5-project-api-release-blocker.md`。
5. [ ] 获得独立生产授权，临时静默旧 CEHub scheduled scanner，并观察至少 35 分钟确认读取可用、数据库仍只读且 scanner/read-only/`25006` 日志为 0。
6. [ ] 合并修复形成新 release，在 ECS 重建并重新执行 inventory verify、完整 dry-run 与目标零变化快照。
7. [ ] Data Owner 绑定新 release，批准重跑后的 source fingerprint 与五类 count/预测 created/skipped。
8. [ ] 分别获得新 release 部署与生产 apply 授权，升级 0028～0030、apply、幂等重放并抽查五类数据。
9. [ ] 业务 Owner 宣布 `pdos.beepump.net` 为主入口，验证 CEHub 只读审计归档并观察至少 30 分钟。
10. [ ] 人工确认 Sprint 5 Exit Gate 与切换退役；S5-1 延期风险继续独立跟踪。

证据分支 `codex/sprint-5-cutover-evidence` 最终 head `7fe20cb` 已通过 GitHub 完整 Quality/migration 门禁（7m22s），PR #5 以 merge commit `499db37f8d696edbf19c00111b29803912194dda` 合并；这项代码库状态不替代以上任何生产或人工 Gate。

运行时严格使用 `docs/runbooks/sprint-5-cutover-and-retirement.md`。以上任何生产项未完成前，不得把全项目目标、Sprint 5 Exit 或退役标记为完成。
