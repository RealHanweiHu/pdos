# Current Work Queue

> 唯一当前指针：**六 Sprint 建设与 Sprint 5 / Cutover Exit 已于 2026-08-14 经 Data Owner、发布 Owner、业务 Owner 共同确认完成。** S5-1 真实身份/外发 smoke 作为已接受延期残余风险继续单独跟踪，canonical checkbox 保持未勾选，生产 `delivery=false`；当前没有待执行的主计划工作项。
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

## Completed: Sprint 2 Exit Gate

- [x] 汇报 Sprint 2 验收结果；生产部署与人工 smoke 证据见 `docs/reports/2026-08-12-sprint-2-production-deployment.md`
- [x] 只读盘点现役 CEHub 的 4 个未归档项目，并在 `docs/runbooks/sprint-2-pilot.md` 记录未选中候选与建议
- [x] 由人选择 C4s 与 S18-01 两个真实双跑项目，并填写 `docs/runbooks/sprint-2-pilot.md`
- [x] 获得人明确确认，进入 Sprint 3（2026-08-12）

## Completed: S3-1 Specification + Development BOM 三型

**Definition of Ready**

- [x] 规格出处：`PostgreSQL_Schema_Design.md`、`Product_Flow.md`、`System_of_Record_Matrix.md`、`RBAC_and_Audit.md` 与 canonical S3-1
- [x] 依赖项：Sprint 2 出口已确认；Project、Event/Audit、RBAC 与人工写路径已就绪
- [x] 范围冻结：Specification + EBOM / Prototype BOM / Cost BOM；MBOM/Routing 仅保存 ERP 引用，不成为 PDOS SoR
- [x] 下一迁移号冻结为 `0015`，单调递增且不复用

**Implementation slices**

- [x] S3-1a：从冻结规格提取 Specification/BOM 字段、关系、SoR 与 RBAC 契约，建立会失败的迁移/模型契约测试（RED：metadata/0015 缺失；另发现本地测试库凭据与现存容器不一致）
- [x] S3-1b：migration 0015 建立 Specification、BOM 与 BOM Item 数据边界、租户完整性和 ERP 引用约束；聚焦 schema/往返/drift/lint/type 全绿
- [x] S3-1c：实现 Specification 与三型 BOM 的服务/API 写读路径，写操作同事务产出事件与审计；15 项聚焦测试及服务端 220 项完整回归全绿
- [x] S3-1d：实现 Project Workspace 中 Specification/BOM 最小纵向界面与同源 BFF；三型语义、ERP 引用边界、内部读写/只读/外部零请求、loading/empty/error/retry 均有测试，web 95 项与生产构建全绿
- [x] S3-1e：完成聚焦测试、迁移往返、完整门禁和真实 API/浏览器路径验收

**Acceptance evidence required**

- [x] 同一项目可建立 Specification 与 EBOM / Prototype BOM / Cost BOM，三型语义和版本可区分
- [x] PDOS 不创建 MBOM/Routing 业务真值；仅允许经过约束的外部 ERP 引用
- [x] 跨租户对象与 BOM 引用 fail-close；所有写入同事务落版本化 event + immutable audit
- [x] migration 0015 downgrade→upgrade 保持单 head/无 metadata drift；完整门禁与运行时路径全绿

**Completion evidence（2026-08-12）**

- migration `0015_specification_boms` 在隔离 `pdos_test` 完成 downgrade→upgrade，唯一 head 为 `0015_specification_boms`；schema/往返/drift 7 项全绿。
- `make check` 全绿：web 95 tests、server 220 tests，ESLint/Ruff/format/mypy/TypeScript/Next.js build/Python compile 全部通过；测试库 fail-close 明确验证为 `pdos_test`。
- 真实本地 HTTP/浏览器闭环在 C4s 测试项目建立 1 个 Specification 与 EBOM/Prototype/Cost 各 1 个；Cost BOM 成本条目 201、同成本写入 EBOM 409、Routing 仅以 ERP reference 201 保存。
- 事件与审计各自形成 `1 Specification + 3 BOM + 1 item + 1 ERP reference` 对称记录；跨租户/外部角色/Quality 只读边界由服务端与前端测试覆盖。
- 隔离 Playwright 会话在 1440/768/320px、亮/暗主题完成验收；320px `scrollWidth == clientWidth == 320`，产品面 11 个交互控件最小高度 44px，控制台 0 error/0 warning。截图位于 `output/playwright/s3-1-product-engineering-*.png`（按 `.gitignore` 不入库）。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| `tables.specifications` 不存在、Alembic head 仍为 0014 | 1 | 预期 RED，进入 S3-1b 实现 0015 与 canonical metadata |
| 本地 `pdos_test` 对 `pdos` 用户报 password authentication failed | 1 | 与业务 RED 分离；只读核对 compose/容器契约后恢复隔离测试库，不修改生产配置 |
| Alembic revision `0015_specification_development_boms` 超过既有 `varchar(32)` | 1 | 事务 DDL 已自动回滚；缩短 revision 为 `0015_specification_boms`，保持迁移号和语义不变 |
| migration check constraint 被 naming convention 二次加前缀，metadata drift 44 项 | 1 | 用 `op.f(...)` 标记完整名称已格式化，保持 migration 与 metadata 同名 |
| 机械替换命令在 `server/` 目录误用了 `server/...` 路径 | 1 | 改用当前目录相对路径 `migrations/...`；原命令未产生文件修改 |
| 完整回归仍断言 Engineer 的旧项目权限清单，未包含新增产品工程权限 | 1 | 同步冻结 HTTP 权限响应契约；聚焦 3 项与服务端完整 220 项测试全绿 |
| S3-1d RED：产品工程 BFF 路由不存在、Workspace 缺产品工程标签与三类状态 | 1 | 实现同源会话 BFF、运行时响应守卫、懒加载容器及可访问面板；15 项聚焦测试转绿 |
| React lint 拒绝 effect 内同步修正规格选择状态 | 1 | 改为从当前规格集派生有效 selection，不再用 effect 镜像 props；lint/typecheck 全绿 |
| migration 往返首次使用了不存在的 0014 revision 名 | 1 | 读取迁移文件确认实际基线 `0014_finding_quality_controls` 后重跑，downgrade→upgrade 与唯一 head 全绿 |
| 首轮 `make check` 捕获旧权限测试列表缩进未格式化，随后又在 `server/` 目录误调用根 Makefile | 1 | Ruff 机械格式化单文件，并回到仓库根目录从头执行完整门禁，全绿 |

## Completed: S3-2 Gate 硬闸与签核

**Definition of Ready**

- [x] 规格出处：`Workflow.md`、`System_of_Record_Matrix.md`、`Event_Catalog.md`、`RBAC_and_Audit.md`、canonical S3-2 与老 CEHub `projectGateSignoffRounds` 成熟语义
- [x] 依赖项：S3-1 已完成；Project/Stage/Gate、Decision、Event/Audit、RBAC 与 Work Item/Risk 真值已就绪
- [x] 范围冻结：NPD v1 三槽签核、轮次快照、就绪度、同事务硬闸、只增不减的项目级加签、历史 Gate grandfather 留痕；不提前实现 S3-5 交付物清单
- [x] 下一迁移号冻结为 `0016`，单调递增且不复用

**Frozen contract**

- Gate 仅有 `preparing / reviewing / approved / rejected` 四态；一个 Stage 对应一个 Gate，新建 Project 原子实例化七个 Gate
- NPD v1 槽位仅为 `product / engineering / quality`；要求为 `required / conditional / not_applicable`，签核为 `pending / approved / conditional / rejected / not_applicable`
- Owner/Admin 可治理并代签；Project Manager 可治理并签 product；Engineer/Quality 仅可签各自专业槽；Supplier/Customer 无 Gate 面
- 打开轮次冻结 policy/requirements/risk snapshot；项目级加签只能提升要求且使当前 open round superseded，不能降级、重复或改历史 Gate
- Approved 决策在持有项目/Gate/轮次锁的同一事务内复核签核、Stage 阻塞任务、Critical Issue 与 16+ Risk，随后写 Gate、Round、Decision、`GATE_APPROVED` 与 audit
- grandfather 仅允许 `approved` 且其 Stage 已早于项目 current Stage 的历史 Gate；它是追加式政策留痕，不参与当前/未来 Gate 的 readiness 绕过

**Implementation slices**

- [x] S3-2a：冻结契约并建立 migration/metadata、状态机、RBAC、竞态与 grandfather 的会失败测试
- [x] S3-2b：migration 0016 建立轮次、签核、项目加签与 grandfather 边界；Project 创建补齐七 Gate，保持 tenant-safe / 单 head / 无 drift
- [x] S3-2c：实现 Gate 查询、开轮、签核、加签、拒绝/复审与同事务 Approved 硬闸；Stage 推进必须由当前 Gate Approved 守门
- [x] S3-2d：完成 API/RBAC/跨租户/事件审计/并发正反例及完整门禁
- [x] S3-2e：完成真实 HTTP 闭环与数据库证据，更新 canonical checkbox 和当前指针

**Acceptance evidence required**

- [x] 七 Stage Gate 可按四态流转；轮次要求和完成时 readiness 快照不可被后续变更重写
- [x] 未满足必签、存在 rejected 签核或确定性阻塞时，Approved 与 Stage 推进均 fail-close；同事务复核关闭 TOCTOU 窗口
- [x] 加签只升不降并产生新轮次；历史 grandfather 追加可追溯，当前/未来 Gate 豁免稳定拒绝
- [x] 跨租户/非成员/不合格签核角色 fail-close；Approved 同事务落 Decision、`GATE_APPROVED` 与 immutable audit
- [x] migration 0016 downgrade→upgrade 保持单 head/无 metadata drift；聚焦测试、完整门禁与真实 HTTP 路径全绿

**Completion evidence（2026-08-12）**

- migration `0016_gate_signoffs` 建立 Gate signoff round/signoff/addition/grandfather 四张 tenant-safe 表；部分唯一索引保证每个 Gate 最多一个 open round，完成轮次冻结 requirements/risk/readiness，downgrade→upgrade 后唯一 head 与 metadata drift 均全绿。
- NPD v1 三槽策略、四态、角色签核边界与只升不降加签已版本化；新建 Project 同事务实例化七个 Gate，Stage 推进对当前 Gate `approved` fail-close。
- Approved 在项目/Gate/轮次/签核与 readiness 真值的统一锁序下复核；Critical Issue、16+ Risk、Stage blocked Task 和未满足签核均阻断。并发双审批仅产生一个 Decision/Event/Audit，readiness 变更与审批序列化，无 TOCTOU 穿透。
- Owner/Admin、PM、Engineer、Quality 的治理/专业槽签核边界通过；Supplier/Customer 零 Gate 面；`pdos_agent` 对新增 Gate 业务表 INSERT 仍被数据库拒绝。
- `make check` 全绿：Web 95 tests、Server 231 tests，ESLint/Ruff/format、TypeScript/mypy 140 source files、Next.js production build 与 Python compile 全部通过。
- 真实本地 TCP API 在 `pdos_test` 完成 setup→开轮→三槽签核→Critical Issue 阻断 409→Approved 200→Stage 推进 200→历史 grandfather 201；当前 Gate grandfather 409，数据库 Decision / `GATE_APPROVED` / `gate.approve` 各 1 条；本地服务随后关闭。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| Gate policy/schema 首次收集缺 `app.domain.gates` | 1 | 预期 RED；实现版本化 NPD v1 策略、0016 metadata 与 migration 后 8 项聚焦测试转绿 |
| 本地 `.env` 仍指向旧 55432，而当前隔离 PG 暴露于 57432 | 1 | 只对测试命令显式覆盖 `TEST_DATABASE_URL`，确认库名 `pdos_test`；未修改用户环境模板或生产配置 |
| grandfather audit 将 Python `None` 序列化为 JSON null，触发 audit SQL NULL 约束 | 1 | 与既有 EventAuditWriter 对齐：仅在快照存在时写列；真实 201 路径与不可变 audit 转绿 |
| 首次全量 pytest 等待结果被误判后重复启动，两个套件并发 TRUNCATE 产生假失败 | 1 | 终止重复本地测试进程、恢复 Alembic head，单实例从头重跑 231 项全绿 |
| 三份旧的未跟踪 `* 2` 源码副本被 TypeScript 纳入编译并使用过期组件契约 | 1 | 未删除；原样移至被忽略的 `output/quarantine/duplicate-source-copies/`，可恢复，正式源码 type/build 转绿 |
| 从仓库根目录直接调用 server venv 的 `uv run ruff` 找不到命令 | 1 | 未产生修改；回到 `server/` 执行格式化，再从根目录跑统一 `make typecheck/check` |

## Completed: S3-3 Build / Sample / Test / Certification

**Definition of Ready**

- [x] 规格出处：`PostgreSQL_Schema_Design.md`、`System_of_Record_Matrix.md`、`Event_Catalog.md`、canonical S3-3 与老 CEHub Sample/Test/Certification 成熟语义
- [x] 依赖项：S3-2 已完成；EVT/DVT/PVT Stage/Gate、Project 锁序、Event/Audit、RBAC 与产品工程对象已就绪
- [x] 范围冻结：Build 批次、样机序列号与谱系、Sample 签核、Test 计划/用例/报告、Certification 台账与到期扫描；不提前实现 S3-5 交付物清单或 S3-6 前端
- [x] 下一迁移号冻结为 `0017`，单调递增且不复用

**Frozen contract**

- Build 只能绑定项目的 EVT/DVT/PVT Stage；序列号在租户内唯一，Sample 必须属于同项目 Build，父样机谱系不可自指或成环，Prototype BOM 引用必须同项目且类型正确
- Sample 签核受 `internal / supplier / customer` audience 限制；外部角色只能看到并响应自身 audience，响应形成不可覆盖的 actor/time 留痕
- Test Plan 绑定 EVT/DVT/PVT；Test Case 的 `failed` 转换与 `TEST_FAILED`、audit 同事务，事件 payload 使用冻结的 `test_record_id + severity`，由既有 dispatcher 喂 Project Intelligence/Quality 观察面
- Test Report 只有 Quality/治理角色可完成 review；Gate 只接受 approved 且结果为 pass/conditional 的报告，failed/blocked Test Case 始终是确定性阻塞
- EVT/DVT/PVT Gate 要求对应 completed Build、至少一个 Sample、合格 Test Report 且已创建的 Sample 签核全部闭环；PVT 另要求全部 `is_required` Certification 当前有效
- Certification 扫描以显式 `as_of` 日期确定性运行；valid 且过期的证书转 expired，90/30/0 天提醒按证书有效期和 lead day 幂等去重，不依赖 LLM

**Implementation slices**

- [x] S3-3a：建立 migration/metadata、状态机、谱系、RBAC、事件与 Gate 联动的会失败测试
- [x] S3-3b：migration 0017 建立 Build/Sample/Test/Certification tenant-safe 数据边界与受限 Agent 零写边界
- [x] S3-3c：实现 Build/Sample/Sample Signoff/Test/Certification 服务与 API，写路径同事务 event + audit
- [x] S3-3d：把 NPI 事实接入 Gate readiness，并实现幂等证书到期扫描与并发/跨租户负例
- [x] S3-3e：完成迁移往返、聚焦/完整门禁、真实 HTTP 与数据库事件审计证据，更新 canonical checkbox 和当前指针

**Acceptance evidence required**

- [x] EVT/DVT/PVT 批次可建立租户隔离的样机序列号与无环谱系，跨项目/BOM 引用 fail-close
- [x] Sample audience 与响应权限正确；测试失败同事务产出唯一 `TEST_FAILED`，失败/阻塞测试阻断 Gate
- [x] 合格报告、批次/样机、签核及 PVT 证书真值全部在 Gate 决策事务内复核，无 TOCTOU 穿透
- [x] 到期扫描可重复执行且不重复提醒；过期/撤销的必需证书不能通过 PVT Gate
- [x] migration 0017 downgrade→upgrade 保持单 head/无 metadata drift；聚焦测试、完整门禁与真实 HTTP 路径全绿

**Completion evidence（2026-08-12）**

- migration `0017_npi_quality` 建立 10 张 tenant-safe NPI 表：Build/Sample 位于 `cehub_product`，Sample Signoff/Test/Certification 位于 `cehub_quality`；downgrade→upgrade、唯一 head 与 metadata drift 全绿。
- Build 只绑定 EVT/DVT/PVT Stage；批次数量限制、租户唯一序列号、同项目 Prototype BOM、不可变父样机谱系及跨项目引用均 fail-close。Sample Signoff 对 Supplier/Customer 仅暴露自身 audience，并只允许一次响应。
- Test Plan/Case/Report 完成执行与 QA review 边界；`failed` 在同事务写唯一 `TEST_FAILED` 与 audit，既有 dispatcher 可消费。failed/blocked Case、缺 Build/Sample/合格报告、未闭环 Signoff 与 PVT 无效必需证书均进入 Gate 实时/审批事务 readiness。
- Certification 以显式 `as_of` 确定性扫描；90/30/0 天提醒按证书+有效期+lead day 幂等，过期状态、提醒、event/audit 同事务。首次 30 天扫描创建 1 条，重放创建 0 条，越过有效期后首次转 expired、再次扫描 0 变更。
- `pdos_agent` 对新增 Build 业务表真实 INSERT 被拒；Supplier 创建 Build 返回 403；项目锁序使 NPI 写与 Gate 审批串行复核，未开放 Agent 业务写出口。
- `make check` 全绿：Web 95 tests、Server 235 tests，ESLint/Ruff/format、TypeScript/mypy 144 source files、Next.js production build 与 Python compile 全部通过。
- 真实本地 TCP API 在 `pdos_test` 完成 setup→Build→Sample→Supplier Signoff→Test failed→报告 review→Build completed→重测 passed→Certification→扫描重放；failed blocker 可见，重测后仅剩 `round:not_open`，`TEST_FAILED` 恰好 1 条且全部 NPI event/audit 对称；本地服务随后关闭。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| 首个 S3-3 端到端测试命中 NPI 路由 404 | 1 | 预期 RED；实现 NPI service/router 并注册到 FastAPI 后纵切转绿 |
| `test_cases.related_issue_id` 初版三列 FK 缺少 Issue 对应唯一键 | 1 | 在 0017 单调迁移中补 `uq_issues_tenant_project_id`，保持项目级 tenant FK 可证明 |
| 新增 join/alert 表的直接 Tenant FK 在已处于 0017 的本地库产生临时 drift | 1 | 完善 0017 后执行 downgrade→upgrade 重建隔离库；metadata drift 归零 |
| audit snapshot 内的 UUID 列表无法 JSON 序列化 | 1 | 将 snapshot normalizer 扩展为递归处理 UUID/date/list/dict，事件与审计恢复原子写入 |
| PostgreSQL `ON CONFLICT DO NOTHING` 的 psycopg rowcount 为 -1 | 1 | 改用 `RETURNING id` 判断是否真实插入，证书提醒幂等计数稳定为 1→0 |

## Completed: S3-4 变更链后段

**Definition of Ready**

- [x] 规格出处：`Workflow.md`、`System_of_Record_Matrix.md`、`PostgreSQL_Schema_Design.md` 与 canonical S3-4
- [x] 依赖项：S3-1 Development BOM、S3-2 Gate/Decision、S3-3 PVT readiness 已完成
- [x] 范围冻结：ECR→影响分析→人工审批→ECN→人工生效决策→ERP Handoff 状态就位；S5 前不执行 ERP outbox/发送/重放/对账
- [x] 下一迁移号冻结为 `0018`，单调递增且不复用

**Frozen contract**

- ECR 状态为 `request → impact_analysis → approval → approved/rejected`，可在前三态人工取消；影响 BOM 采用 tenant/project-safe 关系表，不以不可信 JSON 代替引用
- ECR 申请人不得审批自己的申请；批准/拒绝同事务写 Decision、change event 与 immutable audit
- 仅 approved ECR 可一对一生成 ECN；ECN 状态为 `ecn → effectivity_decision → erp_handoff`，生效拒绝则进入 cancelled
- 生效批准必须选择同项目 EBOM，冻结 BOM header/items snapshot，并同事务创建 effectivity Decision 与 `pending` ERP Handoff
- Handoff 状态预留 `pending / ready / queued / sent / confirmed / failed`；S3-4 只允许 pending→ready，且必须 PVT Gate approved；queued 及之后由 S5 执行体拥有

**Implementation slices**

- [x] S3-4a：以测试冻结 ECR/ECN/Handoff schema、状态机、四眼审批与 SoR 边界
- [x] S3-4b：migration 0018 建立 tenant-safe ECR、影响 BOM、ECN 与 Handoff 数据边界
- [x] S3-4c：实现变更服务/API、Decision/event/audit 原子路径与 RBAC/跨租户负例
- [x] S3-4d：实现 Frozen EBOM snapshot、PVT Gate→Handoff ready 硬闸及 S5 状态所有权阻断
- [x] S3-4e：完成迁移往返、完整门禁与真实 HTTP 变更闭环，更新 canonical checkbox 和当前指针

**Acceptance evidence required**

- [x] ECR 影响分析只能引用同项目 BOM；申请人自审 fail-close，批准/拒绝形成独立 Decision
- [x] approved ECR 才能一对一生成 ECN；生效批准只接受同项目 EBOM，并冻结 header/items 快照
- [x] PVT Gate 未 approved 时 Handoff `pending→ready` 被硬阻断；S3 无 queued/sent/confirmed 写入口
- [x] 变更写入同事务落 `CHANGE_RECORD_CHANGED` 与 immutable audit；`pdos_agent` 对新增业务表零写
- [x] migration 0018 downgrade→upgrade 保持单 head/无 metadata drift；完整门禁与真实 TCP HTTP 路径全绿

**Completion evidence（2026-08-12）**

- migration `0018_change_governance` 建立 ECR、受影响 BOM 关系、ECN 与 ERP Handoff 四张 tenant/project-safe 表；唯一 head、metadata drift 和迁移往返全绿。
- ECR 固化 request→impact_analysis→approval→approved/rejected；申请人自审返回 409，Manager 独立审批同事务写 Decision、change event 与 audit。仅 approved ECR 可一对一创建 ECN。
- ECN 生效决策对 Prototype BOM 返回 409，只接受同项目 EBOM；批准时冻结 BOM header 与有序 items，并创建 pending Handoff。PVT Gate 未批准时 ready 返回 409，批准后 ready 200。
- Sprint 5 所有权边界已实证：没有 queue API，`/queue` 返回 404；预留 queued/sent/confirmed/failed 仅为后续执行体状态，不由 Sprint 3 业务入口写入。
- `pdos_agent` 对 ECR 真实 INSERT 被数据库拒绝；CHANGE event/audit 在端到端闭环各 9 条且对称。
- 显式隔离库执行 `make check` 全绿：Web 95 tests、Server 238 tests，ESLint/Ruff/format、TypeScript/mypy 148 source files、Next.js production build 与 Python compile 全部通过。
- 真实本地 TCP API 完成 setup→ECR→影响分析→四眼审批→ECN→生效决策→Frozen EBOM→Handoff；自审/非 EBOM/PVT 未批均 409，PVT 批准后 ready 200，服务随后关闭。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| Alembic 状态复核首次未显式设置 `DATABASE_URL` | 1 | 按测试隔离纪律显式指向 `pdos_test@57432`，未修改用户环境文件 |
| 初次全仓 `make check` 读取 `.env` 的旧 55432，后端统一连接失败 | 1 | 确认 lint/type/web 全绿且错误同源后，以 `TEST_DATABASE_URL`/`DATABASE_URL` 显式覆盖 57432 从头重跑，238 项全绿 |
| 自动生成 migration/schema 的长约束字符串未通过 Ruff E501 | 1 | 仅拆分 Python 字符串字面量，不改变 SQL 约束语义；Ruff、drift 与往返测试全绿 |

## Completed: S3-5 检查项资产库

**Definition of Ready**

- [x] 规格出处：canonical S3-5、`System_of_Record_Matrix.md` 与随仓库资产 `assets/cehub/deliverable-guide-manifest.json`
- [x] 依赖项：S3-2 Gate/Stage 已完成；S3-4 已完成且完整门禁全绿
- [x] 资产事实：manifest schemaVersion=3，含 2 个模板版本，deliverables 为名称索引对象，合计恰好 687 条 checkItems
- [x] 范围冻结：直接消费 JSON manifest，不解析或反推 xlsx；绑定 projectType/phase/isGate，并接入 Gate 确定性 readiness
- [x] 下一迁移号冻结为 `0019`，单调递增且不复用

**Implementation slices**

- [x] S3-5a：冻结 manifest 校验、687 条完整性、稳定 ID/绑定/硬闸语义与导入幂等契约
- [x] S3-5b：migration 0019 建立版本化检查项模板与项目实例/完成证据的 tenant-safe 数据边界
- [x] S3-5c：实现直接导入器、项目实例化与查询/完成 API，保持 event/audit 和 RBAC 边界
- [x] S3-5d：将 isGate 未完成项接入对应 Stage Gate readiness，验证非硬闸项不阻断
- [x] S3-5e：完成迁移往返、完整门禁与真实 HTTP 验收，更新 canonical checkbox 和当前指针

**Acceptance evidence required**

- [x] JSON asset 直接解析为恰好 687 个稳定唯一检查项；720 个 binding 与 131 个 isGate binding 完整保留
- [x] 模板导入按 tenant 幂等且 content hash 漂移 fail-close；项目实例按 projectType/Stage 绑定且重放零重复
- [x] 硬闸项 pending/not_applicable 均阻断对应 Gate，completed 必须有证据；非硬闸项可带理由 not_applicable 且不阻断
- [x] 读取/治理/完成权限、跨租户与数据库 tenant/project/stage FK fail-close；`pdos_agent` 零业务写
- [x] migration 0019 往返保持单 head/无 metadata drift；完整门禁与真实 TCP HTTP 路径全绿

**Completion evidence（2026-08-12）**

- 直接读取 `deliverable-guide-manifest.json`，确认 schemaVersion 3、模板版本 2 个、687 个唯一 checkItems、720 个 bindings、131 个 isGate bindings；99 个无 binding 条目仍完整进入模板库，不被丢弃。
- migration `0019_deliverable_checks` 建立 tenant 级版本化模板与 project/workflow/stage 绑定实例；content hash 防止同 key 静默漂移，项目唯一约束和 PostgreSQL conflict handling 保证导入/实例化重放幂等。
- NPD 七阶段实例化 282 项，其中 44 项硬闸；Concept 阶段 6 个硬闸 blocker 可见。完成一项必须提供 evidence，blocker 6→5；硬闸 not_applicable 409，非硬闸带理由 not_applicable 200。
- 模板导入、项目实例化、完成/豁免均同事务落 `DELIVERABLE_CHECK_CHANGED` 与 immutable audit；真实闭环 event/audit 各 4 条；`pdos_agent` 对 project_check_items INSERT 被数据库拒绝。
- `make check` 全绿：Web 95 tests、Server 242 tests，ESLint/Ruff/format、TypeScript/mypy 152 source files、Next.js production build 与 Python compile 全部通过。
- 真实本地 TCP API 完成 setup→687 模板导入→NPD 282 项实例化→幂等重放 0 新增→Gate blocker→证据完成→非硬闸豁免；服务随后关闭。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| 首轮资产校验假设每个检查项都必须有 binding，但 manifest 有 99 个库级未绑定项 | 1 | 修正为 687 条全部入模板库、仅明确绑定项实例化；720 binding/131 gate 计数锁入测试 |
| 聚焦组合中 initial-schema 全链降级遇到前序安全测试遗留的非 risk Finding | 1 | 确认 0012 有数据拒绝损失降级的保护正确；仅清空显式 `pdos_test` 后分别重跑，全链往返和完整套件均绿 |

## Completed: S3-6 前端 Gate / Document

**Definition of Ready**

- [x] 规格出处：canonical S3-6、UI baseline v0.2、`Workflow.md` 与 S3-2/S3-5 已冻结 API
- [x] 依赖项：Gate readiness/签核与 687 检查项库已完成；现有 Project Workspace 有 Overview/Tasks/Issues & Risks/Product Engineering/AI Chat
- [x] 范围冻结：增加 Gate 与 Document 标签；Gate 默认只显缺项/风险，完整材料按需展开；不提前实现 OCR 或 S4 能力

**Implementation slices**

- [x] S3-6a：建立同源 BFF 与 runtime guard，覆盖 Gate/Document loading/empty/error/retry/RBAC
- [x] S3-6b：实现例外优先 Gate readiness、阶段切换、材料清单按需展开与可访问状态
- [x] S3-6c：实现 Document 列表/上传入口，沿用 S2 私有对象存储与抽取状态
- [x] S3-6d：完成组件测试、真实浏览器桌面/移动/双主题与 console 验收
- [x] S3-6e：完成完整门禁，更新 canonical checkbox 和当前指针

**Acceptance evidence required**

- [x] Project Workspace 内部成员可见 Gate/文档标签；外部成员零请求、零标签
- [x] Gate 默认仅呈现首个例外与总数，其余材料按需展开；加载失败不伪装成零缺项
- [x] 文档列表只暴露安全元数据/抽取状态，不含 object key；上传仅接受 PDF/XLSX 并沿用 S2 私有存储链
- [x] 同源 BFF 只转发 HttpOnly session bearer，项目 ID 编码、无会话/错误路径 fail-close
- [x] 桌面/320px、亮/暗主题无横向页面溢出，交互控件 44px，console 0 error/0 warning；完整门禁全绿

**Completion evidence（2026-08-12）**

- Project Workspace 从 7 个内部标签扩展为 9 个，新增 Gate 与文档；外部 Supplier/Customer 仍仅见概览/时间线，组件测试保持零工程请求。
- Gate 面按阶段展示缺项总数，详情默认只渲染首项，用户显式展开其余材料；error/retry 与 empty 状态分离。真实 Concept Gate 7 个例外中 6 个来自检查项资产，完整展开可见。
- Document 面增加安全列表 API、同源 BFF、PDF/XLSX 上传与 internal/confidential/restricted 密级选择；响应不暴露对象存储键，空库、loading、error/retry 和 OCR-required 状态均有明确文案。
- `make check` 全绿：Web 99 tests、Server 242 tests，ESLint/Ruff/format、TypeScript/mypy 152 source files、Next.js production build 与 Python compile 全部通过。
- Playwright 真实浏览器在 1440px 亮主题与 320px 暗主题完成 Gate/Document 验收；320px `scrollWidth == clientWidth == 320`，全部可见按钮/标签高度至少 44px，console 0 error/0 warning。截图位于 `output/playwright/s3-6-*.png`（忽略不入库）。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| 首次 Playwright wrapper 命令把同一行临时变量当作已展开路径，得到空命令 permission denied | 1 | 改用明确 wrapper 绝对路径并保持命名 session，后续真实浏览器流程全绿 |

## Completed: S3-7 迁移工具 v1

**Definition of Ready**

- [x] 规格出处：canonical S3-7、SoR/RBAC/Project/Gate 既有模型与生产迁移纪律
- [x] 依赖项：User/Project/Task/Gate/Document 目标模型已就绪；同 RDS 实例跨库只读源账号属于人执行配置
- [x] 范围冻结：CEHub projects→Project、project_tasks→Task、Gate 历史→Gate、users→User、文件→OSS 引用；dry-run + 幂等 + 抽查报告
- [x] 安全边界：工具不创建 RDS 账号、不改生产连接、不复制文件正文；真实生产运行必须另行人确认

**Implementation slices**

- [x] S3-7a：冻结源快照契约、字段映射、稳定 external key、dry-run 与错误报告格式
- [x] S3-7b：实现只读源 adapter、目标幂等 upsert 与事务/批次边界
- [x] S3-7c：实现 User/Project/Task/Gate/File-reference 映射及跨实体引用解析
- [x] S3-7d：建立合成 CEHub 源库正反例、重放 0 重复、dry-run 0 写与抽查一致性测试
- [x] S3-7e：交付运行手册，完成 migration 往返、metadata drift 与完整本地门禁
- [x] S3-7f：经人授权配置 CEHub 只读账号，对 C4s / S18-01 执行正式 dry-run→apply→重放与数据 Owner 抽查
- [x] S3-7g：真实试点一致后更新 canonical S3-7，并汇报 Sprint 3 Exit Gate 等待人工确认

**Local completion evidence（2026-08-12）**

- migration `0020_cehub_migration_v1` 建立 `migration_runs` / `migration_mappings` 审计边界、完整 Gate 历史与外部 OSS 文件引用；downgrade→upgrade、单一 head 与 metadata drift 全绿。
- 源 adapter 在 `REPEATABLE READ` 事务中强制 `SET TRANSACTION READ ONLY`，且要求显式项目 ID 或唯一项目编号；报告与审计统一固化解析后的真实源 ID。v1 接受 NPD 七阶段与 OBT `intake/sample/pvt/mp` 四阶段，未知类型/状态/引用、目标冲突和源行漂移全部 fail-close。
- 旧账号只迁移身份且默认禁用，不复用密码哈希；每个项目按源类型实例化独立版本化 Workflow/Stage/Gate，OBT 使用独立 `obt-gate-v1` 策略，Gate 全轮历史保留，文件只保留旧 OSS 引用而不复制正文或伪装成新文档。
- 合成 CEHub 源库完成 S18-01 形态验收：2 User、1 Project、2 Task、2 Gate review、1 File reference；dry-run `target_writes=0`，apply 建立 8 个稳定映射，第二次 apply 五类 created 均为 0，修改已迁移源行后 `SOURCE_CHANGED` 阻断。
- CLI 强制 `--dry-run` / `--apply` 二选一、至少一个 `--project-id`、源/目标数据库名不同；JSON 报告不输出连接串，落盘权限为 `0600`。运行手册见 `docs/runbooks/cehub-migration-v1.md`。
- 显式隔离库执行 `make check` 全绿：Web 99 tests、Server 276 tests，ESLint/Ruff/format、TypeScript/mypy 160 source files、Next.js production build 与 Python compile 全部通过；新增覆盖 ID/项目编号解析、NPD+OBT 双项目 11 Stage/Gate、OBT Gate 开轮、DML/REFERENCES/TRIGGER 任一非只读权限 fail-close、Prisma-only URL 参数兼容、同一项目 EVT→DVT→PVT/ECN 出口纵向闭环，以及 Git bundle/源码漂移/镜像 revision 发布契约。
- intended-vs-implemented 审计补齐 canonical 冻结但仓库缺失的 `scripts/deploy-ecs.sh`：生产入口分为 preflight/build/deploy/status/rollback，deploy/rollback 均要求与 git SHA 绑定的人工确认；固定执行 migration→Agent 最小权限重施加/验证→无依赖运行服务→本机/公网健康与限时日志扫描，回滚不运行旧迁移器或数据库 downgrade。API 候选镜像以本地缓存的同版本基础镜像真实构建成功，非 root UID、内置 SQL 与两个 CLI 入口 smoke 通过。
- S5-1 release 冻结审计从干净 Git bundle 执行真实 `deploy-ecs.sh build`，发现 `env -i` 漏传 `USER` 会令 Docker Desktop credential helper 在固定摘要镜像解析前失败；入口现显式保留最小 `USER`/`LOGNAME` 身份变量并有发布契约回归，未继承业务密钥或放宽生产确认门禁。
- S3-7 apply 已与人审 dry-run 真值绑定：CLI 要求完整获批 `source_fingerprint`，并以租户+fingerprint+有序项目选择器生成二次确认口令；源快照变化在目标写入前以 `SOURCE_SNAPSHOT_NOT_APPROVED` 阻断。生产入口同时验证同一批准 RDS、独立账号、异库与 verify-full/固定 CA；报告以原子 `0600` 文件落盘并拒绝 symlink，消除先写后 chmod 窗口。
- 生产发布输入已绑定不可伪装的 Git 对象：本地只从 `HEAD` 生成并复核 `pdos-<40位SHA>.bundle`，ECS 必须在独立 bare repository 验证 bundle 后 clone 到全新目录；deploy 会核对 Git HEAD、拒绝除 `.env.production` 外的 tracked/untracked/ignored 漂移，并复核 API/Web 镜像的 OCI revision 等于同一 SHA。首轮旧镜像回滚额外绑定 API/Web image ID，迁移报告移到 release 工作树之外。两个候选镜像已完成真实 label inspect，聚焦 24 tests 与完整门禁全绿。

**Human-authorized production gate（completed）**

- 经人授权，生产 PDOS 已从 `0014_finding_quality_controls` 升级到 `0020_cehub_migration_v1`；迁移后四个现有服务容器保持 healthy、restart count 0，公网登录入口返回 HTTP 200。应用镜像未在本步骤重部署。
- 真实源库只读预检确认 `C4s` / `S18-01` 是项目编号，真实源 ID 分别为 `zGpNH0Xq` / `aBnbEdQG`；C4s 为 OBT/intake，S18-01 为 NPD/concept。导入器已据此补齐选择器解析和 OBT 契约测试。
- 经人授权已创建独立角色 `pdos_cehub_readonly` 并写入生产私有执行环境：默认事务只读、五表 SELECT-only、无高权限/角色继承，四项变量各唯一一份，`.env.production` 保持 `0600`；真实源连接、active `beepump` 租户与 `admin` Owner 操作人均验证通过。
- `e1d0b2aaaff1ef9cf0b49e27f59464554aac80e3` 候选已由完整 Git bundle 在 ECS 独立 release 中验证；Linux/amd64 API 与 Web OCI revision、非 root runtime、production preflight 均通过，未替换线上容器。
- C4s / S18-01 正式生产 dry-run 已通过：fingerprint `d37ac192c4c318b540f6beb74d3340ee8bbfd04f7776f4f0f1112b1760abe71d`，5 User / 2 Project / 53 Task / 0 Gate Review / 10 File Reference，`target_writes=0`、errors 为空。独立源五表抽查一致，目标 11 表前后 count+内容 SHA-256 完全相同，证据见 `docs/reports/2026-08-12-s3-7-production-dry-run.md`。
- 数据 Owner 明确绑定 release `e1d0b2aaaff1ef9cf0b49e27f59464554aac80e3`、上述 fingerprint、目标租户与有序选择器批准 apply。首次 apply 创建 5 User / 2 Project / 53 Task / 0 Gate Review / 10 File Reference；独立目标审计验证 70 条 mapping 的目标均存在、用户默认禁用、项目结构/任务/文件样本与源抽查一致。
- 原参数幂等重放五类 created 全为 0、skipped 与源计数完全相等，`target_writes=1` 仅新增成功运行审计；十张业务/映射表 count 与内容 SHA-256 均未改变，Migration Run 从 1 增为 2，Mapping 保持 70。线上容器 ID 未变、restart count 0、全部 healthy，公网登录 HTTP 200。证据见 `docs/reports/2026-08-12-s3-7-production-apply.md`。
- 迁移器已增加源角色硬校验：`default_transaction_read_only=on`、五表全读、五表 DML/REFERENCES/TRIGGER 零权限缺一不可；可写应用账号或仍持有表级非 SELECT 权限的账号在任何项目快照读取前即被拒绝。运行手册提供 DBA 最小授权 SQL 模板。
- 真实 CEHub URL 的 Prisma-only `uselibpqcompat` 参数已在迁移源连接入口定点移除，`sslmode` 等真实 PostgreSQL 参数保持不变；避免只读账号就绪后被 psycopg 连接参数阻断。
- `c39b2b4` 候选已只读上传 ECS；对真实 CEHub 现役可写账号的负向 smoke 先成功完成 URL 规范化，再在任何项目快照读取前返回 `blocked_write_capable_role`。未连接目标 PDOS、未写生产数据、未替换运行容器。
- Sprint 3 intended-vs-implemented 出口审计发现并补齐“同一项目 EVT→DVT→PVT + 硬闸 + 一次 ECN”的跨模块证据：新增真实 FastAPI 纵向验收，终态为 EVT/DVT/PVT 三 Gate approved、恰好 1 个 ECN、Handoff ready、当前 Stage=MP；出口报告见 `docs/reports/2026-08-12-sprint-3-exit-draft.md`。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| 首轮 TDD 导入不存在的 `app.migrations` | 1 | 预期 RED；补冻结映射、只读 source adapter 与原子 target importer 后转绿 |
| 合成 Gate review 首条 fixture 少一个 `createdBy` 值 | 1 | 修正测试数据列值对齐，随后完整映射/重放/漂移用例全绿 |
| 首次全仓门禁命中新测试单处 Ruff 格式差异 | 1 | 使用项目格式化器修正并从头重跑 |
| 前端 `.next/types` 有带 ` 2` 后缀的重复缓存，清理后 tsbuildinfo 仍引用旧路径 | 2 | 将 `.next` 与 `tsconfig.tsbuildinfo` 移至 `/tmp` 可恢复位置，重新生成后 type/build 全绿；未改源码 |
| 真实试点使用项目编号而非主键，且 C4s 为 OBT 四阶段 | 1 | 选择器改为 ID/唯一项目编号双解析，审计固化真实 ID；新增 OBT Workflow 与 `obt-gate-v1`，双项目合成验收覆盖 11 Stage/Gate |
| 固定摘要基础镜像的 registry 元数据在本机无响应 | 1 | 终止无进展构建后，以本机缓存的相同版本 tag、`--pull=false` 重跑 Dockerfile；新增 SQL COPY、非 root 用户和 CLI 入口均完成真实镜像 smoke，正式发布仍使用 Compose 中冻结的摘要 |
| 全仓门禁首次 TypeScript 检查在旧 `.next` 缓存上静默且 CPU 为 0 | 1 | 中止停滞进程，把生成缓存移动到 `/tmp` 可恢复目录后单独 typecheck 通过；再从头执行完整 `make check`，276/99 tests 与 build 全绿 |
| 正式生产 dry-run 读取真实 `project_tasks` 时命中不存在的 `blocked_reason`，并发现 `project_files.securityClassification` 同样不在真实 schema | 1 | 只读固化五表列契约；缺失任务原因固定投影为 NULL，文件密级改由真实 `visibility` 同名白名单映射且未知值 fail-close；合成源 fixture 改为真实列形态后迁移/重放/漂移回归转绿 |
| 首次生产重放二次确认串漏填 fingerprint | 1 | 安全闸在数据库连接/写入前拒绝；未创建报告、未产生目标写入。改用人工批准绑定的完整租户+fingerprint+有序选择器确认串后重放通过 |

## Completed: S4-1 CAPA 正式链

**Definition of Ready**

- [x] 规格出处：canonical S4-1、质量 schema/SoR、RBAC/Event Catalog 与 Sprint 4 Exit 验收
- [x] 依赖项：Project/Customer/User/Document、Event/Audit、Quality 角色与 `COMPLAINT_CREATED` 注册定义均已就绪
- [x] 预计触达：migration `0021_quality_capa`、schema/domain/API/event tests、Quality 前端与 BFF、运行时验收和文档
- [x] 安全边界：AI 只创建 Finding；质量业务写仅由人工 FastAPI 动作完成，tenant/project/角色/四眼全部服务端绑定并 fail-close
- [x] 质量 Owner 已确认字段、状态机、严重度/来源枚举、四眼规则与有效性关闭门禁；合同见 `docs/design/2026-08-12-s4-1-quality-owner-contract-draft.md`

**Implementation slices**

- [x] S4-1a：质量 Owner 拍板契约，冻结 API/错误码/RBAC 与 migration 0021 验收合同
- [x] S4-1b：Complaint 创建/查询/triage 纵向切片，同事务接通 `COMPLAINT_CREATED` + Audit
- [x] S4-1c：NCR→根因→纠正/预防措施状态机、不可变版本与硬闸
- [x] S4-1d：有效性复核、ineffective 回流、关闭与四眼/治理 override
- [x] S4-1e：Quality Complaint/CAPA 前端与同源 BFF，外部角色零内部数据
- [x] S4-1f：迁移往返/metadata drift、聚焦/完整门禁、真实 HTTP/浏览器链路及错误/越权证据
- [x] S4-1g：完成 DoD、更新 canonical checkbox 和当前指针到 S4-2

**Completion evidence（2026-08-12）**

- Sprint 3 Exit Gate 已经人工确认；`codex/sprint-4` 从确认后的 Sprint 3 终点建立。
- 质量 Owner 已明确回复“确认采用推荐 CAPA 契约”；字段、状态机、枚举、四眼与有效性关闭门禁成为 v1 实施合同。API/RBAC/错误码冻结见 `docs/design/2026-08-12-s4-1-quality-api-contract.md`，后续政策变更必须版本化。
- migration `0021_quality_capa` 在 `cehub_quality` 建立 Complaint、NCR、Root Cause Analysis、CAPA Action、Effectiveness Review 五表；downgrade→upgrade、单一 head 与 metadata drift 全绿。Complaint 的 Document 引用及所有父子关系均由 tenant+project 复合外键和服务端真值复核约束。
- Complaint→Triage/NCR→Containment→不可变根因版本/Quality 四眼批准→Corrective+Preventive（或 Quality N/A）→Action evidence→冻结有效性计划→独立 Quality reviewer→effective close 已闭环；ineffective 会回流 Action，且无新增 follow-up Action 时禁止重复验证。最终 NCR/Complaint 关闭只允许 Quality，Owner/Admin 不可治理越权。
- 所有质量写路径在同一事务写版本化 Event 与不可变 Audit；`COMPLAINT_CREATED` 已接通，状态、根因、措施、有效性与关闭事件均进入目录。真实受限账号验证 `pdos_agent` 对五张新增业务表的 `INSERT` 全部被数据库拒绝。
- Project Workspace 增加内部成员可见的“质量 / CAPA”标签、Complaint 创建/Triage、六步 CAPA 时间线及根因/措施/有效性只读历史；Supplier/Customer 零标签、零请求。同源 BFF 只转发 HttpOnly session bearer，并以精确 allowlist、UUID 与有界 JSON fail-close。
- 完整 `make check` 全绿：Web 104 tests、Server 283 tests，ESLint/Ruff/format、TypeScript/mypy 170 source files、Next.js production build 与 Python compile 全部通过。
- Playwright 真实 Chromium 完成登录→Project Workspace→质量/CAPA→Complaint→Triage/NCR；Web BFF 返回 `201/201/200`，console 0 error/0 warning。数据库复核 1 Complaint、1 NCR，`COMPLAINT_CREATED`、`COMPLAINT_STATUS_CHANGED`、`NCR_CREATED` 三组 Event/Audit 全部同 ID 配对；截图位于 `output/playwright/s4-1-capa-browser.png`（忽略不入库）。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| 全仓首次 mypy 发现测试 JSON helper 返回类型过窄 | 1 | 将测试 helper 明确为有界 JSON 对象类型并 `cast`，聚焦 mypy 与 Ruff 转绿 |
| 完整门禁首次仍有 6 个旧 migration head 快照和 1 个 Engineer action 快照 | 1 | 将 append-only head 更新为 `0021_quality_capa`，补 `quality.view` / `complaint.create` / `capa.execute` 精确期望；14 项回归及完整门禁转绿 |
| Next dev 首次把多余 `--` 解析为项目目录 | 1 | 按仓库 pnpm wrapper 的参数透传规则移除分隔符，临时 API/Web 真实进程随后正常启动 |

## Completed: S4-2 Memory + 向量检索

**Definition of Ready**

- [x] 规格出处：canonical S4-2、Knowledge/Memory 状态机、Context Builder 与租户/项目/状态过滤语义
- [x] 依赖项：S4-1 CAPA 链、Document 抽取、Knowledge Lite draft Finding、pgvector 基础设施与模型治理均已就绪
- [x] 范围冻结：draft→verified→archived；仅 verified 可检索/进入 AI context；embedding provider 可替换，Knowledge Search 独立入口
- [x] 安全边界：tenant/project 范围服务端绑定；未验证 Memory、原文与对象存储键不得进入检索/模型上下文

**Implementation slices**

- [x] S4-2a：冻结数据/API/RBAC/embedding/search/引用契约与错误码
- [x] S4-2b：migration 0022/0023 建立 Memory/Embedding、Finding Apply、四眼状态机、来源/项目边界与 pgvector
- [x] S4-2c：实现人工 draft/edit/verify/archive/reembed 与 Finding/CAPA 来源闭环
- [x] S4-2d：实现可替换 embedding client、verified-only 语义检索与 Agent projection
- [x] S4-2e：接入 `/ai/chat` Memory citation、Knowledge Search API/BFF/独立入口
- [x] S4-2f：完成迁移/安全/完整门禁、真实 HTTP/浏览器与 Sprint 4 纵向证据
- [x] S4-2g：完成 DoD、更新 canonical checkbox 和当前指针到 S4-3

**Completion evidence（2026-08-12）**

- 规格与既有 S2 工具合同共同冻结“只有 verified 进入 Search/Agent/Chat”；Knowledge Lite 只产 `knowledge_draft` Finding，当前 Apply 明确 fail-close，正好作为 S4-2 的受控输入。
- v1 技术合同见 `docs/design/2026-08-12-s4-2-memory-search-contract.md`：项目级、创建/验证四眼、OpenAI-compatible embedding、模型版本留痕与显式 re-embed、无配置不可伪装为空结果。
- migration `0022_memory_search` 与 `0023_memory_finding_apply` 建立项目级 Memory/Embedding、向量索引与 Finding→Memory 受控落地；downgrade/upgrade、单一 head、metadata drift 和初始 schema 快照均通过。
- Memory 完成 `draft→verified→archived` 单向状态机、创建/验证四眼、服务端 tenant/project/source 真值复核与显式 re-embed；只有当前内容哈希、当前 provider/model/dimension 且处于 verified 的记录可进入检索。
- OpenAI-compatible embedding client 固化 provider/model/dimension/content hash，禁用环境代理继承并禁止重定向；缺配置或供应商故障返回明确 unavailable，绝不伪装成空结果，API 不暴露原始向量。
- `cehub_ai.agent_memory_projection` 只投影 verified Memory；受限 `pdos_agent` 可读投影但对 Memory/Embedding 业务表零写。`search_memory` 工具与 `/ai/chat` 均复用服务端项目边界，Chat 命中返回可点击 `/knowledge` 引用。
- Knowledge Search 独立入口、同源 BFF、状态注册表与 AI Review 二次 Apply 已完成；桌面与 390px 移动端无横向溢出，真实 Chromium console 0 error/0 warning。
- 真实浏览器验收在隔离 `pdos_test` 完成：Engineer 创建 draft→检索 0 命中且无 Verify 权限→另一位 Quality 验证→检索 100% 命中并展示 provider/model→归档→再次检索 0 命中；创建/验证/检索/归档 BFF 分别返回 `201/200/200/200`。
- 关闭 NCR 生成 `knowledge_draft` Finding，经人工 Accept 与第二次 Apply 创建 Memory draft，再由不同用户 Verify；`ChatEvidenceRepository` 确认 `/ai/chat` 返回该 verified Memory citation，覆盖 Sprint 4 纵向验收主链。
- 完整门禁全绿：Web 32 files / 110 tests，Server 300 tests；ESLint、TypeScript、Ruff、format、mypy、Python compile 全部通过。Next.js production build 使用 webpack 成功；默认 Turbopack 在受限沙箱因内部进程绑定失败，不属于源码或生产构建错误。

**Errors encountered**

| Error | Attempt | Resolution |
|---|---:|---|
| 本机 `.env` 仍指向旧 PostgreSQL 端口 55432 | 1 | 验收显式绑定 Docker 当前映射 57432 的隔离 `pdos_test`，未修改用户环境文件、未触碰开发/生产库 |
| 本地 embedding stub 被继承的系统代理截获并超时 | 1 | client 固定 `trust_env=False` 且禁用重定向；真实浏览器检索随后完整通过 |
| 全量门禁首先发现初始 schema / Engineer action 快照未包含新增对象 | 1 | 仅追加 Memory 两表及 `memory.draft`/`memory.view` 精确期望，相关聚焦回归与完整门禁均转绿 |

## Completed: S4-3 Phase 2 双 Agent

**Definition of Ready**

- [x] 规格出处：canonical S4-3、AI Runtime Architecture、Event Catalog 与永久 Agent/Finding 安全红线
- [x] 依赖项：Phase 1 runtime、Finding 人审/Apply、BOM/Change、Test/Complaint/CAPA 与 verified Memory 均已就绪
- [x] 范围冻结：Engineering Intelligence 只做 BOM/Change 影响建议；Quality Intelligence 只做 Test/Complaint 聚类与 CAPA 风险建议
- [x] 安全边界：Agent 只写 Finding；二次 Apply 只创建 Risk，不直接改工程或质量 SoR；新增证据只经 lease-bound 投影
- [x] migration：`0024_phase_two_agents`；合同见 `docs/design/2026-08-12-s4-3-phase-two-agents-contract.md`

**Implementation slices**

- [x] S4-3a：冻结 Agent/event/Finding/payload/apply/projection/golden-case 契约
- [x] S4-3b：migration 0024 扩展 Agent/Finding 数据库合同及往返/漂移验收
- [x] S4-3c：增加 Engineering/Quality prompt、静态路由、确定性预检与 golden suite
- [x] S4-3d：增加 lease-bound 工程/质量只读投影、工具与模型 reference 白名单
- [x] S4-3e：接通 dispatcher→executor→Finding→Review→Risk Apply 全链路及受限账号测试
- [x] S4-3f：更新 AI Review 标签并完成真实 HTTP/worker/浏览器验收
- [x] S4-3g：完成全量 DoD、更新 canonical checkbox 和当前指针到 S4-4

**Current evidence（2026-08-12）**

- 推荐 v1 采用四种 risk-shaped Finding；工程/质量事实不由 Agent 直接修改，Accept/Edit/Reject 与 Apply 继续复用已验证的双人工动作。
- migration `0024_phase_two_agents` 扩展四个 Agent/Finding allowlist、受限创建函数及两张 `security_barrier` 证据投影视图；空 `pdos_test` 完成 `0024→0023→0024` 往返，最终唯一 head 为 `0024_phase_two_agents`，migration/schema 7 项全绿。
- Engineering Intelligence 精确订阅 `DEVELOPMENT_BOM_CREATED`、`DEVELOPMENT_BOM_ITEM_ADDED`、`CHANGE_RECORD_CHANGED`；Quality Intelligence 精确订阅 `TEST_FAILED`、`COMPLAINT_CREATED`。两份版本化静态 prompt、五条 golden cases（含 `no_action`）与跨 Agent/跨 run evidence fail-close 均通过，路由/golden 组合 34 项全绿。
- Phase 1 的冻结工具前缀保持不变；仅 Phase 2 分别追加 `get_engineering_evidence` / `get_quality_evidence`。模型只收到 `reference_id/entity/entity_id/label/excerpt`，Customer reference、document key 与 BOM attribute 不进入上下文；owner 工具 17 项、真实受限 `pdos_agent` 正反向 6 项全绿。
- 四种新 Finding 均保持 `pending_review→accepted/rejected→applied`；Accept 后业务 Risk 数为 0，第二次独立 Apply 才创建 Risk，并写入 `RISK_CREATED`、`risk.create_from_finding` 与 Finding action。四类型 Apply/重放 9 项全绿，受限 Agent 对 BOM/ECR/Complaint/NCR/Root Cause/CAPA/Effectiveness Review 继续零写权限。
- AI Review 增加 Engineering/Quality Agent 与 BOM/Change/Quality Cluster/CAPA 标签和筛选；web 聚焦 4 项、全量 111 项，ESLint/TypeScript/Next.js production build 全绿；server Ruff/format/mypy/compile 与全量 318 项全绿。
- 真实本地 HTTP/浏览器仅连接 `pdos_test`：Owner 登录后看到 Engineering/Quality 各 1 条；CAPA/BOM 筛选精确隔离。CAPA Accept 后数据库为 `accepted + risk_count=0`；独立 Apply 后为 `applied + risk/event/audit=1/1/1`，深链可打开 Exposure 15 Risk。390px 暗色模式 `scrollWidth == clientWidth == 390`、全部可见按钮至少 44px，Chromium console 0 warning/0 error；临时服务、浏览器会话和验收数据均已清理。

**Error ledger**

| 现象 | 次数 | 处理 |
|---|---:|---|
| 全量 format gate 发现 Phase 1 golden 断言存在一处仅格式差异 | 1 | 运行项目 formatter，随后 207 个 Python 文件 format check 与 Ruff/mypy/compile 全绿 |
| 初次以 `127.0.0.1` 打开 Next dev 被开发资源 origin 保护拦截 | 1 | 改用同一临时服务的 `localhost` 入口；真实交互链路与浏览器 console 随后全绿，未放宽生产或仓库安全配置 |

## Completed: S4-4 Context Builder 补层

**Definition of Ready**

- [x] 规格出处：canonical S4-4、AI Runtime 四层 Context 与 §11 前缀冻结/代码预聚合纪律
- [x] 依赖项：S2 文档抽取、run lease/投影、Phase 1/2 Agent 与 S4 Memory 均已就绪
- [x] 版本边界：`run-context-v2` 新增 Multimodal/User 两层；历史 v1 不回写
- [x] 数据边界：Multimodal 仅 trigger-bound internal 抽取片段；User 仅静态 role lens 与当前项目 active role 聚合
- [x] 安全边界：模型自报 scope/role 无效；PII、object key、原文件与 restricted/confidential 0 穿透
- [x] migration：`0025_context_builder_v2`；合同见 `docs/design/2026-08-12-s4-4-context-builder-layers-contract.md`

**Implementation slices**

- [x] S4-4a：冻结 v2 schema、Multimodal/User 字段、限额、状态、角色映射与兼容合同
- [x] S4-4b：migration 0025 与 run context/version 原子持久化
- [x] S4-4c：实现 owner/restricted Multimodal Context 与 trigger/classification/OCR/cap 边界
- [x] S4-4d：实现 owner/restricted User Context、role lens 与无 PII 项目角色聚合
- [x] S4-4e：把两层接入模型动态 context 尾部并证明 prompt/tool 前缀未变
- [x] S4-4f：完成受限账号、no-leak、迁移、完整门禁与真实 worker/API/浏览器验收
- [x] S4-4g：更新 canonical checkbox、形成 Sprint 4 Exit Gate 报告并停下等人确认

**Current evidence（2026-08-12）**

- 推荐 v2 不把 event-driven Agent 冒充成登录用户；User Context 是静态 Agent role lens + 当前项目 active role 聚合，权限真值仍在 RBAC/数据库。
- `run-context-v2` 固化 `multimodal` 与 `user` 两层；owner/restricted builder、模型白名单投影与持久化共用同一严格 schema。动态层继续追加在版本化 system prompt/tool 前缀之后，Phase 1/2 冻结前缀未改变。
- Multimodal 只消费当前 run 触发的 `DOCUMENT_UPLOADED`，仅 internal + extracted 进入模型；最多 5 份文档、20 个片段、单片段 1,000 字、总计 12,000 字。restricted/confidential、OCR required、object key、SHA、上传人、原始 payload 与跨项目引用均 fail-close。
- User Context 仅包含 Agent 静态视角、`advisory_only` 决策模式、人工 Review/Apply 约束与当前项目 active 成员角色计数；username、display name、email、user id 等 PII 不进入模型。
- migration `0025_context_builder_v2` 往返与有损 downgrade guard 全绿；本地 `pdos_test` 最终唯一版本为 `0025_context_builder_v2`。新增 `security_barrier` 角色投影，真实 `pdos_agent` 仍不可直接读取 User/Project Member 业务表或写业务表。
- 受限运行时四参数视角（project_manager/engineer/engineer/quality）全部通过真实 `pdos_agent` lease→projection→gateway→Finding 链；internal 抽取文本进入模型，restricted 文本、跨租户 Memory、object key 与 PII 均 0 穿透。
- 全量质量门禁全绿：Server 324 tests，Ruff/format/mypy 97 source files/Python compile；Web 32 files / 111 tests，ESLint/TypeScript 与 webpack production build。默认 Turbopack 在沙箱因端口绑定权限失败，webpack 生产构建随后成功。
- 真实 HTTP/浏览器仅连接 `pdos_test`：Owner 创建项目并上传 internal/restricted 两份 XLSX，均返回 201/extracted；文档页只显示 filename/classification/size/status，不显示对象键，事件页按 project + `DOCUMENT_UPLOADED` 精确得到 2 条。Chromium console 0 warning/0 error；临时租户、服务、浏览器与脚本已全部清理。

## Next: Sprint 4 Exit Gate

- [x] S4-1～S4-4 canonical 工作项全部完成
- [x] Complaint→NCR→RCA→CAPA→Effectiveness→closed→Memory draft→verified→`/ai/chat` citation 的纵向验收已在 S4-2 闭环
- [x] 迁移、受限数据库角色、租户/项目/状态过滤、Finding 双人工动作与完整质量门禁均通过
- [x] Exit 报告已形成：`docs/reports/2026-08-12-sprint-4-exit-draft.md`
- [x] 人工确认 Sprint 4 Exit Gate；确认前不得进入 S5-1

人工于 2026-08-12 明确回复“确认 Sprint 4 Exit Gate，进入 Sprint 5”。该确认只批准移动执行指针，不构成生产部署、创建/修改钉钉应用、回调地址、群机器人、审批模板或其他外部系统变更授权。

## Residual Risk: S5-1 钉钉连接器（本地完成，真实应用 Gate 延期）

**Definition of Ready**

- [x] 规格出处：canonical S5-1、API Design / Development Roadmap、RBAC/租户边界及 Sprint 5 Exit 验收
- [x] 依赖项：本地认证/JWT、Event/Audit、Project/Task/Finding/Gate/Decision 与部署边界均已就绪
- [x] 范围冻结：免登、回调 AES、审批、群通知、交互卡片；复用协议经验但使用独立应用标识与回调命名空间
- [x] 安全边界：外部 identity/corp/user/code/回调 payload 均不可信；租户与本地用户映射由服务端数据库真值绑定，重放/伪造/跨租户 fail-close
- [x] 迁移号、API、事件、outbox/重放、幂等、降级、配置与生产回滚合同冻结

**Implementation slices**

- [x] S5-1a：审计规格与老 CEHub 协议实现，冻结 v1 数据/API/安全/可靠性契约
- [x] S5-1b：实现独立钉钉应用配置、免登 code exchange 与本地 session 建立
- [x] S5-1c：实现签名/时间窗/nonce/AES 回调验证、幂等事件接收与 URL challenge
- [x] S5-1d：实现审批发起/结果回调、群通知与交互卡片模板机制
- [x] S5-1e：实现 outbox、退避重试、重放/对账、显式人工降级与运维可观测性
- [x] S5-1f：完成迁移/安全/完整门禁、fake server + 真实浏览器/API 运行验收
- [ ] S5-1g：更新 canonical checkbox 与当前指针到 S5-2

**Current evidence（2026-08-12）**

- 契约见 `docs/design/2026-08-12-s5-1-dingtalk-connector-contract.md`。当前官方授权流与老 CEHub 静默免登存在版本差异：v1 使用 OAuth `authCode→userAccessToken→contact/users/me`，不沿用已不推荐的 `dd.getAuthCode`。
- 老 CEHub 的 token 提前刷新、AES、outTrackId、create 结果不确定隔离经验可复用；审计同时识别并禁止手机号自动匹配、任意 payload 递归找 ID、缺时间窗/nonce/CorpID 尾校验、远端 approved 直接成为本地业务真值等做法。
- v1 采用显式 link 后 password-free login；审批只镜像外部协作结果，不直接批准 Gate。所有 outbound 经 durable outbox；不确定 create 不盲重放，未配置时显式降级为 manual。
- `0026_dingtalk_connector` 建立 8 个租户隔离实体并通过 `0026→0025→0026`、metadata 零漂移与有数据 downgrade fail-close 验收；后续 `0027_dingtalk_hardening` 成为单一 head。
- 免登只走固定官方主机；state 原文不落库且在远端交换前原子消费，corp 必须精确匹配，link 只绑定当前会话用户，login 只命中已有绑定。fake transport + 原认证/RBAC/Event 回归 26 项全绿，OAuth code/user token 未进入数据库、Event/Audit 或日志。
- AES 回调采用 32-byte key、AES-256-CBC、严格 PKCS#7/4-byte 长度/JSON object/尾部 CorpID 校验；签名常量时间比较，timestamp 仅容忍 ±5 分钟，nonce/ciphertext 有界。固定向量、challenge 加密 ACK、同摘要重放零二次处理与异摘要冲突等 7 项验收全绿；未知事件只 ACK，审批固定字段仅形成待同步标记，零 Gate 写入。
- 审批、群通知与互动卡片统一进入 durable outbox；稳定 idempotency/request/outTrack ID、skip-locked lease、退避重试、确定失败、create 结果 uncertain 隔离、人工对账后重放、lease 过期 quarantine 与 delivery disabled→manual 均有正反例。远端审批只更新镜像，PDOS Gate 状态保持不变。
- 生产 compose 增加独立 `dingtalk` worker，部署/回滚顺序与运行手册同步；生产安全重施脚本显式断言 `pdos_agent` 对 `integration_outbox` 无 INSERT、对钉钉身份表无 SELECT。数据库安全、迁移、部署合同和连接器聚焦验收 38 项全绿。
- 真实 Chromium 仅连接 `pdos_test` 与 fake provider：Owner password-free login 成功；集成页显示应用/绑定/manual/outbox 状态；390×844 无横向溢出；Supplier 无导航、直接访问明确拒绝且网络只有 `/api/session/me`，零钉钉集成 API 请求；本地 PDOS 页面 console 0 warning/0 error。临时浏览器与 API/Web 进程已关闭。
- 真实应用门禁前协议复核已补齐：生产 Web 新增无会话、严格 allowlist 的 AES/card 公网 BFF；OAuth redirect 固定 `/dingtalk/callback` 并与 `PDOS_PUBLIC_BASE_URL` fail-close；卡片按官方 `actionCallback + userId + content.cardPrivateData.params.action` 解析并显式 `callbackType=HTTP/userIdType=1`；应用 token 进程内缓存且提前 5 分钟刷新。
- `0027_dingtalk_hardening` 以单调递增迁移追加 `agent_id` 约束，保持已提交的 0026 不可变；新增只读 `python -m scripts.check_dingtalk_readiness --tenant-slug <slug>`，不调用钉钉、不写数据库、不输出 secret，一次检查 0026+0027 schema 合同、HTTPS origin、env/binding、回调密码学、2 个用户绑定、项目群与 outbox 基线。扩展后端聚焦 52 项、完整后端 354 项、前端 121 项及 lint/type/production build 全绿；mypy 200 source files 无错误，公网构建产物包含 AES/card 两条 callback route。
- S5-1 发布级 compose smoke 已在隔离 `pdos_test` 实证：`0027`、Agent 权限重施、API/dispatcher/executor/DingTalk/Web health、非 root UID 和无会话 callback BFF→FastAPI fail-close 全绿；候选容器自动清理。ECS 部署后同一公网 callback edge 探针已成为硬门禁。发布就绪与回滚清单见 `docs/reports/2026-08-13-s5-1-release-readiness.md`；当前仍因真实应用和本次生产授权缺失保持 NO-GO。
- 新增两阶段只读 Exit Evidence：真实 smoke 前冻结完整 release SHA、tenant/project 与所有 Gate 真值哈希，之后在 PostgreSQL `READ ONLY` transaction 中验证免登、三类 delivery、审批 callback + mirror 且 Gate 不变、card 单次处理与 outbox 清零。baseline 自带摘要且不输出 secret/外部 identity/reference；负向 OAuth/回调、浏览器/RBAC 与 Data Owner 抽查继续保留人工门禁。聚焦正向完整链、读零写、SHA/Gate 漂移和基线篡改 2 项全绿。
- shipping security checklist 的 OSV 批量审计首次在锁定依赖中发现 `cryptography 46.0.7` 的 4 个去重公告（7 条含 GHSA/PYSEC 别名），旧候选 `4180cfaaa975f1135e7386ca6c35094d08e3b272` 立即失效；升级到统一修复版本 `50.0.0` 后复查 916 个 npm/PyPI registry 版本为 0 finding，production smoke 新增运行时 50.x 硬断言。该检查已固化为只发送 ecosystem/name/version、固定 OSV 官方 HTTPS 端点、分批有界响应且任何网络/协议/漏洞异常均 fail-close 的 `make audit-dependencies`，并进入 `make check` 与 CI。
- 最新发布门禁全绿：Server 362 tests，Ruff/format/mypy 205 source files/Python compile；Web 35 files / 121 tests、ESLint/TypeScript 与 production build；锁文件 OSV 审计进入默认 `make check` 与 CI。

**真实应用 Exit Gate（必须由人创建/配置并单独授权）**

- [ ] 独立企业内部应用、最小权限、OAuth redirect、AES callback、机器人/测试群、审批模板与 card template 已由人配置
- [ ] 真实已绑定用户完成 1 次 password-free login；未绑定、错 corp、state replay 均拒绝
- [ ] 真实项目群通知可达，outbox `succeeded` 且 remote reference 可对账
- [ ] 真实 Gate 外部审批回调后仅镜像更新，PDOS Gate 状态不变
- [ ] 真实 card acknowledge 成功且重复回调只处理一次
- [ ] 人工确认 S5-1 Exit Gate；随后才勾选 canonical S5-1 并移动指针到 S5-2

**生产试点例外（2026-08-13）**

- release `a34c7eb06aaba036bef8c257c30a841c1ec6be0d` 已在 ECS 完成 migration `0027`、Agent 零写边界重施与五服务健康验证；实际 `PDOS_DINGTALK_DELIVERY_ENABLED=false`，容器重启计数为 0。
- 租户 `beepump` 的 active binding 与项目 `S18-01` 群已通过 Owner/Admin 受审计 API 配置；readiness 已验证 HTTPS、服务器凭据、schema、binding scope、回调密码学、项目群和零 unresolved outbox。
- 人明确要求“如果必要性不大，先跳过这个，默认已经完成，先完成其他的”。按执行纪律记录为延期/风险接受，不把 0/2 linked users、真实 password-free login、群通知、审批与 card smoke 伪记为 PASS；S5-1 canonical/Exit Gate 保持未通过，Stage C/外发仍需单独授权。
- 为避免该延期阻塞独立工作，人批准继续 S5-2；该批准本身不构成生产 ERP/CRM/DingTalk 外发、Stage C 或 Sprint 5 Exit Gate 授权。Sprint 5 / Cutover Exit 后续已于 2026-08-14 独立明确确认，外发与 Stage C 仍未获授权。

## 当前工作项：S5-2 ERP Handoff（2026-08-13 启动）

- [x] 契约冻结：`docs/design/2026-08-13-s5-2-erp-handoff-contract.md`
- [x] SoR 边界冻结：PDOS 只交付冻结 EBOM/effectivity；Material Master、MBOM、Routing、Inventory、Production Version 仍由 ERP 持有
- [x] 外部前提冻结：ERP API 未确认可用，默认采用人工交付降级；不得自行向生产 ERP 发请求
- [x] RED：outbox 幂等、人工导出、对账、失败重放、权限与租户隔离合同测试
- [x] GREEN：migration 0028、交付服务/API；API 模式未配置时 fail closed，默认 manual 零外部调用
- [x] VERIFY：manual 全链路、metadata drift、迁移单 head、项目级门禁；362 项服务端全量测试通过
- [x] REPORT：`docs/reports/2026-08-13-s5-2-erp-handoff-acceptance.md`

## 当前工作项：S5-3 CRM 需求入口 + 26 实体收尾（2026-08-13 启动）

- [x] 冻结 CRM 外部事件→Requirement 草稿→人工成立合同
- [x] 对照规格实体目录与当前 schema，补齐 Supplier / Cost / Resource 缺口
- [x] RED：幂等、来源追踪、人审硬闸、tenant/project 边界与 26 实体合同
- [x] GREEN：migration 0029、domain/API/event/audit、公网 POST BFF 与需求池独立人审入口
- [x] VERIFY：服务端 368 tests、Web 125 tests、ruff/format/mypy/typecheck/lint 全绿；报告见 `docs/reports/2026-08-13-s5-3-crm-entities-acceptance.md`

## 当前工作项：S5-4 Phase 3 双 Agent（2026-08-13 启动）

- [x] 冻结 Supplier Intelligence 与 Executive Intelligence 的事件路由、Finding 类型、证据和权限合同
- [x] RED：prompt 前缀、静态路由、确定性 preflight、跨租户/跨项目与 golden-case
- [x] GREEN：两份版本化 prompt、runtime route/preflight、投影工具与 migration 0030
- [x] VERIFY：受限 `pdos_agent` 端到端、全量门禁与 Sprint 5 Exit 候选报告；见 `docs/reports/2026-08-13-s5-4-phase-three-agents-acceptance.md`

## Completed: Sprint 5 全量切换与只读退役（2026-08-14）

- [x] 冻结全量定义：CEHub 全部 Project（含 archived 历史项目），不以当前 4 个未归档项目代替全库盘点
- [x] 新增 SELECT-only `capture→Data Owner→verify` 两阶段清单指纹门禁，源/目标端点与只读角色继续 fail-close
- [x] 冻结全量 dry-run→apply→幂等重放、主入口声明、CEHub 写冻结/只读归档、30 分钟观察与前向回滚契约
- [x] 补齐 migration 0029 有数据时有损 downgrade guard；成功迁移不提供自动删除或 schema downgrade
- [x] 明确 S5-1 延期例外在切换期间保持 `delivery=false`，不隐式放开外发或伪记 PASS
- [x] 获得生产只读盘点授权并在 ECS 用最终 release 捕获完整 CEHub inventory
- [x] Data Owner 批准 inventory fingerprint、全部项目 ID、release/tenant/actor，并授权立即执行 CEHub 写冻结、verify 与全量 dry-run
- [x] CEHub 写冻结稳定生效，inventory verify 与全量 dry-run 通过；`target_writes=0`，目标 11 表 count/内容 SHA-256 前后完全相同
- [x] 只读发布 `status` 发现导入 Project 列表 500 并精确复现；旧 release `2cce...` 失效且未部署/apply
- [x] 修复后端/Web 可空 Development Case 读合同并增加真实迁移回归
- [x] 获得独立生产授权，在旧 CEHub 私有环境备份原值后设置 `AUTOMATION_SCAN_INTERVAL_MIN=35790`，以同一旧 image 重建并观察至少 35 分钟，确认 scheduled scanner/read-only/`25006` 日志为 0
- [x] 合并修复形成新 release，在 ECS 仅构建候选并重新执行 inventory verify、全量 dry-run 与目标零变化快照
- [x] Data Owner 绑定新 release，批准 source fingerprint 与五类 count/预测 created/skipped
- [x] 获得新 release 部署授权，完成 0028～0030 生产部署、Agent 安全边界重施、项目 readiness 与 10 分钟有界观察
- [x] Owner/Admin 登录后确认 Dashboard 项目组合可读且不再显示“驾驶舱暂不可用”；C4s / S18-01 Project Workspace 均可进入，浏览器 console warning/error 为 0
- [x] 获得独立生产 apply 授权（明确包含成功后的同参数幂等重放），完成 apply、目标前后快照、独立 Data Owner 口径抽查与幂等验证
- [x] 业务 Owner 宣布 `pdos.beepump.net` 主入口、验证 CEHub 只读归档并完成观察窗
- [x] 人工确认 Sprint 5 Exit Gate 与切换退役；S5-1 延期残余风险另行跟踪

契约：`docs/design/2026-08-13-sprint-5-cutover-contract.md`；运行手册：`docs/runbooks/sprint-5-cutover-and-retirement.md`。最终 release 的全量 dry-run、生产部署、apply、独立抽查、幂等重放、业务 Owner 主入口声明及声明后 1844 秒只读观察均已通过；Data Owner、发布 Owner、业务 Owner 已共同确认 Sprint 5 / Cutover Exit。

**Sprint 5 / Cutover Exit 人工确认（2026-08-14）**

- 人工明确确认 Sprint 5 / Cutover Exit，并接受 S5-1 真实钉钉 smoke 作为延期残余风险，生产保持 `delivery=false`。
- 该确认完成六 Sprint 建设与本次切换出口；不把 S5-1 canonical/真实应用 Gate 改写为 PASS，不授权恢复 CEHub 写入、开启钉钉外发、修改 DNS/Nginx 或执行 CEHub 最终停机。
- 最终候选状态见 `docs/reports/2026-08-13-sprint-5-exit-and-cutover-candidate.md`；主入口与只读归档证据见 `docs/reports/2026-08-14-sprint-5-main-entry-observation.md`。

**生产 inventory capture（2026-08-13）**

- PR #4 已合并，最终 release `2ccefa1d2fe6567be4af8370b67aed9164aadd1d` 的 bundle、远端 clone、OCI revision 与非 root image 均完成一致性校验。
- ECS 全量只读 capture 成功：4 Project / 4 active / 0 archived，类型为 3 NPD + 1 OBT，`errors=[]`；inventory fingerprint 为 `a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d`。
- 线上 5 个容器保持 release `a34c7eb06aaba036bef8c257c30a841c1ec6be0d`、container ID 不变且 healthy；Alembic 仍为 `0027_dingtalk_hardening`，未部署、未迁移、未写目标库。
- 脱敏证据：`docs/reports/2026-08-13-sprint-5-production-inventory-capture.md`。Data Owner 后续已批准 fingerprint 与有序四项目清单，并授权完成写冻结、verify 和最终全量 dry-run；当前等待批准新的 `source_fingerprint`。

**生产全量写冻结与 dry-run（2026-08-13）**

- Data Owner 已绑定 release、inventory fingerprint、有序四项目、tenant 与 actor，并明确授权写冻结、verify、dry-run；禁止部署和 apply。
- 旧 CEHub `ce_hub@cehub` 已设置 `default_transaction_read_only=on`；读取 4 Project 正常，永久表零行写探针返回 `25006`。只读模式下禁用每 5 秒写 heartbeat 的 activity-log tailer 后错误风暴清零，原环境有 `0600` 备份；后续发现无禁用开关的 scheduled scanner 仍每 30 分钟尝试写心跳并被 `25006` 安全拒绝，数据边界有效但稳定归档日志门禁待独立授权完成。
- Inventory verify 为 `ready`；全量 dry-run fingerprint 为 `d3d903b6bfa05958678b00502e565f0629d34d634242c8adb49c5a6f06d56b54`，6 User / 4 Project / 117 Task / 0 Gate Review / 14 File Reference，`target_writes=0`。
- 目标 tenant 11 表前后 count 与完整内容 SHA-256 全部相同；PDOS 仍运行旧 release，Alembic 仍为 0027，候选容器数 0。证据见 `docs/reports/2026-08-13-sprint-5-production-full-dry-run.md`。

**生产发布阻断（2026-08-13）**

- 候选 release 的只读 `status` 在 10 分钟有界日志中捕获线上真实 `/api/projects` 500；堆栈稳定落在 `ProjectService.list()` → `_record_from_row()` → `ProjectNotFoundError`。
- 根因是 CEHub 迁移项目按 schema 合法缺少原生 Development Case，而后端读模型和 Web 解码器错误地要求 `development_case_id` 必须存在。修复只放宽导入项目读取；原生 Project 创建仍强制 Case。
- `2cce...` 含相同缺陷，故已失效且不得部署/apply。CEHub 继续只读、PDOS 保持旧 release；报告见 `docs/reports/2026-08-13-sprint-5-project-api-release-blocker.md`。

**发布候选复验（2026-08-13）**

- Server 388 tests；Ruff / 246 files format / mypy 213 source files / compileall 全绿。
- Web 37 files / 126 tests；ESLint / Next typegen / TypeScript / webpack production build（33 pages）全绿。
- 锁定依赖 916 个版本经 OSV 两批审计为 0 known vulnerabilities；`git diff --check` 通过。
- 最终审查修复了 Portfolio 聚合笛卡尔计数、Supplier delay 外部事件确定性校验、0029 有数据 downgrade guard 与全历史项目盘点缺口。
- Exit 候选报告：`docs/reports/2026-08-13-sprint-5-exit-and-cutover-candidate.md`。

**生产最终 release 复验（2026-08-14）**

- PR #6 已合并，最终 release 为 `82de9d215c5b0101aaba8cbff2d1adf6d751ceef`；ECS API/Web OCI revision 精确一致，并已在明确发布授权下切换五个生产容器。
- CEHub 原私有环境已做 `root:root 0600` 备份；tailer=false、scan interval=35790，以同一旧镜像重建并从安全探针后观察至少 35 分钟，restart=0、读取 200、相关错误日志为 0。
- Inventory verify 为 `ready`；全量 dry-run source fingerprint 仍为 `d3d903b6bfa05958678b00502e565f0629d34d634242c8adb49c5a6f06d56b54`，五类 source/created/skipped 守恒，`target_writes=0`。
- 目标 tenant 11 表前后快照逐字节一致，SHA-256 均为 `d02fd41fe4a70c4ac2c4bc9a3715543f63a50a25a30431cfceed7bafb3317a4e`；本次部署未执行 CEHub apply。
- canonical deploy 完成 0028～0030 与 Agent 安全边界重施；五容器全部健康，生产保持 `delivery=false`，CEHub 容器与静默参数未变化。
- 最终 release 以强制只读连接通过 2 个导入 Project readiness；公共入口全 200，部署后 10 分钟不健康容器、fatal pattern 与 `/api/projects` 500 均为 0。详细脱敏证据见 `docs/reports/2026-08-14-sprint-5-production-release-revalidation.md`。

**生产正式主入口与只读归档复核（2026-08-14）**

- 业务 Owner 明确宣布 `pdos.beepump.net` 为 PDOS 正式主入口，并授权 30 分钟只读观察、四项目真实登录/查询及 CEHub 只读归档复核；明确禁止 DNS/Nginx、CEHub 写恢复与钉钉外发。
- 正式窗口 UTC `02:43:51`～`03:14:35`，61 样本、1844 秒；五容器/固定 image、HTTP/TLS、重启、fatal、Project 500、CEHub 归档错误和 `delivery=false` 全部 0 失败。
- 生产 admin 会话显示 4 个可见项目；C4s、S18-01、D14-04、D15-05 工作区与 OBT/NPD Gate 查询通过，console warning/error 为 0。
- 独立目标只读事务确认 4 Project / 117 Task / 25 Gate / 14 File Reference / 141 Mapping / 4 Migration Run；窗口内登录 Event/Audit 各 1 且时间一致。
- CEHub `ce_hub@cehub` 默认/当前事务均只读，4 Project 可读，零行写探针返回 `25006`；原 container ID、restart=0、tailer=false、scanner=35790、读取 200 与窗口归档错误 0 均保持。详细证据见 `docs/reports/2026-08-14-sprint-5-main-entry-observation.md`。

**Error ledger**

| 现象 | 次数 | 处理 |
|---|---:|---|
| CEHub 只读后 scheduled scanner 每 30 分钟写心跳并产生 `25006` | 3+ | 已观察 UTC 05:20/05:50/06:20 三次且预计持续；数据库只读边界安全拒绝、项目可读、assigned-XID 为 0，旧镜像无 disable flag；待独立生产授权后按固定 `35790` 分钟重建并观察至少 35 分钟 |
| 候选只读 `status` 命中线上 `/api/projects` Traceback | 1 | 停止发布；定位为迁移 Project 合法无 Case 与读模型冲突，先写真实迁移 RED，再同步修复后端 API/Web 解码并把 `2cce...` 标记失效 |
| 本机 `.env` 的测试 URL 指向被 CEHub 占用的旧 `55432`，凭据校验失败 | 2 | 只读定位当前 PDOS compose 为 `57432`，所有验收显式绑定 `pdos_test`；未修改用户环境文件、未连接开发/生产库 |
| 本地 HTTP 验收脚本继承系统代理导致 loopback 首次超时 | 1 | 临时 client 设置 `trust_env=False` 后，仅访问 `127.0.0.1:8314` 的链路成功；未修改应用出口政策 |
| 默认 Turbopack production build 在沙箱尝试绑定端口被拒 | 2 | 以仓库支持的 webpack production build 复验，全部路由成功生成；源码、部署配置与安全边界无需放宽 |
| React Strict Mode 首次挂载清理中断唯一 OAuth callback fetch | 1 | 保留 `useRef` 一次提交保护并移除 effect cleanup abort；Strict Mode 单请求测试与真实 password-free login 均通过 |
| 完整套件共享 `pdos_test` 遗留钉钉数据触发 0026 有损 downgrade guard | 1 | 旧迁移测试先升级到 head 并清空隔离租户后再降级；保留生产有数据 fail-close，完整 343 tests 全绿 |
| S5-4 首次全量回归发现 S5-3 新增四张表未进入旧的 exact-table 集合 | 1 | 更新 canonical schema 集合后重跑，381 tests 全绿；不是 migration 或 Phase 3 运行时缺陷 |
| Production smoke 的基础设施入口未继承测试 URL 中的非默认端口 | 1 | 默认 `55432` 与 CEHub 冲突后停止；按现有 PDOS 端口 `57432` 恢复本机容器并以显式 `PDOS_POSTGRES_PORT=57432` 重跑，未连接 CEHub 或生产库 |
| 沙箱内完整测试无法访问本机 PostgreSQL 和临时 HTTP socket | 1 | lint/type 先完成；随后在获批本机运行边界外以同一 `pdos_test` 重跑，Server 354、Web 121 与 production build 全绿 |
| 依赖升级后的旧 Compose 2.17 对共享 API image 发起多服务重复构建，首次 metadata 超时、串行模式随后无进展 | 2 | 中止并确认零容器残留；production smoke 与 ECS build 入口均固化为只构建唯一 `api web`，再按原顺序启动服务，避免五个后端服务并行争用同一 image，所有验收断言保持不变 |
