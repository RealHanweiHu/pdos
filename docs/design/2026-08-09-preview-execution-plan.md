# preview.zip 具体执行计划

> 日期：2026-08-09
> 基准：[docs/specs/cehub-v3.2-preview/](../specs/cehub-v3.2-preview/)（唯一产品规格）
> 决策记录：[汇合与地位文档](./2026-08-09-cehub-v32-convergence.md)
> 原则：preview.zip 的实体/Agent/架构/路线图全量实现；CEHub 代码复用可选、**基础设施复用确定**（RDS/ECS/OSS/钉钉/部署链，避免重复搭建）。

## 0. 不可协商项

1. Master Prompt 六规则：域边界、不替代 ERP/MES/PLM、AI 输出人审、既定实体、SoR 所有权、增量实现。
2. AI-native：Sprint 2 起 AI 在关键路径，拆除测试为验收判据。
3. 每 Sprint 出口：测试全绿（隔离运行为准）+ 类型检查 + 可部署。
4. Alembic 迁移从第 1 天规范化，禁止 schema 与迁移脱节（CEHub v3-2 的教训）。

### 0.1 设计结构确认（2026-08-10）

当前设计按六层闭环，结构成立，不再另起架构：

1. **产品域**：26 个业务/AI 实体，加 1 个基础设施实体 Event（规格清单共 27 项）覆盖 Idea→Requirement→Development Case→Project→NPI→MP/Ramp→Quality Feedback→Memory；四套规格状态机与 SoR 矩阵约束实体归属。
2. **应用层**：Next.js 承载已拍板 IA，FastAPI 承载业务服务与人工动作，LangGraph worker 承载事件驱动 AI 执行；对象存储只保存文件与无损指针。
3. **数据层**：PostgreSQL 10 个 schema 按域隔离；业务写、事件、审计同事务；Alembic 是 schema 变更唯一入口。
4. **AI 层**：六 Agent 是一个运行时的六份订阅配置，统一走 Event→Context Builder→Agent Selection→Tool Calling→Human Review→Business Update，不引入 Agent 互审。
5. **治理层**：租户 fail-close、对象权限、上下文白名单、`pdos_agent` 数据库最小权限、人审 finding 与服务端真值复核共同闭环。
6. **交付层**：Sprint 0→5 依赖顺序正确；Sprint 2 先建立 AI 关键路径，Sprint 3–5 再增加域深度、记忆与外部集成。

本次确认只补齐施工断点、权限职责和验收证据，不改变产品规格、技术栈、实体边界或 Sprint 范围。

### 0.2 实施控制流程（所有工作项通用）

工作项状态以编号前的 checkbox 为准：`[ ]` 未开始、`[~]` 进行中、`[x]` 完成、`[!]` 阻塞。任何工作项只能按以下顺序推进：

1. **Definition of Ready**：确认规格出处、依赖项、预计触达文件、迁移号、验收条款；涉及 RDS/OSS/ECS/边缘代理/DNS、生产环境或远程 push 时，先停下等人确认。
2. **纵向最小切片**：以一个可运行行为为单位同时完成 schema/服务/API/UI/测试中实际需要的部分；共享迁移和公共契约串行，契约冻结后的独立切片才可并行。
3. **实现内门禁**：先跑聚焦测试，再跑 lint/format/typecheck、完整测试、构建；涉及数据库时必须在 `pdos_test` 执行 `alembic upgrade head`，并验证开发库与测试库隔离保护。
4. **运行时验证**：不能只以编译通过收口；按工作项验收条款走一次真实 API/UI/worker 路径，覆盖至少一个错误路径，并记录命令、结果或截图位置。
5. **完成记录**：验收条款和项目级 DoD 全部满足后，才把工作项改为 `[x]`；同时更新 `tasks/todo.md` 的当前指针。不得以“代码已写完”代替完成。
6. **Sprint 出口**：汇总工作项证据、迁移头、测试/类型/构建结果、安全与回滚检查，向人汇报；得到确认后才进入下一 Sprint。

项目级 Definition of Done：验收条款满足；新增行为有会失败再通过的测试；错误路径和租户越界有覆盖；无无关重构/调试残留；文档、迁移、配置同步；运行时已验证；高风险变更有回滚路径；需人审的出口已确认。

事件目录纪律：规格的 10 类事件是必须实现的冻结基线，不是数据库闭集；工作项确需新增域事件时，必须先在版本化事件注册表中补名称、payload schema、生产者、消费者、幂等键与兼容测试，禁止在代码中散落裸字符串。

## 1. 基础设施（复用现有，参数级）

| 项 | 方案 | 动作 |
|---|---|---|
| **RDS** | 复用实例 `pgm-2ze135h6045td5ujvo.pg.rds.aliyuncs.com:5432`（已承载 erp_dashboard、cehub 两库，分库隔离模式成熟） | 控制台新建数据库 `pdos` + 专用账号 `pdos_app`（与 ce_hub/erp 账号分离）；ECS 内网 172.19.142.146 已在白名单，无需动 |
| RDS CA | 复用 `certs/ApsaraDB-CA-Chain.pem`（CEHub 仓库已带，公开 CA 链） | 拷贝进本仓库 certs/ |
| **pgvector** | 规格要求。RDS PG 需确认版本支持 `CREATE EXTENSION vector`（阿里云 RDS PG 11+ 一般可装） | Sprint 0 第一天验证；**不支持则回退**：ECS 上 compose 内置 `pgvector/pgvector:pg16` 容器承载 pdos 库（RDS 仅作回退时不用） |
| **ECS** | 复用 `8.140.197.68`（Ubuntu 22.04 + Docker，已跑 ERP 看板 + CEHub） | 新 compose 项目，app 绑 `127.0.0.1:3002`（3000/3001 已被占用），api 与 LangGraph worker 分容器 |
| **域名/HTTPS** | 复用 ECS 现有 Nginx（2026-08-11 经人确认） | `pdos.beepump.net` A 记录指向 ECS；Nginx 接入 `pdos_default` 并反代唯一别名 `pdos-web:3000`；certbot webroot 签发和续期证书。决策与回滚见 ADR-001 |
| **对象存储** | 复用 OSS（同 endpoint/凭据模式） | 控制台新建桶 `pdos-files`（托管 OSS 需预建桶，应用凭据无 CreateBucket 权限——CEHub 已踩过） |
| **钉钉**（Sprint 5） | 复用同企业 corp_id 与协议实现经验（免登/回调 AES/交互卡片模板机制） | 建议新建企业内应用（新 agent_id + 回调地址），避免与 CEHub 回调冲突；代码层协议逻辑可搬 |
| **部署链** | 复用 CEHub 模式：`.env.production` 不入库、`scripts/deploy-ecs.sh`、runtime migrator、compose prod 只绑本机端口 | 照抄骨架改参数 |
| **本地开发** | 复用 CEHub `compose.local` 模式 | `docker compose up postgres minio`（PG 镜像换 pgvector/pg16）；测试库 `pdos_test` 独立（吸取 cehub_vitest 隔离教训） |

**Day-1 基础设施清单（半天）**分两条轨道：① Agent 可执行：本地 compose 起 PG+MinIO、`.env` 模板与隔离保护；② 必须由人执行或明确授权：RDS 建库/账号、验证托管 pgvector、OSS 建桶。两条轨道可并行，外部资源未就绪不阻塞 S0-1 的本地与 CI 脚手架，但必须在 Sprint 0 生产验收前完成。

## 2. 仓库结构与栈

```
ai-native-R&D-platform/
  web/        Next.js (App Router, React+TS)          ← 规格 Frontend
  server/     FastAPI + LangGraph(Python) + Alembic    ← 规格 API Services + AI Runtime
    app/api/          REST 路由（/projects /events /ai/*）
    app/domain/       实体服务（按 namespace 分包）
    app/ai/           gateway / graphs / agents / tools / prompts
    app/worker/       事件消费 + agent 执行（独立容器）
    migrations/       Alembic
  certs/      RDS CA 链（复用）
  docs/       specs + design
  scripts/    deploy-ecs.sh / 迁移工具（Sprint 3 末）
```

数据库 namespace 按规格建 10 个 schema：`cehub_core / cehub_project / cehub_product / cehub_quality / cehub_supplier / cehub_cost / cehub_ai / cehub_memory / cehub_event / cehub_audit`（Alembic migration 0001，greenfield 第一天做对）。

## 3. Sprint 0 — Tenant, Auth, RBAC, Database（1.5–2 周）

| # | 工作项 | 说明 |
|---|---|---|
| [x] S0-0 | **UI 基线 v0.2 已完成并拍板**（2026-08-10 校准） | 交付：`2026-08-09-ui-baseline.md` + `ui-baseline-mockup.html`。定稿：shadcn/ui + Tailwind v4 + Geist/Geist Mono；**公司主题橙**强调色（亮 #c2410c / 暗 #fb923c）、待审状态色纯黄、圆角 8px 锁定、双主题跟随系统；IA 导航树 + 三承重界面（收件箱三键裁决 A/E/R + 逐字段 diff + 证据引用跳转；accepted 后独立 Apply；驾驶舱三卡；项目工作区阶段轨道+九页签）交互已定义。Sprint 0 按此实现，改动走版本号 |
| [x] S0-1 | **仓库脚手架 + 本地基础设施 + 最小 CI 门禁** | 建立 `web/` Next.js App Router + TS + Tailwind v4 + shadcn/ui + Geist/Phosphor，`server/` FastAPI + LangGraph(Python) + Alembic；本地 compose 提供 pgvector/pg16（`pdos` 与 `pdos_test`）+ MinIO；统一开发/测试/类型/构建命令与 CI。测试入口必须 fail-close：`TEST_DATABASE_URL` 库名不是 `pdos_test` 时直接拒绝。**验收**：无 LLM key 时本地依赖可启动，web 与 `/healthz` 可访问；空迁移可在 `pdos_test` 升级；web lint/type/build 与 server lint/type/test 全绿；生产模板不含真实密钥。ECS 空应用部署是人授权后的单独 smoke gate，不由 Agent 自行执行 |
| [x] S0-2 | migration 0001：10 schema + 第一批实体表 | cehub_core：Tenant/User/Customer；cehub_project：Requirement/DevelopmentCase/Project/Workflow/Stage/Gate/Task/Issue/Risk/Decision |
| [x] S0-3 | 认证 + 租户解析 | 本地账号密码 + JWT（CEHub 模式）；fail-close 租户中间件（语义参考 CEHub tenant-context：无默认租户成员关系即拒绝）；/api/setup 一次性初始化管理员（CEHub 模式） |
| [x] S0-4 | RBAC 7 角色 | Owner/Admin/PM/Engineer/Quality/Supplier/Customer；对象权限骨架（项目成员表+角色矩阵）；Supplier/Customer 为外部角色，默认最小可见面 |
| [x] S0-5 | 事件与审计骨架 | `cehub_event.events`（规格 schema：event_id/event_type/source/entity/entity_id/payload/timestamp + tenant_id/project_id；UNIQUE(source, event_id) 幂等）+ `cehub_audit.audit_log`；建立版本化事件注册表并登记规格 10 类事件的 payload/生产者/消费者/幂等规则；写路径纪律=业务同事务落事件 |

**验收**：多租户下建项目互不可见；7 角色权限矩阵有测试；任一写路径落事件+审计；ECS 上可访问登录页。

## 4. Sprint 1 — Requirement, Project, Task, Issue（2 周）

| # | 工作项 | 说明 |
|---|---|---|
| [x] S1-1 | Requirement 池 | 录入/编辑/关联 Customer；REQUIREMENT 相关事件 |
| [~] S1-2 | Development Case + 转化 | Requirement→Case 正式转化动作（产 **Decision** 记录）；Case 状态机 Draft→Evaluating→Approved→Converted/Rejected |
| [ ] S1-3 | Project + Workflow/Stage 实例化 | 项目 7 态状态机（Draft/Proposed/Approved/Active/OnHold/Completed/Archived）；Workflow 模板→Stage 实例（NPD 阶段结构参考 CEHub SOP 但按规格 Workflow 实体建模） |
| [ ] S1-4 | Task / Issue / Risk | Issue 5 态（Open→Analysis→Action→Verification→Closed）；任务依赖与阻塞遵守「前置未完成=待开始≠blocked」铁律 |
| [ ] S1-5 | 事件全覆盖 + 调试页 | PROJECT_CREATED / PROJECT_STAGE_CHANGED / ISSUE_CREATED 等接通；事件浏览调试页（开发内部用） |
| [ ] S1-6 | 前端第一版 | Dashboard 骨架（Portfolio/Risk 两卡）+ Project Workspace（Overview/Timeline/Task/Issue/Risk 五标签） |

**验收**：一条需求走完 Requirement→Case（Decision 留痕）→Project→Task/Issue 闭环，全程事件可回放；Timeline 正确渲染阶段。

## 5. Sprint 2 — AI Workspace, Document AI, Context Builder（3 周，AI 进关键路径）

| # | 工作项 | 说明 |
|---|---|---|
| [ ] S2-1 | **LLM Gateway（多供应商）** | **模型选择是用户可见的产品功能**：治理页「模型与预算」设置，租户级选择供应商/模型，**默认 MiniMax 国内版（minimax.cn）**；下拉列表=管理员在 env 配了凭据**且 golden-case 评测通过**的白名单模型（用户自由选、但只能在评测过的池子里选——门禁与自由不冲突）；API key 永不暴露给用户。协议层：GLM/MiniMax/OpenAI/DeepSeek 走 OpenAI 兼容协议（base_url+key+model 三元组），Anthropic 走原生协议——网关只实现这两种协议形态。**支持按 Agent 分档路由**（抽取类用便宜模型、推理类用强模型，Sprint 2 先单模型跑通，分档留接口）。**结构化输出不依赖供应商原生能力**：统一由网关做 schema 校验+重试（国产模型兼容性差异被这层吸收）。`cehub_ai.model_invocations` 留痕（prompt 版本/供应商/模型版本/token/耗时/agent 归因，多供应商计价归一）；租户日预算+熔断（超限静默降级不阻塞业务）；**上下文白名单投影是硬前提非可选**（沿用 ERP Agent Gateway 方案A「结构出门数据留库」：尤其使用国产供应商时，密级字段/对象存储键/原文永不出门）；**出口白名单（边界）**：worker 容器网络出口仅允许已配置供应商的 API 端点；**换供应商/换模型的门禁=golden-case 评测集全量重跑不退化**（§11 失败归因纪律） |
| [ ] S2-2 | **LangGraph 执行环** | 规格六环节：Event→Context Builder→Agent Selection→Tool Calling→Human Review→Business Update。控制面 dispatcher 用 id-cursor 消费 events（拖尾语义参考 CEHub activityLogTailer）并管理 debounce/游标/订阅；AI executor 只接收冻结的 run context，生产中与 dispatcher 分进程/容器，拿不到控制面或业务库凭据。**事件按项目聚合 debounce（默认 15 分钟窗口合并触发，可调）**；事件类型→Agent 静态路由表；只读工具 3 个起步（get_project_context / search_memory / get_recent_events），**工具的租户/项目范围由服务端从触发事件的 run 上下文绑定——模型传参一律视为自报主张，不作为政策事实，越界 ID 直接拒**；`cehub_ai.agent_runs` 留痕；**失败侧熔断：单 Agent 连续 N 次 run 失败或产出连续被拒 → 自动停该订阅并告警，不无限重试** |
| [ ] S2-2b | **数据库层边界（PEDO 式，红线的最终居所）** | 角色分离：`pdos_worker` 仅可读事件并写 worker 游标/订阅/运行控制记录，`pdos_agent` 仅可 SELECT 租户投影视图并 INSERT `cehub_ai.findings/agent_runs/model_invocations`，两者均对业务表零写权限；AI executor 只持 `pdos_agent`，不得注入 `pdos_app`/`pdos_worker` 凭据。finding 的业务应用只由 FastAPI 的人工 apply handler 使用 `pdos_app` 完成。生产 RDS 的角色创建/凭据发放属于人执行的一次性动作；代码交付幂等权限模板与正反向权限测试，Agent 不自行用高权限账号执行。工具注册表/prompt 规则是降错器，不计入安全边界——即使将来加工具、改 prompt、被注入，业务表也写不进去 |
| [ ] S2-3 | **AI Finding 状态机** | pending_review→accepted/rejected→applied（语义移植自 cehub-v3-2 已验证设计）；Agent 唯一写出口=创建 finding；**接受与应用不得合并为一个动作**：人先裁决 accepted/rejected，accepted 后再由有权限的人发起第二次“应用到业务对象”并二次鉴权。apply handler 把 finding 载荷当不可信输入：落库前服务端从数据库地面真相重查全部引用/范围/状态，不采信 finding 内容中的任何政策事实 |
| [ ] S2-4 | **Phase 1 双 Agent** | Project Intelligence Agent（风险建议/阻塞预警/Gate 就绪异常，订阅 PROJECT_STAGE_CHANGED/ISSUE_CREATED/TEST_FAILED）；Knowledge Agent Lite（GATE_APPROVED/DOCUMENT_UPLOADED→知识草稿）。prompt 文件版本化入库 |
| [ ] S2-5 | **API 面** | `/ai/chat`（只读问答，回答强制携带引用，无据不答）；`/ai/analyze-document` v0（PDF/Excel 文本抽取→DOCUMENT_UPLOADED 事件→Agent 消费；OCR 后置）；`/ai/create-risk-suggestion`（经 finding 人审通道）；`POST /events`（外部接入口，event_id 去重） |
| [ ] S2-6 | **前端 AI 面** | Engineer Workspace：AI Review 收件箱（Accept/Edit/Reject + diff + 引用跳转；accepted 后独立 Apply 动作）；Dashboard AI Brief 卡片；Project Workspace AI Chat 标签 |
| [ ] S2-7 | 纪律收口 | **拆除测试**（停 LLM→系统可见失能：无新 finding/无 Brief/Chat 降级）演练入 CI 旁路脚本；golden-case 目录随人工修正积累（评测非可选）；**北极星从 Day-1 定为 finding 接受率与被采取行动数（不是产出量）**——接受率遥测入 Dashboard，低于阈值自动收窄该 Agent 输出类型，防收件箱灌爆→人审疲劳→盲批 |

**架构红线（Sprint 2 起永久生效）**：六 Agent = 一个运行时 + 六份订阅配置，**永远不引入 Agent 互审 Agent**（同文本审读零信息增益）；本系统合格的新信息源只有两个——人审判定、真实系统状态（测试结果/数据库事实）。

**验收**：开启租户内业务事件在无人工干预下自动产出 finding 进入收件箱；人审→应用为风险条目全程留痕；/ai/chat 引用可点击跳转；拆除测试通过；**红队违例测试：以注入文档诱导 Agent 写业务表/越界读他租户 → `pdos_agent` 边界 0 穿透**。**试点开始：选 1–2 个真实项目在新系统双跑体验 AI 面。**

## 6. Sprint 3 — NPI Stage Gate, Build, Sample（3–4 周，最易爆周期，盯紧）

| # | 工作项 | 说明 |
|---|---|---|
| [ ] S3-1 | Specification + Development BOM 三型 | EBOM/Prototype BOM/Cost BOM（cehub_product/cehub_cost）；BOM 边界=规格 SoR 矩阵（MBOM/Routing 属 ERP，只存引用） |
| [ ] S3-2 | Gate 硬闸与签核 | 签核轮次/就绪度/硬闸/grandfather 豁免——**直接参考 CEHub projectGateSignoffRounds 等成熟设计重实现**（这是最值钱的域知识复用）；Gate 4 态按规格 |
| [ ] S3-3 | Build / Sample / Test / Certification | Build 批次+样机谱系+序列号（EVT/DVT/PVT）；Sample 签核；Test 计划/用例/报告（TEST_FAILED 事件接通，喂 Quality Agent）；Certification+到期扫描 |
| [ ] S3-4 | 变更链后段 | ECR→影响分析→审批→**ECN→生效决策→ERP Handoff 状态**（Handoff 执行体在 Sprint 5，此处状态机与数据就位） |
| [ ] S3-5 | 检查项资产库 | CEHub `deliverable-guide-manifest.json` 687 条直接导入（数据复用，勿解析 xlsx 反推）；绑定项目类型/阶段/是否硬闸 |
| [ ] S3-6 | 前端 | Project Workspace 补 Gate/Document 标签；Gate 就绪度视图（例外优先：默认展示缺项与风险，完整材料包按需展开） |
| [ ] S3-7 | **迁移工具 v1** | 同 RDS 实例跨库 ETL：CEHub 库（只读账号）→ pdos 映射（projects→Project、project_tasks→Task、gate 历史→Gate、users→User、文件→OSS 引用）；dry-run + 幂等 |

**验收**：一个项目走完 EVT→DVT→PVT 含硬闸拦截与一次 ECN；一个真实 CEHub 项目经迁移工具进入新系统且数据抽查一致。

## 7. Sprint 4 — Quality, CAPA, Memory（3 周）

| # | 工作项 | 说明 |
|---|---|---|
| [ ] S4-1 | CAPA 正式链 | Complaint→NCR→根因→纠正预防→有效性验证（cehub_quality；字段与公司质量流程 owner 共同定义，不闭门造）；COMPLAINT_CREATED 事件接通 |
| [ ] S4-2 | Memory + 向量检索 | draft→verified→archived 状态机（未验证不进检索与 AI 上下文——移植 cehub-v3-2 已验证语义）；pgvector embedding 管线上线（embedding 走 API，模型可换）；Knowledge Search 独立入口 |
| [ ] S4-3 | Phase 2 双 Agent | Engineering Intelligence（BOM/变更影响分析建议）、Quality Intelligence（TEST_FAILED/COMPLAINT 聚类与 CAPA 建议） |
| [ ] S4-4 | Context Builder 补层 | Multimodal Context（文档抽取产物）+ User Context（角色视角）接入 |

**验收**：一条客诉走完 CAPA 闭环并沉淀 verified memory，被 /ai/chat 引用命中；向量检索与租户/项目/状态过滤叠加正确。

## 8. Sprint 5 — DingTalk, ERP, CRM Integration（3–4 周，弹性）

| # | 工作项 | 说明 |
|---|---|---|
| [ ] S5-1 | 钉钉连接器 | 免登/审批/群通知/交互卡片——复用同企业凭据模式与 CEHub 协议实现经验；新建应用独立回调 |
| [ ] S5-2 | ERP Handoff | PVT 冻结 EBOM→ERP 交接执行体 + outbox/重放/对账；ERP 侧接口不就绪则保持人工流程降级（不阻塞切换） |
| [ ] S5-3 | CRM 需求入口 | POST /events 外部通道 + Requirement 自动建草稿（人审后成立）；Supplier/Cost/Resource 实体收尾（26 个业务/AI 实体齐；Event 基础设施实体已在 Sprint 0） |
| [ ] S5-4 | Phase 3 双 Agent | Supplier Intelligence（SUPPLIER_DELAY_REPORTED 聚合）、Executive Intelligence（跨项目 Brief） |

**验收**：钉钉免登可用、通知可达；一次 EBOM 交接走完 outbox+对账（或人工降级路径演练）；26 个业务/AI 实体全部落库，Event 基础设施实体持续可用。

## 9. 切换与退役

1. Sprint 2 末起双跑试点（新系统体验 AI 面，老 CEHub 仍是事实源）；
2. Sprint 3 末迁移工具就绪，试点项目全量迁移演练；
3. Sprint 5 末：选低峰全量迁移 → `pdos.beepump.net` 转正（或接管主域）→ 老 CEHub 转只读归档（保留审计查询期，Manus 切换时同样手法）；
4. CEHub 仓库侧独立事项：`codex/cehub-v3-2` M0 止血落库照做（现役系统健康问题）；grandfather 幂等失败需查证是否影响现役 main。

## 10. 排期总览与风险

- Sprint 0–2 ≈ **6–8 周**（窗口期硬约束：不超一个季度）；Sprint 3–5 各 3–4 周；总计 1–2 季度。
- 风险与对策：①Sprint 3 重建执行链最易爆周期——靠参考 CEHub 设计重实现压缩，必要时砍 Build 谱系深度保 AI；②pgvector RDS 兼容性 Day-1 验证，有回退方案；③双跑期一致性=老 CEHub 为准；④token 成本=invocation 留痕 Day-1 就有，试点期出每项目月成本实测；⑤文档抽取质量=golden-case 从第一份真实文档积累。

## 11. 方法论全面审查补充（ai-agents-in-depth 全 17 项审计，2026-08-09）

四个已修缺口（数据库层边界 / 工具参数不信任 / 出口白名单 / 北极星=接受率）之外，全量审查新增以下纪律，按落点归入对应 Sprint：

### Context 工程三件套（S2-1/S2-2 施工纪律）
- **前缀冻结**：每个 Agent 的 system prompt + 工具定义（含顺序）定稿即冻结，动态内容（项目状态、事件、时间）一律追加到 context 末尾——严禁在 system prompt 里插 `{{now}}`/最新状态类模板变量（书中实测该错误使 TTFT 6–10×、账单翻倍）。`model_invocations` 留痕加 cache_read/cache_creation 字段，缓存命中率进监控。
- **状态由代码预聚合**：Context Builder 用 SQL 算好聚合值（7 天 issue 数、gate 距离天数、当日剩余预算、本 Agent 今日 run 数），注入 context 末尾——不让模型从原始事件流自行"心算"；聚合值准确率进监控（模型无条件信任注入状态，错值直通决策）。
- **大文档隔离**：/ai/analyze-document 的抽取结论+无损指针（文档 id/段落）进 Agent context，原文全文不进；/ai/chat 长历史走检索+verified memory，不整段灌入。

### 错误处理（S2-2 施工纪律）
- 错误分类表：429/超时→退避重试；schema 校验失败→带错误详情喂回重试 ≤2 次；预算超限/4xx→零重试直接降级。错误详情结构化注入重跑 context（书中基线：恢复率 60%→95% 的增益在信息供给不在重试次数）。
- **死亡螺旋防线**：worker 错误路径上零模型调用（run 失败后的清理/汇报不得再调 LLM）；熔断阈值上线时标记"待校准"，生产统计积累后回填。

### 工具接口（S2-2 施工纪律）
- 三个只读工具的 description 必须写 Use when / Do not use when + 负例 + 边界；参数带格式示例。
- **参数保真**：工具输出截断必须显式标注（"已显示 X 之 Y 条"+续读方式），不得静默截断；不静默改写模型输入。
- 长耗时操作命名用 `initiate_*` 语义 + 事件回报完成，不伪装同步。

### 行动空间恒定不变量（架构红线补充）
- AI runtime **永不获得** shell/SQL/HTTP 自由执行通道；新增工具只能是白名单只读查询或 finding 类受控写。这使沙箱层永久不需要——该不变量本身写入文档与评审 checklist。
- finding 入收件箱前跑**确定性预检**（引用存在性/schema/租户一致性，纯代码），预检不用 LLM 复审。

### 学习环纪律（S2-7 golden-case 与 prompt 迭代）
- **可信根不可自改**：golden-case 评测集、发布阈值、`pdos_agent` 权限定义在任何自动化可写范围之外；prompt 迭代=人工发布流程（最小 diff + golden-case 回归不退化才发布），不做自动 prompt 重写。
- **修正沉淀按载体路由**：人审修正积累后——事实→verified memory；策略→prompt 版本化更新；确定性约束→代码/schema（如某类 finding 反复因引用失效被拒→加确定性预检，不是加 prompt 规则）。防 prompt 堆成"99 条铁律"。
- 现有设计的两处正确性确认：verified memory 的 draft→人工验证→才进检索与 AI 上下文 = 恰好实现"候选≠生产"与"注入不得固化为经验"（Knowledge Agent 从不可信文档产的草稿必经人验）——此边界不得在后续迭代中放松。
- 失败归因顺序：finding 质量差时先查 golden-case 评测集本身与 Context Builder 投影（观察层缺数据=模型看不见，堆 prompt 无效），再谈换模型；每次换模型重跑 golden-case 全量。

### 明确不适用项（记录以防将来误用）
- 多智能体协作架构/快慢双组件：本系统无 Agent 间协作与实时语音形态，不引入。
- 后训练/RL：不训练。若将来想"微调让模型了解产品知识"——那是事实型缺口，走 verified memory/RAG，禁止 SFT 装事实。

## 12. 开工顺序（本周）

1. 人确认本次结构校准 → 本仓库首次 commit（docs/模板/资产全量入库；不 push）；
2. 启动 [ ] S0-1：先完成本地脚手架、隔离数据库、MinIO 与 CI 门禁；
3. 人工基础设施轨与 S0-1 并行：人创建 RDS `pdos`/`pdos_app`、验证 pgvector、创建 OSS 桶；Agent 只提供检查清单，不自行操作；
4. S0-1 本地验收通过后进入 S0-2 migration 0001；空应用 ECS/Nginx/DNS smoke 仅在人明确授权后执行，并在 Sprint 0 出口前完成；
5. CEHub M0 止血是另一仓库的独立轨道，不占用本仓库的迁移号或完成状态。
