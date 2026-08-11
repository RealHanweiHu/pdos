# Current Work Queue

> 唯一当前指针：**S0-5 Event + Audit Skeleton。** S0-4 已由 7 角色全矩阵、migration 0002 往返、多租户对象权限与真实 HTTP 路径验收。
> 产品范围与完成状态以 `docs/design/2026-08-09-preview-execution-plan.md` 为准。

## Gate B0: Baseline Freeze

- [x] 设计结构审查完成
- [x] 执行流程与 S0-1 验收补齐
- [x] UI accepted→applied 双动作校准
- [x] Agent 控制面/执行面数据库角色校准
- [x] 文档交叉口径扫描
- [x] 人确认本次文档校准
- [x] 创建首次本地 commit（`d28d984`，未 push）

## Completed: S0-1 Scaffold

### S0-1a Root Contract

**Acceptance criteria**

- [x] 根目录给出单一的 setup/dev/test/lint/type/build 入口与版本约束
- [x] `.env.example` 能在无 LLM key 下支持 Sprint 0/1
- [x] 不提交真实密钥、构建产物或本地数据卷

**Verification**

- [x] 新环境按 README 能完成依赖准备
- [x] secret/config 扫描无真实值

**Dependencies:** Gate B0

**Estimated scope:** Medium

### S0-1b Server Health Slice

**Acceptance criteria**

- [x] FastAPI `/healthz` 返回稳定、可测试的健康响应
- [x] Python lint/type/test 命令可重复运行
- [x] Alembic 环境存在且只有一个 head（`0000_scaffold`）

**Verification**

- [x] 聚焦测试先失败后通过
- [x] server lint/type/test 全绿
- [x] 运行时请求 `/healthz` 成功

**Dependencies:** S0-1a

**Estimated scope:** Medium

### S0-1c Web Shell Slice

**Acceptance criteria**

- [x] Next.js App Router 空应用采用 Tailwind v4、shadcn/ui、Geist、Phosphor
- [x] 公司橙、8px 圆角与双主题 token 落到基础样式
- [x] 首页可运行且不提前实现 Sprint 1 业务页面

**Verification**

- [x] web test/lint/type/build 全绿
- [x] 亮/暗主题运行时 smoke 通过；320/768/1024/1440 无横向溢出，浏览器控制台零 warning/error

**Dependencies:** S0-1a

**Estimated scope:** Medium

### S0-1d Local Data Isolation Slice

**Acceptance criteria**

- [x] compose 启动 pgvector/pg16 与 MinIO
- [x] `pdos`、`pdos_test` 独立创建
- [x] 测试入口遇到非 `pdos_test` URL 直接拒绝

**Verification**

- [x] `pdos_test` 可执行 `alembic upgrade head`
- [x] 故意传入 `pdos` URL 的隔离测试失败关闭
- [x] MinIO healthcheck 通过并初始化私有 `pdos-files` 桶

**Dependencies:** S0-1a, S0-1b

**Estimated scope:** Medium

### S0-1e CI Gate

**Acceptance criteria**

- [x] CI 覆盖 web/server lint、type、test、build
- [x] CI 启动隔离测试库、验证 pgvector 并执行 migration smoke
- [x] 失败步骤有明确日志，不静默跳过

**Verification**

- [x] 本地等价验证命令全绿
- [x] CI 首次成功运行全绿（GitHub Actions run `31461239210`）

**Dependencies:** S0-1b, S0-1c, S0-1d

**Estimated scope:** Medium

## S0-1 Completion Gate

- [x] 唯一执行计划 S0-1 的全部验收条款满足
- [x] 项目级 Definition of Done 满足
- [x] 执行计划 S0-1 checkbox 更新为 `[x]`
- [x] 当前指针移动到 S0-2

## Completed: S0-2 Migration 0001

**Definition of Ready**

- [x] 规格出处：`PostgreSQL_Schema_Design.md`、`Workflow.md`、`System_of_Record_Matrix.md`
- [x] 依赖项：S0-1 已完成；Alembic 当前唯一 head 为 `0000_scaffold`
- [x] 迁移号冻结为 `0001`，仅在隔离的 `pdos_test` 中执行与验收

**Implementation slices**

- [x] S0-2a：创建 10 个冻结 namespace，并建立跨表通用主键、时间戳与租户归属约定
- [x] S0-2b：建立 `cehub_core` 的 Tenant/User/Customer 表、约束与索引
- [x] S0-2c：建立 `cehub_project` 的 Requirement/DevelopmentCase/Project/Workflow/Stage/Gate 表与状态约束
- [x] S0-2d：建立 `cehub_project` 的 Task/Issue/Risk/Decision 表、关系约束与查询索引
- [x] S0-2e：补齐迁移正反向、单 head、实体清单、租户外键与开发/测试库隔离验收

**Acceptance evidence required**

- [x] `pdos_test` 从空库升级到 `0001`，10 schema 与 13 张首批实体表精确存在
- [x] 状态、唯一性、租户归属与跨实体引用约束的正反例测试通过
- [x] downgrade→upgrade 往返后仍保持单一 Alembic head，完整门禁全绿

## Completed: S0-3 Auth + Tenant Resolution

**Definition of Ready**

- [x] 规格出处：`RBAC_and_Audit.md` 与 canonical S0-3
- [x] 依赖项：S0-2 User/Tenant 表及 composite tenant FK 已完成
- [x] 范围冻结：本地密码、JWT、一次性 `/api/setup`、fail-close 租户上下文

**Implementation slices**

- [x] S0-3a：建立密码哈希、JWT claim/时效与认证配置契约
- [x] S0-3b：实现一次性 `/api/setup`，原子创建首个 Tenant 与初始化管理员账号
- [x] S0-3c：实现本地账号登录、签发 JWT 与当前用户读取端点
- [x] S0-3d：实现 fail-close 租户解析；缺失、失效或无租户归属一律拒绝
- [x] S0-3e：覆盖 setup 竞态、错误密码、伪造/过期 token 与租户上下文正反例

**Acceptance evidence required**

- [x] 空库只能成功 setup 一次，并可使用创建的初始化管理员登录
- [x] 有效 token 可解析唯一 tenant/user；所有无效上下文返回稳定 401/403
- [x] 聚焦测试、完整门禁与真实 HTTP 认证路径全绿

## Completed: S0-4 RBAC 7 Roles

**Definition of Ready**

- [x] 规格出处：`RBAC_and_Audit.md` 与 canonical S0-4
- [x] 依赖项：S0-3 已提供 fail-close 的 tenant/user 认证上下文
- [x] 范围冻结：7 个固定角色、项目成员关系、服务端角色矩阵、外部角色最小可见面

**Implementation slices**

- [x] S0-4a：定义 7 个冻结角色及租户级角色归属，初始化管理员授予 Owner
- [x] S0-4b：增加 tenant-safe 项目成员表与 migration 0002，保持 Alembic 单 head/无 drift
- [x] S0-4c：建立服务端权限动作目录与角色矩阵，默认拒绝未登记动作
- [x] S0-4d：实现 tenant + project 对象权限依赖，非项目成员与跨租户请求 fail-close
- [x] S0-4e：覆盖 7 角色矩阵、Supplier/Customer 最小可见面和多租户隔离正反例

**Acceptance evidence required**

- [x] 7 个角色对全部冻结动作的 allow/deny 矩阵测试通过，未知动作默认拒绝
- [x] 项目成员只能访问本租户授权项目；跨租户与非成员请求稳定拒绝
- [x] migration 0002 往返、聚焦测试、完整门禁与真实 HTTP 权限路径全绿

## Next: S0-5 Event + Audit Skeleton

**Definition of Ready**

- [x] 规格出处：`Event_Catalog.md`、`RBAC_and_Audit.md` 与 canonical S0-5
- [x] 依赖项：S0-2 业务实体、S0-3 actor/tenant 上下文与 S0-4 权限边界已完成
- [x] 范围冻结：events、audit_log、规格 10 类事件注册表、业务写与事件同事务

**Implementation slices**

- [ ] S0-5a：增加 `cehub_event.events` 与 `cehub_audit.audit_log` 的 tenant-safe migration 0003
- [ ] S0-5b：建立版本化事件注册表，登记规格 10 类事件的 schema、生产者、消费者与幂等规则
- [ ] S0-5c：建立业务写 + event + audit 的同事务写入端口，服务端绑定 tenant/actor
- [ ] S0-5d：将 Sprint 0 已有写路径接入事件与审计，并保持敏感字段不进入 payload
- [ ] S0-5e：覆盖重复 event、事务回滚、跨租户引用、审计不可变与迁移 drift 正反例

**Acceptance evidence required**

- [ ] `(source, event_id)` 重复写被数据库拒绝；规格 10 类事件注册表完整且版本固定
- [ ] 任一已实现业务写路径均同事务落 event + audit；失败时三者一并回滚
- [ ] migration 0003 往返、聚焦测试、完整门禁与真实 HTTP 审计路径全绿
