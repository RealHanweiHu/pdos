# Sprint 3 Exit Gate 审计草案

日期：2026-08-12

状态：**尚未达到 Sprint 3 Exit**。S3-1～S3-6 与本地 S3-7 实现已具备可部署证据；同一项目的跨模块 NPI/ECN 连续验收已补齐。唯一 canonical 硬缺口仍是 S3-7 真实 CEHub 试点 dry-run、数据 Owner 抽查、apply 与幂等重放。

本文件是出口草案，不代表人工 Exit Gate 已确认，也不授权进入 Sprint 4。

## 审计依据与方法

- 唯一执行依据：`docs/design/2026-08-09-preview-execution-plan.md:120-132`。
- 项目级 DoD：同文件 `:32-41`，要求验收、失败测试、错误/越界路径、迁移/文档同步、运行时验证与回滚路径全部成立。
- 审计逐项比较“文档声称的边界”与“实际服务端 enforcement point”，不把 checkbox 或测试名称本身当作实现证据。

## Intended vs. Implemented

| 范围 | 文档意图 | 服务端/运行时实现证据 | 验收证据 | 结论 |
|---|---|---|---|---|
| S3-1 Specification / BOM | PDOS 只拥有 EBOM、Prototype、Cost；MBOM/Routing 只存 ERP 引用 | `server/app/api/product_engineering.py:150,197` 限定三类 BOM 与三类外部引用；`server/app/db/schema.py:770-950` 以 check/FK 固化类型与租户边界；写路径通过 `server/app/domain/product_engineering.py:448-740` 同事务记录 event/audit | `server/tests/test_product_engineering_api.py:153,284`；`tasks/todo.md` S3-1 真实 HTTP/浏览器证据 | 已匹配 |
| S3-2 Gate 硬闸 | 当前 Gate 未批准不得推进；审批事务内复核签核、风险、任务和确定性材料 | `server/app/domain/projects.py:637-717` 锁 Project、检查当前 Gate approved、仅允许下一 Stage；`server/app/domain/gates.py:507-733` 聚合 Task/Issue/Risk/检查项/NPI 阻塞；`:1287-1409` 在锁内复核 readiness 后原子写 Decision、Gate、Event/Audit | `server/tests/test_gate_api.py:245,503,563,619` | 已匹配 |
| S3-3 Build/Sample/Test/Certification | EVT/DVT/PVT 的批次、样机、测试和证书真值进入 Gate；TEST_FAILED 同事务发出 | `server/app/domain/npi_execution.py:430-480` 约束样机数量/同项目 Prototype BOM；`:825-885` 测试失败同事务写 `TEST_FAILED`；`:1004-1125` 建证与幂等到期扫描；Gate 聚合见 `server/app/domain/gates.py:574-705` | `server/tests/test_npi_execution_api.py:206,432` | 已匹配 |
| S3-4 ECR→ECN→Handoff | 四眼审批、EBOM 冻结、PVT Gate 批准后才 ready；S3 不写 queue 以后状态 | `server/app/domain/change_governance.py:382-449` 拒绝申请人自审；`:550-689` 只接受同项目 EBOM 并冻结快照；`:693-752` 仅当 PVT Gate approved 才 pending→ready | `server/tests/test_change_governance_api.py:221` | 已匹配 |
| S3-5 687 检查项 | 直接消费 JSON，绑定 Stage/isGate，硬闸项进入 Gate | `server/app/domain/deliverable_checks.py:20-88` 固化资产路径与 687 唯一数；`:287-306` 实例化 `isGate`；`:391-425` 硬闸不可 not-applicable；Gate 查询 `server/app/domain/gates.py:548-567` | `server/tests/test_deliverable_checks_api.py:158` | 已匹配 |
| S3-6 Gate/Document 前端 | 内部成员懒加载；外部成员零标签/零请求；异常优先且不泄露 object key | `web/src/components/projects/project-workspace.tsx:55-68,170-186,400-415` 角色与懒加载边界；`web/src/components/projects/project-workspace.test.tsx:366-415,622-639` 验证例外优先、错误态、无 object key 与外部零请求 | `tasks/todo.md` S3-6 桌面/移动/双主题真实浏览器证据 | 已匹配 |
| S3-7 迁移工具 | CEHub 五类数据只读导入、dry-run 0 写、稳定映射、幂等重放 | `server/app/migrations/cehub_v1.py:181-218` 强制独立 SELECT-only/default-read-only 账号；`:867-965` 阻断源漂移并生成 0 写计划；`:1503-1600` 以租户 advisory lock 原子 apply；migration `0020` 建审计/映射/外部文件引用表 | 合成源测试与生产 schema 升级已完成；真实试点尚未运行 | **未完成** |

## 跨模块 Sprint 3 验收

审计前，各模块分别有完整验收，但没有一条证据证明 canonical 所写的“**一个项目**走完 EVT→DVT→PVT 含硬闸拦截与一次 ECN”。这属于证据和集成覆盖缺口，不是可以用多个独立测试拼接替代的条件。

已新增 `server/tests/test_sprint3_acceptance.py:370`，在同一租户、同一 Project 上通过真实 FastAPI 路径完成：

1. EVT Gate 已签核但缺 completed Build 时返回 `GATE_NOT_READY`，明确包含 `build:evt:completed_missing`；
2. 创建 EVT Build/Sample/Test Plan/Test Case/approved Report 后批准 EVT Gate，推进 DVT；
3. 完成 DVT 同构 NPI 事实、批准 DVT Gate，推进 PVT；
4. 同一项目创建 ECR，申请人之外的 PM 审批，生成且批准恰好一个 ECN，冻结 EBOM；
5. PVT Gate 未批准时 Handoff ready 返回 `HANDOFF_PVT_GATE_REQUIRED`；完成 PVT 事实和 Gate 后 Handoff 进入 ready，再推进 MP；
6. 数据库终态复核三个 Gate 全 approved、一个 ECN、Handoff ready、当前 Stage=MP、`GATE_APPROVED` 恰好三条。

加入该测试、真实 CEHub URL 兼容回归及生产部署链契约后，全仓 `make check` 已从头通过：Web 99 tests、Server 274 tests，ESLint/Ruff/format、TypeScript、mypy 160 source files、Next.js production build 与 Python compile 全绿。

同一轮 intended-vs-implemented 审计还发现 canonical 冻结的 `scripts/deploy-ecs.sh` 尚未落库。现已补齐分阶段 preflight/build/deploy/status/rollback 入口：生产 deploy/rollback 使用与 git SHA 绑定的人工确认，migration 后强制重施加并验证 Agent 数据库最小权限，运行服务以 `--no-deps` 启动，回滚只切换已存在镜像且不执行旧迁移或数据库 downgrade。API 候选镜像完成真实非 root/内置安全 SQL/CLI smoke；该能力交付不构成当前生产应用部署授权。

审计进一步证明首次 apply 原先只绑定项目选择器，没有绑定数据 Owner 已审 dry-run 的源快照；源行若在签字与首次 apply 之间变化，旧 mapping 尚不存在，`SOURCE_CHANGED` 无法阻断。现生产 CLI 强制提供获批完整 `source_fingerprint`，二次确认口令绑定租户/fingerprint/有序项目范围；当前快照不一致时在目标写入前返回 `SOURCE_SNAPSHOT_NOT_APPROVED`。同一入口还在连接前验证批准 RDS/异库/独立角色/TLS+CA，迁移报告原子以 `0600` 落盘并拒绝 symlink。

发布链复核又发现仅以环境变量给镜像打 SHA tag，不能证明 ECS 工作目录和镜像内容来自该 commit。现只允许从 `HEAD` 生成并验证 Git bundle，ECS 在独立 bare repository 验证后 clone 到全新目录；部署入口要求完整 40 位 SHA，核对 Git HEAD 并拒绝除 `.env.production` 外的全部文件漂移。API/Web 镜像写入且复核同一 OCI revision；一次性旧镜像兼容回滚另绑定两个实际 image ID。迁移报告目录移出 release 工作树，两个候选镜像的 revision label 已真实 inspect，相关聚焦 24 tests 与全仓门禁均通过。

## 当前开放门禁

1. RDS 尚不存在符合“五表全读、五表零写、`default_transaction_read_only=on`”的 CEHub 登录角色；ECS 也未设置 `CEHUB_SOURCE_DATABASE_URL`。
2. 生产 PDOS schema 已是 `0020_cehub_migration_v1 (head)`，但真实 C4s（`zGpNH0Xq`）/S18-01（`aBnbEdQG`）尚未 dry-run 或写入。
3. 只读账号就绪后：先 dry-run 并由数据 Owner 核对五类计数/抽样；正式 apply 必须再次取得生产授权。
4. apply 后必须原参数重放，证明五类 `created_counts=0`、mapping/业务行不增长，并执行抽样 SQL。
5. 完成后才能勾选 canonical S3-7、提交正式 Sprint 3 Exit 报告，等待人工确认；在此之前不得进入 Sprint 4。

生产 schema 与真实源预检的详细证据见 `docs/reports/2026-08-12-s3-7-production-migration-preflight.md`。

真实源负向 smoke 已证明候选代码能处理现役 Prisma URL，并会在读取项目数据前拒绝可写账号；该结果不能替代独立只读账号的正式 dry-run。
