# preview.zip 全量建设执行计划（最终基准）

> 日期：2026-08-09（同日第二次修订，替换早前「CEHub 长期数据源」方案）
> 决策（用户拍板）：**preview.zip 是最终产品形态的唯一基准**——按它的实体、Agent、架构、路线图全量建设。新项目、独立数据库。CEHub 仅为**可选**的代码/资产复用源，不构成约束（"不复用也可以"）；最终由新系统替换老 CEHub。
> 规格原文：[docs/specs/cehub-v3.2-preview/](../specs/cehub-v3.2-preview/)（11 份，已收编版本化）

## 1. 规格地位（修订）

- **preview.zip = 产品规格与验收基准**：26 个业务/AI 实体 + Event 基础设施实体（规格清单共 27 项）、六 Agent 三 Phase、AI Runtime 六环节、10 类事件目录、四套状态机、API 面、7 角色 RBAC、前端 IA、六 Sprint 路线图——全部按规格实现，命名跟随规格（Agent 用 Project Intelligence / Knowledge Agent Lite 等，不再用五角色别名）。
- **提案 v0.3 / m0-plan 降为工程参考**：其中经过验证的工程件按需取用——CEHub 连接器设计（降级为一次性历史数据迁移工具）、检查项资产库导入（manifest 687 条）、LLM trace/golden-case 纪律、For-review 交互范式（并入规格的 Human Review 环节与 AI Review 工作区）。
- **「AI-native 非 AI 赋能」定调继续生效**：AI 必须尽早进关键路径，拆除测试（关掉 LLM 系统明显失能）保留为 Sprint 2 验收判据。

## 2. 技术栈与数据库

- 栈沿用已拍板：**Next.js（React+TS，符合规格前端）+ FastAPI（规格的 API Services）+ PostgreSQL**；AI 运行时用 **LangGraph（Python 版，规格点名）**；对象存储 S3 兼容（自托管 CEHub 已有经验）。
- **新数据库与专用账号，与 CEHub 零 schema/账号共享**；最终基础设施决策允许复用同一 RDS 实例，参数与回退方案以具体执行计划 §1 为准。greenfield 无历史包袱，**按规格落 10 个 schema namespace**（cehub_core/project/product/quality/supplier/cost/ai/memory/event/audit）——这是原地改造做不到、新建第一天就该做对的事。
- **pgvector 扩展 day-1 启用**（规格技术栈明列；embedding 管线随 Sprint 4 Memory 上线，扩展先就位避免后期迁移）。
- Alembic 迁移从第 1 天规范化（吸取 CEHub 快照断层教训）。

## 3. 六个 Sprint 的工程化展开

按规格路线图（11_Development_Roadmap）执行，每 Sprint 给验收判据：

### Sprint 0 — Tenant, Auth, RBAC, Database（约 1–2 周）
- 10 namespace 骨架 + 核心实体第一批（Tenant/User/Customer/Requirement/Development Case/Project/Workflow/Stage/Gate/Task/Issue/Risk/Decision）+ `cehub_event.events`（10 类目录 + event_id 幂等）+ `cehub_audit` 审计表。
- 7 角色 RBAC（Owner/Admin/PM/Engineer/Quality/Supplier/Customer），租户隔离 fail-close（语义参考 CEHub tenant-context 的成熟实现，代码重写）。
- 验收：多租户下建项目、跨租户不可见、全部写路径落审计与事件。

### Sprint 1 — Requirement, Project, Task, Issue（约 2 周）
- 生命周期前段打通：Requirement → Development Case（正式转化动作，产 Decision 记录）→ Project → Task/Issue/Risk。
- 四套状态机按规格（05_Workflow）：项目 7 态、Issue 5 态（Open→Analysis→Action→Verification→Closed）、Gate 4 态、变更链前段。
- 每个状态迁移同事务写事件（PROJECT_CREATED/STAGE_CHANGED/ISSUE_CREATED…）——Agent 的燃料从这里开始积累。
- 验收：一条需求走完 Requirement→Case→Project→任务闭环，全程事件可回放。

### Sprint 2 — AI Workspace, Document AI, Context Builder（约 3 周，AI 进关键路径）
- **LLM Gateway**：provider 薄抽象、invocation 留痕（prompt/模型版本/token/耗时/agent 归因）、租户日预算+熔断、结构化输出 schema 校验、上下文白名单投影脱敏。供应商默认值已在后续具体执行计划 S2-1 收口为 MiniMax 国内版；本文不再保留独立默认值。
- **LangGraph 执行环**（规格六环节）：Event → Context Builder → Agent Selection → Tool Calling → Human Review → Business Update。Agent 唯一写出口=AI Finding（pending_review→accepted/rejected→applied 状态机）；应用到业务对象是第二个人工动作。
- **Context Builder**：四层中先落 Project Context + Enterprise Context；Multimodal/User Context 留接口 Sprint 4 补。
- **Phase 1 双 Agent**：Project Intelligence Agent（风险建议/阻塞预警/Gate 就绪度异常）、Knowledge Agent Lite（事件→知识草稿）。
- **API 面**：/ai/chat（只读问答+强制引用）、/ai/analyze-document（PDF/Excel 文本抽取 v0，OCR 后置）、/ai/create-risk-suggestion、POST /events。
- **前端**：AI Review 工作区（Engineer Workspace）、Dashboard AI Brief 卡片、项目工作区 AI Chat 标签。
- 验收：**拆除测试**——业务事件自动触发 Agent 产出发现进人审队列；停掉 LLM 后系统可见失能。golden-case 目录随人工修正开始积累。

### Sprint 3 — NPI Stage Gate, Build, Sample（约 3–4 周）
- Specification、Development BOM 三型（EBOM/Prototype BOM/Cost BOM）、Build（批次/样机谱系/序列号）、Sample 签核、Test（计划/用例/报告）、Certification。
- Gate 评审/签核轮次/硬闸语义**参考 CEHub 打磨过的设计重实现**（signoff rounds、就绪度、grandfather 豁免概念）——这是最值得复用的域知识。
- 变更链后段：ECR→影响分析→审批→ECN→生效决策→ERP Handoff 状态（Handoff 本体 Sprint 5）。
- 验收：一个项目走完 EVT→DVT→PVT 含 Gate 硬闸与一次 ECN。

### Sprint 4 — Quality, CAPA, Memory（约 3 周）
- 正式 CAPA 链：Complaint→NCR→根因→纠正预防→有效性验证（与公司真实质量流程 owner 共同定义字段）。
- Memory：draft→verified→archived 状态机 + **pgvector embedding 检索启用**（只有 verified 进检索与 AI 上下文）。
- Phase 2 Agent：Engineering Intelligence、Quality Intelligence（TEST_FAILED/COMPLAINT_CREATED 触发）。
- 验收：一条客诉走完 CAPA 闭环并沉淀为 verified memory，可被 /ai/chat 引用命中。

### Sprint 5 — DingTalk, ERP, CRM Integration（约 3–4 周，外部依赖多，按就绪度弹性）
- 钉钉连接器（免登/审批/群/机器人——CEHub 协议经验直接复用）；ERP 连接器（PVT 冻结 EBOM 交接，SoR 矩阵边界）；CRM 需求入口；outbox/重放/对账。
- Phase 3 Agent：Supplier Intelligence、Executive Intelligence。
- 外部条件不就绪的项不阻塞切换，降级为人工流程。

## 4. 老 CEHub 的角色与切换策略

- **建设期零打扰**：老 CEHub 照常服务公司同事，不动。
- **Sprint 2 末自用试点**：选 1–2 个真实项目在新系统双跑（AI 面先行体验）。
- **Sprint 3 齐平后迁移**：历史数据一次性迁移（m0-plan 的连接器设计降级为迁移工具：读 activity_logs/projects/tasks/gate 数据映射入新实体；687 检查项从 manifest 直接导入）。
- **切换退役**：全员切换后老 CEHub 转只读归档，保留审计查询期。
- **复用清单（全部可选，不约束设计）**：manifest 687 检查项（数据，直接导入）；React 组件与交互范式；gate 签核/硬闸/租户 fail-close 的设计语义；钉钉协议实现经验；activityLogTailer 拖尾语义（迁移工具用）。
- **CEHub 侧唯一建议动作**：`codex/cehub-v3-2` 的 M0 止血落库（修 3 个测试失败+提交合并）仍值得做——它是运行中系统的健康问题，与新项目无关；该分支的 AI 表休眠不启用。

## 5. 排期与风险

- 粗估：Sprint 0–2 约 6–8 周（AI 进关键路径的最小完整产品），Sprint 3–5 各 3–4 周，总计 1–2 个季度。窗口期约束（12–24 个月）要求 Sprint 0–2 不得超一个季度，超了先砍 Sprint 3 的谱系深度而不是 AI。
- 风险：①重建执行链工作量最大（CEHub 91 张表是数月打磨的域逻辑，Sprint 3 是最容易爆周期的地方——靠"参考重实现"而非从零发明来压缩）；②双跑期数据一致性（以老 CEHub 为准，新系统只读镜像心态）；③文档抽取质量（golden-case 从第一份真实文档积累）；④token 成本（invocation 留痕 day-1 就有，试点期出每项目月成本实测）。

## 6. 下一步

具体执行计划（含基础设施复用参数、每 Sprint 工作项与验收）见 **[2026-08-09-preview-execution-plan.md](./2026-08-09-preview-execution-plan.md)**。
