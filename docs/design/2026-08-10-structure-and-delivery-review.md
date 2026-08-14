# PDOS 设计结构与实施流程校准记录

> 日期：2026-08-10
> 审查对象：preview 规格 11 份、唯一执行计划、UI 基线、汇合决策、仓库入口与环境模板
> 结论：**设计结构通过，可以按既定路线进入 S0-1；无需重做产品架构。** 本次只修复执行断点与边界表述。

## 1. 结构确认

| 层 | 已确认结构 | 判断 |
|---|---|---|
| 产品域 | 26 个业务/AI 实体 + Event 基础设施实体（规格清单共 27 项）、四套规格状态机、Idea→Memory 生命周期 | 覆盖完整，Sprint 分配有依赖顺序 |
| SoR | PDOS 管开发上下文/决策/Development BOM；ERP/MES/PLM 保留各自事实源 | 边界清楚，不构成替代系统 |
| 应用 | Next.js + FastAPI + LangGraph worker + Object Storage | 与规格和已拍板栈一致 |
| 数据 | PostgreSQL 10 schema、Alembic、事件与审计同事务 | 适合 greenfield，迁移纪律明确 |
| AI | 一个运行时、六份 Agent 订阅、六环节固定工作流 | 自主性受控，没有无信息增益的 Agent 互审 |
| 治理 | 租户 fail-close、对象权限、投影视图、finding 人审、服务端重查真值 | 安全边界方向正确 |
| UI | 固定 IA + 收件箱/驾驶舱/项目工作区三承重界面 | 能承载 Sprint 0–4 的增量扩展 |
| 交付 | 六 Sprint，Sprint 2 先建立 AI 关键路径 | 先验证差异化，再增加 NPI 深度与集成，顺序合理 |

## 2. 已收口的问题

1. **S0-1 缺失**：进度指针引用 S0-1，但计划无正式工作项。已补为“仓库脚手架 + 本地基础设施 + 最小 CI 门禁”，并加入可测试验收条款。
2. **接受与应用混为一次点击**：UI 的“接受并应用”与 finding 的 `accepted→applied` 两次人工动作冲突。UI v0.2 已改为先 Accept/Edit/Reject，accepted 后独立 Apply 并二次鉴权。
3. **AI 控制面与执行面凭据不清**：已明确 `pdos_worker` 管事件/游标/订阅，`pdos_agent` 只读投影视图并写 AI 留痕/finding；两者均零业务表写权限，AI executor 不持应用角色。
4. **外部人工动作混入 Agent 开工序列**：RDS/OSS/ECS/Caddy/DNS 已拆成人工轨；本地/CI 轨可并行，不再因控制台动作阻塞 S0-1。
5. **工作项没有统一完成状态**：所有 Sprint 工作项已加入 checkbox；新增 DoR、实现门禁、运行时验证、DoD 与 Sprint 人工出口。
6. **文档漂移**：修正 UI 遗留 teal 文案、README 的 Anthropic 默认提示、汇合文档的“独立 RDS 实例”和“默认 Claude”旧口径。

## 3. Agent 可靠性闭环

既定架构已经覆盖生产 Agent 的五个必要功能：

| 功能 | PDOS 落点 | 硬验证 |
|---|---|---|
| 上下文 | 四层 Context Builder、白名单投影、代码预聚合 | 投影/聚合准确率与租户过滤测试 |
| 工具 | 三个起步只读工具、服务端绑定 run scope | 伪造 tenant/project 参数必须被拒 |
| 约束 | 无 shell/SQL/HTTP 自由通道、数据库角色最小权限 | 注入文档写业务表 0 穿透 |
| 验证 | 确定性 finding 预检、人工裁决、apply 前地面真值重查 | 绕过 prompt/伪造载荷/竞态均被守门 |
| 纠正 | 分类重试、失败熔断、订阅停用、人工升级 | 超时/429/schema 错误/预算超限故障注入 |

外部文档、检索结果及其摘要始终保持“不可信数据”身份；进入 context 不会获得指令权或业务授权。提示词和工具定义负责降错，数据库权限与 apply handler 才是最终边界。

## 4. 残余风险与预定落点

以下不是当前开工阻塞，而是已有明确落点的待验证项：

- 托管 RDS 是否支持 pgvector：Sprint 0 人工基础设施轨验证，失败走 ECS pgvector 回退。
- CAPA 字段：Sprint 4 必须与质量流程 owner 共同定义，不在 Sprint 0 预造。
- ERP/CRM/钉钉接口就绪度：Sprint 5 以 outbox 和人工降级路径隔离外部依赖。
- AI 质量与成本：Sprint 2 由 golden-case、接受率、被采取行动数、token/延迟留痕建立基线。
- Sprint 3 工期风险：优先保留 AI 关键路径和 Gate 硬闸，必要时按既定决策压缩 Build 谱系深度。

## 5. 进入实施的条件

1. 人确认本次校准没有改变产品范围；
2. 首次本地 commit 完成且不 push；
3. `tasks/todo.md` 指向 S0-1；
4. S0-1 只做脚手架、本地依赖、隔离保护和 CI，不提前实现 S0-2 业务 schema；
5. RDS/OSS/ECS 等外部动作仍需单独的人授权。
