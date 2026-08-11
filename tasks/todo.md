# Current Work Queue

> 唯一当前指针：**S1-6 前端第一版。** S1-5 已于 2026-08-11 完成全部验收；下一项按计划交付 Dashboard 骨架与 Project Workspace 五标签。
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

## Current: S1-6 Frontend First Version

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
- [ ] S1-6b：重构 Project Workspace 为五标签，交付 Overview 汇总、Timeline 与角色感知的三类工作项界面
- [ ] S1-6c：将登录后首页替换为 Portfolio/Risk 双卡 Dashboard，并按权限处理风险聚合与失败态
- [ ] S1-6d：完成聚焦测试、完整门禁、Requirement→Case→Project→Task/Issue 浏览器闭环及双主题响应式验收

**Acceptance evidence required**

- [ ] 登录后默认进入 Dashboard；Portfolio 展示可见项目的状态、当前阶段与进度，Risk 按 score 降序汇总且可回到对应项目
- [ ] Project Workspace 精确显示五标签；Overview 数量与三类列表一致，Timeline 正确渲染七阶段
- [ ] Task 明确区分 status 与 readiness，依赖未完成显示 waiting 而非 blocked；显式 blocked 动作必须填写原因
- [ ] Issue/Risk 仅呈现服务端冻结状态图允许的下一动作；创建与动作成功后局部数据刷新，失败显示行内可重试错误
- [ ] Supplier/Customer 无 Task/Issue/Risk 标签或网络请求；内部只读/可写边界与服务端 RBAC 一致
- [ ] 页面具备 loading/empty/error 状态，在亮暗主题与 320/768/1440px 下无横向溢出，键盘可达且控制台零 warning/error
- [ ] web/server tests、lint/type/build、Alembic 单 head 与 Sprint 1 真实业务闭环全部通过
