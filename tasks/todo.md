# Current Work Queue

> 唯一当前指针：**Sprint 2 Exit Gate。** S2-1 至 S2-7 已完成；正在执行完整质量门禁与验收汇报，随后必须等待人选择试点项目并明确确认，才能进入 Sprint 3。
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

## Completed: S0-5 Event + Audit Skeleton

**Definition of Ready**

- [x] 规格出处：`Event_Catalog.md`、`RBAC_and_Audit.md` 与 canonical S0-5
- [x] 依赖项：S0-2 业务实体、S0-3 actor/tenant 上下文与 S0-4 权限边界已完成
- [x] 范围冻结：events、audit_log、规格 10 类事件注册表、业务写与事件同事务

**Implementation slices**

- [x] S0-5a：增加 `cehub_event.events` 与 `cehub_audit.audit_log` 的 tenant-safe migration 0003
- [x] S0-5b：建立版本化事件注册表，登记规格 10 类事件的 schema、生产者、消费者与幂等规则
- [x] S0-5c：建立业务写 + event + audit 的同事务写入端口，服务端绑定 tenant/actor
- [x] S0-5d：将 Sprint 0 已有写路径接入事件与审计，并保持敏感字段不进入 payload
- [x] S0-5e：覆盖重复 event、事务回滚、跨租户引用、审计不可变与迁移 drift 正反例

**Acceptance evidence required**

- [x] `(source, event_id)` 重复写被数据库拒绝；规格 10 类事件注册表完整且版本固定
- [x] 任一已实现业务写路径均同事务落 event + audit；失败时三者一并回滚
- [x] migration 0003 往返、聚焦测试、完整门禁与真实 HTTP 审计路径全绿

## Next: Sprint 0 Exit Gate

**Local implementation and verification**

- [x] 按 UI 基线实现首次 setup 与账号密码登录页，双主题、键盘操作和错误态可用
- [x] 浏览器经同源 API 边界完成 setup/login/me，JWT 不进入服务端日志或页面可见输出
- [x] 多租户项目不可见、7 角色矩阵、写路径 event+audit 的 Sprint 0 汇总证据全绿
- [x] web/API 非 root 生产镜像、migration→API→web compose 顺序及回滚运行手册可执行
- [x] 登录限流、安全响应头、私有首次 setup 顺序与生产容器 smoke 通过

**Local evidence (2026-08-11)**

- `make verify-sprint-0`：82 个 server tests、15 个 web tests、lint/type/build、migration head、真实 web/API/BFF smoke 与生产容器 smoke 全绿
- Playwright 真实浏览器：setup→me→首页、错误密码、login→me→首页均已验证；明暗主题刷新零 hydration/console error，键盘顺序与 320/768/1440px 布局通过
- 生产制品：migration→API healthy→web healthy；仅 web 绑定宿主机回环端口，API/web 分别以 UID 10001/1001 运行；pnpm/uv 生产依赖审计均无已知漏洞
- 本地截图：`output/playwright/login-768-light-final.png`、`output/playwright/login-1440-dark-final.png`（验证产物按 `.gitignore` 不入库）

**Human-authorized environment gate**

- [x] 经人授权完成 RDS `pdos`/`pdos_app` 与 pgvector 验证、私有 OSS 桶及最小权限凭据、生产 migration、ECS API/web healthy 和回环端口登录页 smoke
- [x] 人通过私有 SSH 隧道完成唯一一次 setup；已验证 tenant/user/Owner、`TENANT_BOOTSTRAPPED` 事件和审计各一条，`needs_setup: false`，随后关闭隧道
- [x] 人确认采用现有 Nginx + `pdos.beepump.net`；已接入 `pdos_default`、签发并验证证书/续期、启用 HTTPS 反代与登录限流，公网登录页 200、错误凭据 401，既有站点回归正常
- [x] 修复 ERP/CRM 共享 `web` 别名导致的偶发误路由；最终 Nginx 配置上线后连续观察 30 分钟，API/web/Nginx 异常计数均为 0，服务重启计数为 0
- [x] 由人使用生产账号完成公网 login→me→首页 smoke；访问日志已核对 login 200 / me 200，登录后服务健康、零重启且最近 10 分钟无 PDOS 5xx
- [x] 汇报 Sprint 0 验收结果并获得人明确确认，进入 Sprint 1

## Completed: S1-1 Requirement Pool

**Definition of Ready**

- [x] 规格出处：`PostgreSQL_Schema_Design.md`、`Product_Flow.md`、`Event_Catalog.md`、`RBAC_and_Audit.md` 与 canonical S1-1
- [x] 依赖项：Sprint 0 出口已确认；Requirement/Customer 基础表、租户认证、RBAC 与同事务 event+audit 端口已就绪
- [x] 范围冻结：需求录入、列表/详情、编辑、可选 Customer 关联，以及版本化 REQUIREMENT 事件；不提前实现 Requirement→Case 转化
- [x] 迁移号预留为 `0004`，单调递增且不复用

**Implementation slices**

- [x] S1-1a：冻结 Requirement/Customer 数据约束与 tenant-safe migration 0004
- [x] S1-1b：实现需求创建、读取与编辑 API，服务端绑定 tenant/actor，跨租户 fail-close
- [x] S1-1c：登记 REQUIREMENT_CREATED / REQUIREMENT_UPDATED 事件，并让写路径同事务写 event + audit
- [x] S1-1d：实现需求池 UI 与同源 BFF，覆盖录入、编辑、Customer 关联、空态/错误态和键盘路径
- [x] S1-1e：完成聚焦测试、完整门禁、真实 API/浏览器 smoke 与迁移往返验证

**Acceptance evidence required**

- [x] 同一租户可录入、查看和编辑需求，可关联本租户 Customer；Customer 可为空
- [x] 跨租户 Requirement/Customer 不可见、不可关联、不可编辑，未知对象稳定返回 404
- [x] 创建和编辑分别同事务落版本化 REQUIREMENT event 与不可变 audit，失败时全部回滚
- [x] 需求池按最新更新时间稳定排序，页面在双主题和 320/768/1440px 下可用且控制台无 warning/error

**Acceptance evidence (2026-08-11)**

- `make check`：server/web 测试套件、Ruff/ESLint、Python/TypeScript 严格类型检查和生产构建全绿；Alembic `0004` 保持唯一 head，迁移往返测试通过
- 隔离真实 HTTP/浏览器：owner 登录后完成需求创建、关联本租户 Customer、编辑标题/状态；同源 BFF 的 GET/POST/PATCH 分别返回 200/201/200，PATCH 仅发送发生变化的字段
- 数据库证据：同一需求产生 `REQUIREMENT_CREATED`、`REQUIREMENT_UPDATED` 两个 v1 event，以及带正确前后快照的不可变 create/update audit
- Playwright：空态、错误重试、只读角色、键盘路径、明暗主题及 320/768/1440px 均通过；320px 无横向溢出且交互目标至少 44px，控制台 0 warning/0 error
- 本地截图：`output/playwright/s1-requirements-empty-light.png`、`s1-requirements-populated-dark.png`、`s1-requirements-mobile-dark.png`、`s1-requirements-tablet-light.png`（验证产物按 `.gitignore` 不入库）

## Completed: S1-2 Development Case + Conversion

**Definition of Ready**

- [x] 规格出处：`PostgreSQL_Schema_Design.md`、`System_of_Record_Matrix.md` 与 canonical S1-2
- [x] 依赖项：S1-1 已完成；Requirement、DevelopmentCase、Decision 基础表与同事务 event+audit 端口已就绪
- [x] 范围冻结：一条已批准 Requirement 只能执行一次正式转化；同事务创建 draft Case、创建 conversion Decision 并把 Requirement 标记为 converted
- [x] Case 状态机冻结：`draft → evaluating → approved → converted`，`evaluating → rejected`；converted/rejected 为终态，转 converted 必须已有同租户 Project 引用
- [x] 迁移号预留为 `0005`，将历史 `proposed` Case 状态单向映射为 `evaluating`，迁移号不复用

**Implementation slices**

- [x] S1-2a：migration 0005 对齐 Case 状态、非空/JSON/一需求一 Case 约束与更新时间索引
- [x] S1-2b：实现正式 Requirement→Case 转化服务/API，原子写 Case、Decision、Requirement 及各自 event+audit
- [x] S1-2c：实现 Case 列表/详情/编辑与状态迁移，非法跃迁和跨租户对象 fail-close
- [x] S1-2d：实现同源 BFF、需求转化入口与 Case 工作页，覆盖空态/错误态/只读角色/双主题响应式
- [x] S1-2e：完成聚焦测试、完整门禁、迁移往返及真实 API/浏览器验收

**Acceptance evidence required**

- [x] 已批准 Requirement 可且仅可转化一次；转化结果同时包含 draft Case 与 conversion Decision，Requirement 变为 converted
- [x] 任一转化写入失败时 Requirement/Case/Decision/event/audit 全部回滚；跨租户与未知对象返回一致 404
- [x] Case 只允许冻结状态边迁移；approved→converted 必须已有 Project，终态不可再编辑
- [x] owner/admin/PM 可转化和编辑，Engineer/Quality 只读，Supplier/Customer 无入口
- [x] Case 页面在双主题和 320/768/1440px 下可用，控制台无 warning/error

**Acceptance evidence (2026-08-11)**

- `make check`：95 个 server tests、44 个 web tests、Ruff/ESLint、Python/TypeScript 严格类型检查和生产构建全绿；migration `0005` 往返与唯一 Alembic head 测试通过
- 隔离真实 HTTP/浏览器：Owner 创建并批准 Requirement 后完成一次性转化；POST 返回 201 并导航至 Case 工作页，Case 最小 PATCH 仅发送 `title`
- 数据库证据：Requirement 为 `converted`、Case 为 `approved`、conversion Decision 恰好 1 条；转化与两次状态迁移分别产生完整 event+audit，事务回滚、重复转化与跨租户正反例测试通过
- Playwright：Case 编辑及 `draft → evaluating → approved` 显式迁移通过；明暗主题和 320/768/1440px 无横向溢出，移动端主要控件至少 44px，控制台 0 warning/0 error
- 本地截图：`output/playwright/s1-2-cases-light-1440.png`、`s1-2-cases-dark-1440.png`、`s1-2-cases-dark-768.png`、`s1-2-cases-dark-320.png`（验证产物按 `.gitignore` 不入库）

## Completed: S1-3 Project + Workflow/Stage Instantiation

**Definition of Ready**

- [x] 规格出处：`Workflow.md`、`PostgreSQL_Schema_Design.md`、`Product_Flow.md`、`API_Design.md`、`RBAC_and_Audit.md`、`System_of_Record_Matrix.md` 与 canonical S1-3
- [x] 依赖项：S1-2 已完成；approved Development Case、Project/Workflow/Stage 基础表、项目对象权限与同事务 event+audit 端口已就绪
- [x] 项目状态图冻结：`draft → proposed → approved → active → completed → archived`，另有 `active → on_hold → active`；archived 为终态
- [x] 实例化边界冻结：版本化 NPD 模板由服务端定义；创建 Project 时为该项目创建独占 Workflow 实体及 P1 Concept、P2 Planning、P3 Design、P4 EVT、P5 DVT、P6 PVT、P7 MP 七个有序 Stage 实例
- [x] 正式动作冻结：一个 approved Case 只能创建一个 Project；同事务创建 Workflow/Stages/Project、把创建者加入项目、把 Case 标记 converted，并写 event+audit
- [x] 对象权限冻结：Owner/Admin 全租户可见；PM/Engineer/Quality/Supplier/Customer 仅见项目成员范围；仅 Owner/Admin/PM 可创建、编辑、迁移状态或推进相邻 Stage
- [x] 迁移号预留为 `0006`，增加一 Case 一 Project、一 Workflow 一 Project、非空与稳定排序约束，迁移号不复用

**Implementation slices**

- [x] S1-3a：migration 0006 冻结 Project/Workflow/Stage 实例约束、唯一性与查询索引
- [x] S1-3b：实现版本化 NPD Workflow 模板与 Case→Project 原子实例化服务，接通 PROJECT/CASE event+audit
- [x] S1-3c：实现租户/成员安全的 Project 列表、详情、编辑、七态迁移与相邻 Stage 推进 API
- [x] S1-3d：实现同源 BFF 与 Project 创建/列表/详情/Timeline 工作页，覆盖对象权限、空态/错误态和响应式双主题
- [x] S1-3e：完成聚焦测试、完整门禁、迁移往返及真实 Requirement→Case→Project/Stage 浏览器验收

**Acceptance evidence required**

- [x] approved Case 可且仅可创建一个 draft Project；结果含独占 Workflow、七个有序 Stage、首 Stage 指针与创建者成员关系，Case 同事务变为 converted
- [x] 任一实例化写入失败时 Workflow/Stage/Project/member/Case/event/audit 全部回滚；跨租户/未知 Case 与对象范围 fail-close
- [x] Project 只允许冻结状态边；仅 active 项目可推进到同 Workflow 的相邻 Stage，末 Stage/跳级/跨 Workflow 均拒绝
- [x] Owner/Admin 可见租户项目；其余五角色仅见成员项目，且只有 Owner/Admin/PM 有写入口
- [x] Project 页面正确渲染七阶段 Timeline，并在双主题和 320/768/1440px 下可用，控制台无 warning/error

**Acceptance evidence (2026-08-11)**

- `make check`：101 个 server tests、55 个 web tests、Ruff/ESLint、Python/TypeScript 严格类型检查和生产构建全绿；migration `0006` 往返与唯一 Alembic head 测试通过
- 隔离真实 HTTP/浏览器：Owner 完成 Requirement→Case→Project，Project 创建 POST 返回 201；内容编辑 PATCH 仅发送变化的 `name`，三次状态迁移与一次相邻 Stage 推进均返回 200
- 数据库证据：独占 Workflow/Project/创建者成员各 1 条、七个 Stage 顺序与模板完全一致，来源 Case 为 `converted`；项目最终为 `active/planning`，创建、更新、状态和阶段 event+audit 数量逐项一致
- 权限与事务证据：重复编号、重复 Case、跨租户/非成员、非法状态边、跳级/跨 Workflow/非 active 推进及中途失败回滚均由正反例测试覆盖
- Playwright：七阶段 Timeline、空态/错误重试/只读角色、明暗主题和 320/768/1440px 均通过；320px 无横向溢出、所有可见交互目标至少 44px，控制台 0 warning/0 error
- 本地截图：`output/playwright/s1-3-project-light-1440.png`、`s1-3-project-dark-1440.png`、`s1-3-project-dark-768.png`、`s1-3-project-dark-320.png`（验证产物按 `.gitignore` 不入库）

## Completed: S1-4 Task / Issue / Risk

**Definition of Ready**

- [x] 规格出处：`Workflow.md`、`Product_Flow.md`、`PostgreSQL_Schema_Design.md`、`RBAC_and_Audit.md`、`Event_Catalog.md` 与 canonical S1-4
- [x] 依赖项：S1-3 已完成；Project/Stage/成员对象权限、Task/Issue/Risk 基础表与同事务 event+audit 端口已就绪
- [x] Task 边界冻结：公开状态边为 `todo → in_progress/blocked/skipped`、`in_progress → blocked/done`、`blocked → todo/in_progress/skipped`；`done/skipped` 终态，`pending_approval` 本项不开放入口
- [x] 依赖语义冻结：前置未完成时派生 `waiting` readiness、Task 保持 `todo`；不得自动或人工借依赖写成 `blocked`，显式阻塞必须提供真实原因；依赖仅限同项目且禁止自环/有向环
- [x] Issue 状态图冻结：`open → analysis → action → verification → closed`，closed 终态；Risk 状态图冻结：`open → mitigating/watching`、`mitigating ↔ watching`、两者可到 `closed`，closed 终态
- [x] 对象权限冻结：Owner/Admin 可访问租户内项目工作项；PM/Engineer/Quality 仅限成员项目且可编辑；Supplier/Customer 无工作项入口
- [x] UI 边界冻结：S1-4 交付 FastAPI 与同源 BFF 数据合同；Project Workspace 的 Task/Issue/Risk 五标签组合按 canonical 留在 S1-6
- [x] 迁移号预留为 `0007`：增加 Task 依赖关系与显式阻塞原因，强化工作项对象约束、稳定排序索引及闭环时间一致性，迁移号不复用

**Implementation slices**

- [x] S1-4a：migration 0007 建立同项目 Task dependency 图、blocked reason 与 Task/Issue/Risk 数据边界
- [x] S1-4b：实现 Task readiness/依赖环检测与状态动作，确保“等待前置 ≠ blocked”
- [x] S1-4c：实现 Issue 五态与 Risk 生命周期服务，所有写路径同事务落版本化 event+audit
- [x] S1-4d：实现项目对象权限绑定的 Task/Issue/Risk API 与同源 BFF，列表稳定排序并隐藏外部角色
- [x] S1-4e：完成聚焦测试、完整门禁、迁移往返及真实 Requirement→Case→Project→Task/Issue/Risk HTTP 验收

**Acceptance evidence required**

- [x] 同项目 Task 可建立无环依赖；前置未完成时后继仍为 `todo/waiting` 且不可开始，前置完成或跳过后 readiness 自动变为 `ready`
- [x] `blocked` 只能由带非空原因的显式动作产生并可解除；依赖变化永不把后继写成 blocked
- [x] Issue 仅按五态相邻前进并在 closed 写入关闭时间；Risk 仅按冻结四态流转并稳定返回 likelihood×impact 分值
- [x] 跨租户、跨项目依赖/Stage/负责人、非成员和外部角色均 fail-close；失败事务不留下业务/event/audit 残片
- [x] 每个 Task/Issue/Risk 创建、内容编辑与状态动作均有对应版本化 event 与不可变 audit，`ISSUE_CREATED` 保持 canonical payload
- [x] FastAPI/BFF 合同、101+ server tests、55+ web tests、lint/type/build、migration 0007 往返及真实 HTTP 链路全绿

**Acceptance evidence (2026-08-11)**

- `make check`：107 个 server tests、58 个 web tests、Ruff/ESLint、Python/TypeScript 严格类型检查和生产构建全绿；migration `0007` downgrade→upgrade 往返与唯一 Alembic head 测试通过
- 隔离真实同源 HTTP：Owner 完成 Requirement→Case→Project→Task/Issue/Risk；最终 Requirement/Case 均为 `converted`，Project 独占 7 个 Stage，含 2 个 Task、1 条 dependency、1 个 closed Issue 与 1 个 closed Risk
- Task 证据：后继从 `todo/waiting` 随前置完成自动变为 `todo/ready`，显式 `blocked` 必须带原因且解除后恢复 `todo/ready`；有向环与跨项目依赖均被拒绝
- Issue/Risk 证据：Issue 严格相邻推进并写 `closed_at`；Risk 严格按冻结状态图推进，`likelihood=4`、`impact=5` 稳定返回 `score=20`
- 权限与事务证据：跨项目依赖、跨 Workflow Stage、外部角色负责人、非成员与 Supplier 入口均 fail-close；失败写入前后业务/event/audit 计数不变
- 事件审计证据：真实链路中 requirement/development_case/project/task/issue/risk/decision 的 event 与 audit 数量逐实体一致；`ISSUE_CREATED` canonical payload 由测试锁定

## Completed: S1-5 Event Coverage + Debug Stream

**Definition of Ready**

- [x] 规格出处：`Event_Catalog.md`、`API_Design.md`、`RBAC_and_Audit.md` 与 canonical S1-5
- [x] 依赖项：S1-1～S1-4 的业务写路径已统一经过 `EventAuditWriter`，事件表已有 tenant/project/id 查询索引，无需新增 migration `0008`
- [x] 覆盖边界冻结：审计 Sprint 1 已实现写路径并锁定版本化注册表；尚无业务生产者的 Gate/Document/Test/Supplier/Complaint/AI 事件保留注册定义，不伪造事件
- [x] API 边界冻结：只读 `GET /api/events` 提供 tenant-bound、`id` 升序 cursor、limit 与 event_type/project_id 筛选；`GET /api/events/catalog` 返回冻结定义；不提前实现 S2-5 外部 `POST /events`
- [x] 权限边界冻结：事件调试能力仅 Owner/Admin 可见，其他五角色无导航且 API fail-close；project_id 筛选必须解析为当前租户项目
- [x] 回放语义冻结：本项的“回放”是按稳定 cursor 检查历史 envelope/payload，不提供重新执行消费者或改写业务状态的动作
- [x] UI 边界冻结：`/events` 为开发内部只读页，提供类型/项目筛选、刷新、加载更多、catalog/envelope/payload 检查以及 loading/empty/error/forbidden 状态；遵循既定双主题与响应式基线

**Implementation slices**

- [x] S1-5a：锁定 Sprint 1 implemented-event 覆盖清单、catalog 合同与 Owner/Admin 专属 action
- [x] S1-5b：实现 tenant-bound Event 查询服务及 catalog/stream FastAPI，覆盖 cursor、筛选、权限和跨租户正反例
- [x] S1-5c：实现同源 BFF 与只读 `/events` 调试页，隐藏非管理员入口并检查 envelope/payload
- [x] S1-5d：完成聚焦测试、完整门禁及真实事件流 cursor/filter HTTP 与响应式双主题浏览器验收

**Acceptance evidence required**

- [x] Sprint 1 所有实际写路径的 event type 均在 v1 registry 中且 producer/payload 受服务端校验；canonical 10 类集合不被扩写
- [x] Event stream 只返回当前租户数据，按 `id` 稳定升序，可用 cursor 无重无漏读取并按 event_type/同租户 project_id 筛选
- [x] Owner/Admin 可访问 catalog 与 stream；PM/Engineer/Quality/Supplier/Customer 均 403，UI 无入口；未知/跨租户 project filter 一致 fail-close
- [x] 调试页可检查 schema version、source、entity、event_id、timestamp、consumers 与 payload，且不提供任何写入/重放执行能力
- [x] API/BFF、server/web tests、lint/type/build 与真实事件流 HTTP/浏览器链路全绿

**Acceptance evidence (2026-08-11)**

- `make check`：108 个 server tests、64 个 web tests、Ruff/ESLint、Python/TypeScript 严格类型检查与生产构建全绿；事件读取未改变 schema，Alembic 仍为唯一 `0007` head
- catalog 证据：canonical 10 类集合保持不变；Sprint 1 implemented set 精确锁定 22 类，真实页面显示 `22 / 29` 已实现/已注册，未来生产者定义保留但不伪造数据
- 真实同源 HTTP：`limit=2` 首段 ID `[43,44]`、`after_id=44` 次段 `[45,46]`，无重叠且稳定升序；`TASK_CREATED` 类型筛选仅返回对应事件
- 权限与租户证据：Owner/Admin catalog/stream 200，PM 直达只显示管理员限制且导航无入口；五个非管理员角色 API 403，跨租户/未知 Project filter 一致 404，异租户事件不进入结果
- Playwright：Owner 检查 source/entity/event_id/project_id/consumers 与展开 payload，并完成 event_type+project_id 筛选；PM 无事件入口；明暗主题与 320/768/1440px 全绿
- 响应式修复：长 event type `<select>` 的 intrinsic width 已收口；320px `scrollWidth=innerWidth=320`，所有可见交互目标至少 44px，控制台 0 warning/0 error
- 本地截图：`output/playwright/s1-5-events-light-1440.png`、`s1-5-events-dark-1440.png`、`s1-5-events-dark-768.png`、`s1-5-events-dark-320.png`（验证产物按 `.gitignore` 不入库）

## Completed: S1-6 Frontend First Version

**Definition of Ready**

- [x] 规格出处：`Product_Flow.md`、`Workflow.md`、`System_of_Record_Matrix.md`、UI baseline 与 canonical S1-6
- [x] 依赖项：S1-1～S1-5 已完成；Project/Workflow/Stage 与 Task/Issue/Risk FastAPI、RBAC、同源 BFF 合同均已就绪
- [x] Dashboard 范围冻结：登录后默认首页仅交付 Portfolio 与跨项目 Risk 两卡；S2-6 AI Brief 不提前占位或伪造数据
- [x] Project Workspace 范围冻结：仅 Overview/Timeline/Task/Issue/Risk 五标签；Gate/Document/Meeting/AI Chat 均留在后续 Sprint
- [x] 交互范围冻结：内部角色可通过既有 BFF 创建工作项并执行合法状态动作；项目编辑/状态/阶段能力保留；不在前端复制服务端状态机真值
- [x] 权限范围冻结：Owner/Admin 读取租户项目；PM/Engineer/Quality 仅成员项目且可操作工作项；Supplier/Customer 不请求、不展示 Task/Issue/Risk 入口
- [x] 数据范围冻结：不新增 migration 或业务 API；Dashboard 按可见项目聚合风险，失败项目不静默伪装为零风险

**Implementation slices**

- [x] S1-6a：以测试冻结 Task/Issue/Risk 前端类型、响应校验、创建与状态动作请求合同
- [x] S1-6b：重构 Project Workspace 为五标签，交付 Overview 汇总、Timeline 与角色感知的三类工作项界面
- [x] S1-6c：将登录后首页替换为 Portfolio/Risk 双卡 Dashboard，并按权限处理风险聚合与失败态
- [x] S1-6d：完成聚焦测试、完整门禁、Requirement→Case→Project→Task/Issue 浏览器闭环及双主题响应式验收

**Acceptance evidence required**

- [x] 登录后默认进入 Dashboard；Portfolio 展示可见项目的状态、当前阶段与进度，Risk 按 score 降序汇总且可回到对应项目
- [x] Project Workspace 精确显示五标签；Overview 数量与三类列表一致，Timeline 正确渲染七阶段
- [x] Task 明确区分 status 与 readiness，依赖未完成显示 waiting 而非 blocked；显式 blocked 动作必须填写原因
- [x] Issue/Risk 仅呈现服务端冻结状态图允许的下一动作；创建与动作成功后局部数据刷新，失败显示行内可重试错误
- [x] Supplier/Customer 无 Task/Issue/Risk 标签或网络请求；内部只读/可写边界与服务端 RBAC 一致
- [x] 页面具备 loading/empty/error 状态，在亮暗主题与 320/768/1440px 下无横向溢出，键盘可达且控制台零 warning/error
- [x] web/server tests、lint/type/build、Alembic 单 head 与 Sprint 1 真实业务闭环全部通过

**Acceptance evidence (2026-08-11)**

- `make check`：108 个 server tests、75 个 web tests、Ruff/ESLint、Python/TypeScript 严格类型检查、测试库隔离、生产构建与 Python 编译全绿；Alembic 仍为唯一 `0007` head
- Playwright 真实浏览器：从登录后 Dashboard 完成 Requirement `REQ-S1-001` → Case `CASE-S1-001`（Decision 留痕）→ Project `PRJ-S1-001` → Task/Issue/Risk；Dashboard 风险评分 20 可深链回项目，Timeline 精确渲染 P1～P7
- Task/Issue/Risk 证据：前置 Task 完成后后继从 `todo/waiting` 即时刷新为 `todo/ready`；Issue 严格走完 open→analysis→action→verification→closed；Risk 的 likelihood=4、impact=5、score=20
- 事件审计证据：真实链路产生 27 条事件与 27 条审计，按 `(tenant_id, event_id)` 未配对数为 0；Requirement/Case/Decision/Project/Task/Issue/Risk 全程可回放
- 权限与错误态：Supplier/Customer 的工作项标签与请求由测试锁定为零；Dashboard 部分风险请求失败不会伪装为零风险；工作项状态错误行内呈现
- 响应式与可访问性：亮/暗主题以及 320/768/1440px 均无横向溢出；320px 主要控件触控区至少 44px，原生前置复选框关联标签触控区为 201×44px；控制台 0 warning/0 error
- 本地截图：`output/playwright/s1-6-project-timeline-light-1440.png`、`s1-6-dashboard-dark-1440.png`、`s1-6-project-task-dark-768.png`、`s1-6-dashboard-dark-320.png`、`s1-6-project-task-dark-320-viewport.png`（验证产物按 `.gitignore` 不入库）

## Next: Sprint 1 Exit Gate

- [x] S1-1～S1-6 的工作项验收条款与项目级 Definition of Done 全部满足
- [x] Requirement→Case（Decision）→Project→Task/Issue 的真实业务闭环、事件回放与七阶段 Timeline 验收通过
- [x] Sprint 1 的完整质量门禁、权限边界、双主题与响应式浏览器验收通过
- [x] 汇报 Sprint 1 验收结果并获得人明确确认，进入 Sprint 2

## Completed: S2-1 Multi-provider LLM Gateway

**Definition of Ready**

- [x] 规格出处：canonical S2-1、`AI_Runtime_Architecture.md`、`RBAC_and_Audit.md` 与执行计划 §11 学习环纪律
- [x] 依赖项：Sprint 1 出口已确认；`cehub_ai` namespace、租户认证/RBAC、FastAPI/Next.js 同源 BFF 与隔离测试库已就绪
- [x] 协议边界冻结：MiniMax/GLM/OpenAI/DeepSeek 仅走 OpenAI-compatible；Anthropic 仅走原生协议；不增加第三种协议或供应商 SDK
- [x] 模型治理冻结：默认 MiniMax；租户只可选择“env 有凭据 + golden-case 全量通过”的候选，API 永不返回 key/base_url
- [x] 路由边界冻结：Sprint 2 单模型跑通，保留 Agent tier 参数；模型/租户/项目自报值不作为政策事实
- [x] 输出边界冻结：网关统一解析 JSON、执行 schema 校验并有限重试；失败有稳定降级结果，不让业务错误路径再次调用 LLM
- [x] 数据边界冻结：只允许白名单投影离库，密级字段、对象存储键和原文不进入供应商请求；出口主机来自配置白名单
- [x] 迁移号冻结为 `0008`，建立租户模型设置与 `cehub_ai.model_invocations`，不复用或修改旧迁移

**Implementation slices**

- [x] S2-1a：用测试冻结 provider catalog、credential+golden 双门禁、默认 MiniMax 与 Agent tier 路由合同
- [x] S2-1b：migration 0008 建立 tenant model settings 与 model invocation 留痕，覆盖约束、索引、租户 FK 和往返
- [x] S2-1c：实现上下文白名单投影、日预算计算/熔断及租户模型治理服务/API
- [x] S2-1d：实现 OpenAI-compatible/Anthropic 两个 adapter、结构化 schema 校验有限重试及完整 invocation 记录
- [x] S2-1e：实现治理页「模型与预算」及同源 BFF，仅展示合格候选与非敏感调用摘要
- [x] S2-1f：固化 golden-case runner、出口白名单校验、真实本地 fake-provider/API/浏览器路径与完整质量门禁

**Acceptance evidence required**

- S2-1e 前端证据：同源 BFF 缺 session 时 fail-close 且不访问上游；Owner/Admin 才请求治理数据，非管理员不显示导航且不产生治理请求；页面只解析合格模型、选择状态与聚合预算，不接受或呈现连接密钥/地址
- S2-1e 质量证据：82 个 web tests、ESLint 与 TypeScript 严格检查全绿；保存请求精确包含 provider/model/daily token budget，空合格池明确显示且禁用保存

- [x] 只有 env 配置凭据且 golden-case 通过的模型进入租户候选；未配置、未评测或退化模型不可选择，API/UI 不泄露任何 key/base_url
- [x] 两类协议均通过真实 HTTP fake-provider 合同；结构化输出首轮无效时按固定预算重试，耗尽后稳定降级且错误路径零额外 LLM 调用
- [x] 每次成功、供应商失败、schema 失败和预算熔断均产生可归因的 model invocation；token、缓存 token、耗时、prompt 版本、Agent、供应商/模型与归一成本完整
- [x] 租户日预算超限时不调用供应商、不阻塞业务；不同租户预算与用量严格隔离
- [x] 白名单投影阻止密级字段、对象存储键和原文离库；请求目标不在已配置供应商 host 白名单时 fail-close
- [x] 治理页可选择合格模型和调整预算，刷新后保持；Owner/Admin 可写，其他角色只读或拒绝，跨租户稳定 fail-close
- [x] golden-case 全量通过才可发布模型资格，可信根与阈值不在运行时自动化写路径内；完整 lint/type/test/build、migration 往返与浏览器验收全绿

**Acceptance evidence (2026-08-11)**

- `make check`：146 个 server tests、82 个 web tests、Ruff/ESLint、Python/TypeScript 严格类型、Next.js production build 与 Python compile 全绿；Alembic 唯一 head 为 `0009_invocation_cache_tokens`，0007→0009 往返通过
- Provider/runtime：OpenAI-compatible 与 Anthropic-native 均跨真实 loopback HTTP socket 完成合同；注入非配置 route 时 transport 调用数为 0；schema 首轮失败后固定重试、耗尽降级、provider 失败与预算熔断均有测试和不可变 invocation 证据
- Golden gate：可信 suite 内容摘要与 100% 阈值入库；runner 执行完整 suite、只输出 secret-free 报告且没有发布写口；运行时拒绝 suite version/digest 不一致的资格文件；默认人工发布清单为空
- 浏览器：Owner 从导航进入治理页并把租户预算保存为 3,000,000，PATCH 仅含 provider/model/budget，设置/event/audit 三方一致；Supplier 直达显示管理员限制且治理请求数为 0
- 响应式与可访问性：亮/暗主题、320/768/1440px 无横向溢出；320px 可见交互目标均至少 44px，干净浏览器会话 0 warning/0 error；截图位于 `output/playwright/s2-1-governance-*.png`（按 `.gitignore` 不入库）
- 环境门禁：本地所有真实供应商 key 均为空，因此没有伪造或发布 MiniMax 真实资格；当前验收使用 fake-provider，真实模型接入须按 `docs/runbooks/model-qualification.md` 人工全量评测后另行发布

## Current: S2-2 LangGraph Execution Loop

**Definition of Ready**

- [x] 规格出处：canonical S2-2、`AI_Runtime_Architecture.md`、`Event_Catalog.md`、`RBAC_and_Audit.md` 与执行计划 §11 Context/错误/工具纪律
- [x] 依赖项：S2-1 已完成；事件表、租户/项目权限、模型网关与 `cehub_ai` namespace 已就绪
- [x] 进程边界冻结：dispatcher 是控制面，executor 是执行面；生产配置与凭据分离，executor 只接收服务端冻结的 run context
- [x] 触发边界冻结：按 tenant+project 聚合，默认 15 分钟 debounce；id-cursor 单调消费并通过唯一键保证重复事件不重复建 run
- [x] 路由边界冻结：事件类型→Agent 静态表；模型、tenant、project 自报参数都不是政策事实
- [x] 工具边界冻结：仅 get_project_context / search_memory / get_recent_events 三个只读端口；范围只能来自 run context，越界参数直接拒绝且显式标注截断
- [x] 失败边界冻结：run 错误路径零 LLM 调用；单 Agent 连续失败达到阈值后暂停订阅并记录告警，不做无限重试
- [x] 范围冻结：本项只交付运行控制、上下文和只读工具；Finding 写出口、Human Review 状态机与业务 apply 留在 S2-3
- [x] 迁移号冻结为 `0010`，建立 dispatcher cursor/subscription/agent run 控制面记录，不修改或复用既有迁移

**Implementation slices**

- [x] S2-2a：以测试冻结静态 Agent 路由、run context、状态机、debounce/幂等与失败熔断合同
- [x] S2-2b：migration 0010 建立 dispatcher cursor、Agent subscription 与 agent_runs，覆盖租户 FK、唯一键、状态约束、索引和往返
- [x] S2-2c：实现 id-cursor dispatcher、tenant+project debounce、静态路由和原子 run 创建
- [x] S2-2d：实现 executor LangGraph 骨架、冻结前缀/动态 context 末尾、三只读工具及服务端范围绑定
- [x] S2-2e：实现 run 失败分类、错误路径零 LLM、连续失败暂停订阅与告警记录
- [x] S2-2f：完成 dispatcher/executor 分进程配置、真实事件→run fake-model 路径、迁移往返与完整质量门禁

**Acceptance evidence required**

- [x] 同一 tenant+project+Agent 的窗口内事件合并为一个 run，游标单调推进；重复消费不重复建 run，跨租户事件永不合并
- [x] 静态路由只为订阅事件选择 Agent；冻结 run context 由服务端绑定 tenant/project/event 范围，executor 不接受客户端政策事实
- [x] 三只读工具只读取 run context 范围；越界 ID fail-close，截断显式返回“已显示 X 之 Y 条”及续读方式
- [x] system prompt/工具定义前缀稳定，动态项目状态只追加到 context 尾部；代码预聚合值有确定性测试
- [x] 成功/失败/降级 run 状态与 invocation 可关联；错误处理与告警路径零额外 LLM 调用
- [x] 单 Agent 连续失败达到阈值后订阅自动暂停，后续事件不建 run，管理员可见暂停原因
- [x] dispatcher 与 executor 配置/凭据分离；完整 lint/type/test/build、migration 往返与真实事件路径全绿

**Completion evidence（2026-08-11）**

- `make check` 全绿：server 179 tests、web 82 tests，ruff/format/mypy/TypeScript/Next.js build/Python compile 全部通过。
- migration `0010` 升级、降级、metadata drift、append-only 历史兼容与租户 FK 约束回归全绿。
- 真实 PostgreSQL 事件路径通过：Event→id-cursor dispatcher→15 分钟 debounce→queued run→SQL 预聚合 context→LangGraph→fake provider→immutable model invocation；run/invocation 关联正确，原始 payload 与密钥未出门。
- 连续失败阈值测试通过：错误收口零额外模型调用；达到阈值后订阅 paused，新事件只推进游标、不再创建 run；Owner/Admin 可见暂停原因。
- 隔离生产容器 smoke 全绿：migrate/API/dispatcher/executor/web/BFF 健康，Python 服务 UID 10001 非 root；只连接本地 `pdos_test`，未触碰 RDS/生产。

## Completed: S2-2b Database Security Boundary

**Definition of Ready**

- [x] 规格出处：canonical S2-2b、RBAC/Audit 规格、AGENTS 安全红线与 S2-2 已冻结的进程/工具合同
- [x] 依赖项：migration 0010、dispatcher/executor 分进程、专用 DSN 启动前校验已完成
- [x] 权限边界冻结：`pdos_worker` 只读 event stream 并管理 dispatcher 控制记录；`pdos_agent` 只读租户投影视图并写 AI 运行记录；两者业务表零写
- [x] 运维边界冻结：只交付幂等 SQL 模板与隔离数据库正反向测试；不创建生产 RDS 角色、不发放凭据、不部署
- [x] 迁移纪律冻结：数据库角色/GRANT 不进入 Alembic schema migration；独立幂等权限模板可由 DBA 审阅执行

**Implementation slices**

- [x] S2-2b-a：冻结 worker/agent 投影视图与最小权限矩阵，建立独立幂等 SQL 模板
- [x] S2-2b-b：在 `pdos_test` 创建临时角色并验证允许路径（event→run、context projection、invocation）
- [x] S2-2b-c：红队验证业务表 INSERT/UPDATE/DELETE、跨租户投影与自由 schema/table 读取 0 穿透
- [x] S2-2b-d：验证 executor 配置拿不到 app/worker DSN，补齐 DBA 运行手册、完整质量门禁与安全证据

**Completion evidence（2026-08-11）**

- 角色与权限模板连续执行两次成功，回滚成功；测试结束后 `pdos_worker` / `pdos_agent` 临时口令清空，权限对象移除。
- 真实登录角色正向路径通过：worker 消费 event 并创建控制面 run；agent 以 run lease 读取白名单投影、构建冻结 context、调用 fake provider、写不可变 invocation 并完成 run。
- 红队路径 0 穿透：未绑定/伪造 tenant scope 均返回 0 行；业务表自由读取和 INSERT/UPDATE/DELETE、跨租户 invocation、直接更新 run 全部 permission denied；原始 event payload 未进入模型消息。
- `make check` 全绿：server 183 tests、web 82 tests，ruff/format/mypy/TypeScript/Next.js build/Python compile 全部通过。
- 隔离生产容器 smoke 全绿：migrate/API/dispatcher/executor/web/BFF 健康，dispatcher/executor 使用真实独立登录角色且 Python 服务 UID 10001 非 root；只连接本地 `pdos_test`。
- 生产 RDS 未变更；角色创建、密码发放、模板执行和回滚步骤已交付 `docs/runbooks/agent-runtime-database-security.md`，继续由人和 DBA 执行。

## Completed: S2-3 AI Finding State Machine

**Definition of Ready**

- [x] 规格出处：canonical S2-3、AI Integration/RBAC/Audit/Event Catalog 规格与 S2-2b 数据库边界逐条映射
- [x] 状态机冻结：pending_review→accepted/rejected；仅 accepted 可独立 applied；裁决与应用不得合并
- [x] 权限冻结：Agent 只创建 finding；Reviewer 裁决；有项目写权限的人二次鉴权后 apply；executor 仍无业务表写权限
- [x] 真值边界冻结：finding payload 全部不可信；preflight 与 apply 均从数据库重查 tenant/project/reference/status
- [x] 迁移号冻结为 `0011`，事件/审计/幂等键/状态约束与回滚验收先于业务实现

**Implementation slices**

- [x] S2-3a：以测试冻结 Finding schema、状态机、事件、RBAC、预检与 apply 真值复核合同
- [x] S2-3b：migration 0011 建立 findings 与 append-only review/apply 留痕，并扩展 `pdos_agent` 受控创建出口
- [x] S2-3c：实现 Agent deterministic preflight 与 finding 创建，非法引用/跨租户/schema 错误 fail closed
- [x] S2-3d：实现 Reviewer accept/edit/reject 与独立 apply handler，二次鉴权并只支持风险建议落为 Risk
- [x] S2-3e：实现 FastAPI inbox/detail/review/apply API、事件审计与幂等冲突处理
- [x] S2-3f：完整正反向、迁移往返、受限角色、HTTP 与质量门禁验收

**Completion evidence（2026-08-11）**

- migration `0011` 建立 `findings` / append-only `finding_actions`、租户复合 FK、状态/人审/apply 时序约束、run+origin 幂等键；升级/降级/metadata drift 全绿。
- 真实 `pdos_agent` 只能经 `create_agent_finding` 函数提交当前 run 的候选；自由读写 findings、跨租户 evidence、越界 invocation 全部被拒。
- Event→dispatcher→受限 executor→model invocation→确定性 preflight→pending Finding 全链路通过；原始 payload 未进入模型消息，Finding 可追溯到 run/invocation/evidence。
- Review 与 Apply 是两个独立 HTTP/服务动作：Accept/Edit/Reject 写不可变 action 与 AI_FEEDBACK_RECEIVED；Accept 不改业务，独立 Apply 才创建 Risk，重复 Apply 幂等。
- Apply 在持锁事务中二次鉴权并重查用户、项目状态、run、invocation、evidence 和 accepted payload；外部角色/非成员/终态项目/失效引用均 fail closed。
- `make check` 全绿：server 192 tests、web 82 tests，ruff/format/mypy/TypeScript/Next.js build/Python compile 全部通过；隔离生产容器 smoke 全绿。
- 生产 RDS 未变更；测试临时角色口令与权限对象已清理。

## Completed: S2-4 Phase 1 Dual Agents

**Definition of Ready**

- [x] 规格出处：AI Runtime/路线图/canonical S2-4 与当前 Event Catalog/工具/Finding 合同逐条映射
- [x] Agent 边界冻结：同一运行时两份静态配置，不新增 Agent 互审、自由 SQL/HTTP/shell 或第二套 runtime
- [x] Project Intelligence 输出冻结：风险建议/阻塞预警/Gate 就绪异常统一进入 Finding，人审前不改业务
- [x] Knowledge Lite 输出冻结：GATE_APPROVED/DOCUMENT_UPLOADED 只创建知识草稿候选，不进入 verified memory
- [x] prompt 版本化与前缀冻结：system prompt/工具定义文件入库，动态 context 只追加末尾；变更需 golden-case

**Implementation slices**

- [x] S2-4a：冻结双 Agent prompt/结构化输出/订阅/负例与评测合同
- [x] S2-4b：版本化 Project Intelligence prompt 与风险/阻塞/Gate 三类 Finding candidate 映射
- [x] S2-4c：版本化 Knowledge Lite prompt 与知识草稿 Finding 类型/预检/受限创建路径
- [x] S2-4d：接通 PROJECT_STAGE_CHANGED/ISSUE_CREATED/TEST_FAILED 与 GATE_APPROVED/DOCUMENT_UPLOADED 事件路由
- [x] S2-4e：真实受限角色、双 Agent fake-provider、错误路径零 LLM、完整质量门禁验收

**Completion evidence（2026-08-11）**

- 两份独立 JSON prompt 固定为 `project-intelligence-v1` / `knowledge-lite-v1`，与只读工具定义组成不可变前缀；运行时租户/项目/事件上下文仍只追加到末尾。
- `0012_phase_one_agents` 将 Agent↔Finding 类型约束下沉到数据库：Project Intelligence 仅三类项目候选，Knowledge Lite 仅 `knowledge_draft`；降级遇到新类型数据时 fail closed，不静默删数据。
- 确定性 preflight 同时校验 Agent 类型、静态事件订阅、冻结 evidence、payload schema 与租户 run 范围；受限 SQL 函数再次执行同类白名单，跨 Agent 类型与跨租户均拒绝。
- Knowledge 草稿可经人 Accept/Edit/Reject，但 S4-2 verified memory 就绪前不可 Apply，不创建 Risk、不进入检索；Project Intelligence 三类候选继续通过独立 Apply 落成 Risk。
- `phase-one-agents-v1.json` 固化 6 个正/负 golden cases；真实 `pdos_agent` + fake provider 分别完成双 Agent Event→Finding 全链路。
- `make check` 全绿：server 204 tests、web 82 tests，ruff/format/mypy/TypeScript/Next.js build/Python compile 全部通过；隔离生产容器 smoke（本地端口 57432）全绿。
- 生产 RDS 未变更；测试临时角色口令与权限对象已清理。

## Completed: S2-5 API Surface

**Definition of Ready**

- [x] 逐条映射 canonical S2-5、现有 Gateway/Finding/Event/Document 边界与 API 命名
- [x] `/ai/chat` 冻结为只读回答；每个主张必须带可点击引用，无据拒答
- [x] `/ai/analyze-document` v0 仅做 PDF/Excel 文本抽取并发 DOCUMENT_UPLOADED，OCR 后置
- [x] `/ai/create-risk-suggestion` 只创建 pending Finding，不直接写 Risk
- [x] 外部 `POST /events` 由 tenant-bound server context 绑定范围，event_id 幂等去重

**Implementation slices**

- [x] S2-5a：冻结四个 API 的 request/response/error/权限/引用合同与负例
- [x] S2-5b：实现引用强制的只读 `/ai/chat`
- [x] S2-5c：实现 Document AI v0 文本抽取与 DOCUMENT_UPLOADED 事件
- [x] S2-5d：实现风险建议 Finding 入口与幂等外部 Event 接入
- [x] S2-5e：HTTP、注入/越权、错误路径零 LLM、完整质量门禁验收

**Completion evidence（2026-08-11）**

- migration `0013_ai_api_documents` 建立私有 Document 元数据与有序抽取片段；原文件写 S3 兼容 MinIO/OSS，数据库仅留对象键、摘要和 `page` / `sheet+rows` 无损指针；扫描型 PDF 显式返回 `ocr_required`。
- `/api/ai/chat` 以结构化 claim 强制每条主张至少一个引用；模型只收到服务端白名单 evidence ID/摘录，站内 href 由服务端映射，未知或跨范围引用 fail closed 为 `insufficient_evidence`。
- `/api/ai/create-risk-suggestion` 建立可追溯 run/invocation，只产生 `pending_review` Finding；重复 request_id 幂等，Accept 与 Apply 仍保持两个独立人工动作，API 不直接创建 Risk。
- `POST /api/events` 仅开放 TEST_FAILED/SUPPLIER_DELAY_REPORTED/COMPLAINT_CREATED 三类外部事实，tenant/project 由认证上下文与成员权限绑定；相同 event_id 同载荷返回 replay，异载荷返回 409，内部事件冒充被拒。
- DOCUMENT_UPLOADED 会由 dispatcher 路由 Knowledge Lite；受限 `pdos_agent` 只能经 run lease 读取 document fragment projection，原文件与 object_key 不可见，业务表写入仍为 0 穿透。
- 完整门禁全绿：server 211 tests、web 82 tests，Ruff/format/mypy/ESLint/TypeScript/Next.js build/Python compile 全部通过；`0013` 降级再升级、真实受限角色安全测试与隔离生产容器 smoke 全绿。
- 测试仅连接本地 `pdos_test`（端口 57432，因 55432 被现有 CEHub 占用）；生产 RDS/OSS/ECS/Nginx/DNS 均未变更，测试角色口令与权限对象已清理。

## Completed: S2-6 Frontend AI Surface

**Definition of Ready**

- [x] 逐条映射 canonical S2-6、UI baseline、Finding/Chat API 与现有 Dashboard/Project Workspace 结构
- [x] AI Review 收件箱冻结 Accept/Edit/Reject、逐字段 diff、证据跳转与 accepted 后独立 Apply
- [x] Dashboard AI Brief 只呈现真实 Agent/Finding 事实，降级与空态不可伪装为正常
- [x] Project Workspace AI Chat 标签使用 S2-5 引用合同，不在前端自行生成或信任链接
- [x] 权限、双主题、320/768/1440 响应式、键盘可达与真实浏览器验收范围冻结

**Implementation slices**

- [x] S2-6a：冻结前端类型、同源 BFF、权限与交互合同
- [x] S2-6b：实现 AI Review 收件箱及 Accept/Edit/Reject/Apply 两阶段交互
- [x] S2-6c：实现 Dashboard AI Brief 卡片与可观测降级/空态
- [x] S2-6d：实现 Project Workspace AI Chat 标签、引用跳转与无据拒答态
- [x] S2-6e：完成测试、真实浏览器、双主题响应式与完整质量门禁验收

**Completion evidence（2026-08-11）**

- `/ai-review` 交付跨项目 Finding 队列、类型筛选、逐字段 diff、真实 Event 引用深链，以及 Accept/Edit/Reject 键盘操作；Reject 强制人工原因。
- Accept 与 Apply 维持两个独立动作：浏览器实测 Accept 后业务 Risk 数不变，最终载荷预览与二次确认后才由服务端复核并创建 Risk；Knowledge draft 明确不可 Apply。
- Dashboard AI Brief 只读取服务端可见 Finding；模型不可用时显示“AI 已暂停”及最近可追溯事实，不把降级伪装为正常。
- Project Workspace 增加内部用户可见的 AI Chat；只消费服务端映射的同源引用，无证据拒答，模型移除时明确降级；外部角色不显示 AI 面。
- Event 引用已在真实浏览器中验证落到项目 Timeline 的指定活动并高亮；亮/暗主题视觉核对通过。自动化门禁：web 90 tests、server 定向 12 tests，Ruff/format/mypy/ESLint/TypeScript/Next.js build 全绿。
- 本地完整 `make check` 首次运行误读 `.env` 的 55432（该端口属于现有 CEHub），属于环境指向问题；S2-7 收口将以显式隔离的 57432 `pdos_test` 重跑全量门禁。

## Completed: S2-7 Discipline Closeout

**Definition of Ready**

- [x] 拆除测试冻结“无新 Finding / Brief 明确失能 / Chat 降级”三项观测，且错误路径零 LLM
- [x] golden-case 可信根与人工修正积累边界冻结，任何运行时自动化均无写权限
- [x] finding 接受率与被采取行动数的服务端口径、权限范围和 Dashboard 呈现冻结
- [x] 低质阈值只在达到最小人工样本量后按 Agent + Finding 类型收窄，不用产出量替代质量
- [x] Sprint 2 红队、端到端、迁移、浏览器与试点启动清单冻结

**Implementation slices**

- [x] S2-7a：增加质量遥测与按输出类型的确定性自动收窄
- [x] S2-7b：把拆除演练与红队边界验证接入 CI 旁路脚本
- [x] S2-7c：建立只读 golden-case 修正积累/人工晋级流程与回归门禁
- [x] S2-7d：Dashboard 呈现接受率、采取行动数与收窄状态
- [x] S2-7e：完成 Sprint 2 端到端验收、试点启动清单与完整质量门禁

**Completion evidence（2026-08-12）**

- migration `0014_finding_quality_controls` 建立租户内 Agent + Finding type 质量控制；口径只统计已人工裁决样本，默认至少 5 条后才以 50% 阈值收窄，收窄状态 sticky，恢复必须人工处置。
- Review/Apply 同事务刷新质量遥测；Dashboard AI Brief 显示接受率、人工裁决分母、实际 Apply 数与已收窄类型数，Finding 产量未作为成功指标。
- 应用面与受限 `pdos_agent` 的 `create_agent_finding` 双重阻断 narrowed 类型；其他类型和 Agent 仍可运行，避免粗暴停掉整份订阅。
- `make sprint2-removal-drill` 已进入 CI 旁路：清除全部模型凭据后模型目录为空、Chat 降级、Finding 数不变且 provider 调用为 0；Dashboard 的真实浏览器降级态已在 S2-6 验证。
- `server/golden/correction-candidates/`、人工学习环 runbook 与静态门禁建立；运行时无任何 golden 根写接口，评测脚本仍只生成报告且不自动发布资格。
- Sprint 2 试点 runbook 已冻结入选、启动、停止与观测口径。真实 1–2 个项目的选择保留为 Sprint Exit 人工决策，不由 Agent 自行挑选或改变生产状态。

## Sprint 2 Exit Gate — Awaiting explicit human confirmation

- [ ] 汇报 Sprint 2 验收结果
- [ ] 由人选择 1–2 个真实双跑项目并填写 `docs/runbooks/sprint-2-pilot.md`
- [ ] 获得人明确确认后才进入 Sprint 3
