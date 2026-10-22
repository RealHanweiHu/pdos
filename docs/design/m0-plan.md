# M0 工程计划 · 派生闭环：事件层 + CEHub 连接器 + AI 派生 + For-review

> 2026-07-22。前置：[提案 v0.3](proposal.md) 决策清单已拍板（激进变体 B：CEHub 作为事件源）。
> v2 修订：用户定调「AI-native 不是 AI 赋能」——AI 进入 M0 关键路径，废弃「零 LLM 骨架」版本。
> 本计划基于对 CEHub 仓库（`~/Desktop/ce-project-hub`）与交付物模板库的实地探查，关键结论已核对到 file:line。

## 0. M0 的目标与完成判据

**目标**：交付 AI-native 的最小完整循环——**事件流入（CEHub 动作 + 会议转写）→ AI 派生（书记员/汇报员提案，带引用）→ 人裁决（For-review 收件箱）→ 落库为结构化对象**。系统不提供填表主界面：对象字段由 AI 提案填充、人批准或纠错。

验收判据：
1. **燃料**：在 CEHub 里完成任务/推进 gate/上传文件/发评论，数分钟内出现在新系统事件表，带行为人、动作、锚点
2. **书记员闭环**：上传一份真实评审会转写稿 → For-review 出现决议/遗留问题/任务提案（每条带转写片段引用）→ 批准后落库为 Review + Action Item，其中 1 条关联 CEHub 任务镜像；人工修正的 diff 被结构化记录
3. **汇报员闭环**：任选一个试点项目，系统从近 7 天事件流生成状态叙事草稿（每个论断可点开溯源到事件），负责人修改后定稿
4. **资产库**：687 条检查项入库，按项目类型/阶段过滤正确；检查项状态可由人裁决 AI 提案或人工标记（留审计）
5. **schema 完整**：Review（双轨）/Change（PCR）/Deliverable/PrototypeBatch 对象可经 For-review 或例外通道产生实例；字段所有权矩阵在 API 层生效（红线字段 AI 禁写）
6. **拆除测试**：停掉 LLM 服务 → 系统不再产生任何新状态提案与叙事，只剩只读档案与例外通道——证明 AI 在关键路径上
7. **纪律**：每次 LLM 调用有 trace（prompt/输出/token 归因）；golden-case 目录随真实修正开始积累

## 1. 仓库结构与栈（决策 3：沿用）

```
ai-native-R&D-platform/
  web/        Next.js (App Router) 前端
  server/     FastAPI 后端 + 连接器 worker + LLM 派生管线（Python：pg 拖尾/openpyxl/LLM 同栈）
  server/migrations/   Alembic（从第 1 天规范化——吸取 CEHub 快照断层教训）
  docs/       现有调研与设计文档
```

数据库：新系统自己的 PostgreSQL 实例/库（**不与 CEHub 共库**，避免表名冲突与耦合；CEHub 的 RDS 只以只读账号访问）。

## 2. 数据 schema 草案

### 2.1 事件表（P1 的工程落地，按 A1 是出处/审计载体而非重建源）

```sql
events (
  id            bigserial PK,
  source        text NOT NULL,          -- 'cehub' | 'system' | 'import' | 'meeting'(M1)
  source_event_id text,                 -- 幂等键;UNIQUE(source, source_event_id)
  action        text NOT NULL,          -- 沿用 CEHub 词汇:task.complete/gate.create/phase.advance…
  actor_ref     jsonb,                  -- {kind:'cehub_user', id} | {kind:'user', id}
  entity_ref    jsonb NOT NULL,         -- {type, id, system:'cehub'|'local'}
  project_ref   jsonb,
  occurred_at   timestamptz NOT NULL,   -- 源系统时间
  recorded_at   timestamptz DEFAULT now(),
  payload       jsonb,                  -- 源 meta 原样保留(含 before/after/patch)
  anchor        jsonb                   -- 锚点:{phase, task, file, sheet…}
)
-- 索引:(project_ref->>'id', occurred_at)、(source, id)
```

### 2.2 CEHub 镜像（只读，权威在 CEHub）

`cehub_users` / `cehub_projects` / `cehub_tasks` 三张镜像表 + `connector_state`（游标与心跳）。镜像字段取子集：任务取 `status/completed/assigneeUserId/dueDate/startDate/blockedReason/deliverables` 等（对应 CEHub `project_tasks`，见探查 `drizzle/schema.ts:642`）。**镜像表在 UI 全部只读**，展示时标注「来自 CEHub」。

### 2.3 一等对象（硬编码领域 schema）

- `deliverables`：名称、项目/阶段绑定、负责人、**关键参数 jsonb**（M2 由检查员抽取填充，M0 先留字段）、关联 CEHub 文件引用、状态
- `check_items`：从 manifest 导入的资产库——`item_id, requirement, source(operation-guide|template-baseline), bindings(project_type/phase/task/is_gate), required(派生), version`
- `deliverable_check_states`：交付物 × 检查项的勾选状态（勾选动作落 events）
- `reviews`：**双轨**——`kind(DCP|TR)`、DCP 决议枚举 `GO/KILL/HOLD/REDIRECT`、TR 决议枚举 `通过/有条件通过/不通过`、评审主体角色、`prerequisite_review_id`（前置依赖约束）、异步签核轮次（结构参考 CEHub `projectGateSignoffRounds` 的成熟设计）
- `review_action_items`：遗留问题——描述、责任人、**条件项闭环状态**、关联（本地对象或 CEHub 任务镜像）
- `changes`：PCR/ECN——类型、发起人、原因（受限 select）、影响范围引用数组、**回退目标 DCP** 字段、状态
- `prototype_batches`：批次号（贯穿主键）、项目、阶段（EVT/DVT/PVT）、关联事件（schema 完整、UI 最小化）

**M3 语料字段从第一天存在**：reviews/action_items 带计划/实际双时间戳、`delay_reason`（受限 select）、条件项闭环状态——这些是组织记忆的燃料，不是可选项。

## 3. CEHub 连接器（M0 的核心工程件）

探查结论使连接器成本大降：CEHub 已有 `activity_logs` 事件表（`drizzle/schema.ts:1747`：`action/entityType/entityId/meta(含 before/after)/userId/createdAt`）和成熟的 **id-cursor 拖尾消费范式**（`server/automation/activityLogTailer.ts`：每 5s 轮询 `WHERE id > cursor ORDER BY id`）。我们完全复刻这个语义，**零侵入 CEHub 代码**：

1. **接入方式**：CEHub 的阿里云 RDS 上建只读账号，白名单授权 `activity_logs/comments/users/projects/project_tasks`（+按需 `project_files/project_gate_reviews`）
2. **事件拖尾**：独立游标拖尾 `activity_logs`，action 词汇原样入 `events`（约 30 个 router 都写这张表：tasks 8 处、gateReviews 9 处、projects 11 处）
3. **已知缺口——评论**：`comments.add` 不写 activity_logs（探查确认 `collab.ts` 无 createActivityLog），连接器单独拖尾 `comments` 表（同样 id-cursor）
4. **镜像同步**：启动全量 + 事件驱动增量（收到 task.* 事件即刷新该行）+ 每夜全量对账
5. **幂等与容错**：`UNIQUE(source, source_event_id)`；未知 action 原样入库不丢弃（CEHub 迁移是手写的、schema 会漂移——连接器必须对新增 action 容错）
6. **可观测**：connector_state 心跳 + 滞后（cursor 落后条数）暴露在系统状态页；滞后超阈值告警
7. **明确非目标**：M0 **不写回 CEHub**（单向只读）；遗留问题转 CEHub 任务在 M0 用「人工在 CEHub 建任务 + 回填关联」的手动闭环，写回是 M1+ 决策

后备方案（若 RDS 网络/权限受阻）：在 CEHub 手写迁移里加 `AFTER INSERT ON activity_logs` 触发器写 outbox 表——但首选零侵入方案。

## 4. 检查项资产库导入（原「325 模板结构化」，探查后几乎免费）

**单一事实源是 `docs/templates/deliverable-guide-manifest.json`**（688KB，325 个交付物、687 条 checkItems，字段：`id/requirement/source/bindings{projectType,phaseCode,taskId,isGate}`）——不要解析 xlsx 反推（xlsx 是生成产物，受守卫测试管辖）。

工作项：
1. 导入脚本：manifest → `check_items` 表，保留原 id 以便与 CEHub 模板体系对账
2. **必填派生规则**（manifest 无显式布尔，需补一条规则）：`source=operation-guide 且非按需包 → 必填；isGate=true → 硬性通过标准`；规则写成配置常量，留待与你逐类核对
3. 版本化：记录 manifest 的生成时间/hash，CEHub 侧模板再生成后可重导入对比 diff
4. 已知坑：CEHub README 自述的 262/63 分布已过期，以 manifest 实际（588 operation-guide / 99 template-baseline）为准

## 5. 工作项清单与次序

| # | 工作项 | 验收 | 依赖 |
|---|--------|------|------|
| W1 | 仓库脚手架：web/server/Alembic/CI/测试库隔离 | 空应用可跑、迁移可升降 | — |
| W2 | events 表 + 写入 API + 事件浏览调试页 | 系统内动作落事件 | W1 |
| W3 | **CEHub 连接器**：只读账号、activity_logs+comments 拖尾、三镜像、心跳 | 验收判据 1 | W2；需要 RDS 只读账号（唯一外部依赖，先行申请） |
| W4 | **LLM 基座**：provider 薄抽象、全链路 trace/token 归因、修正 diff 落库、golden-case 目录+跑分脚本 | 验收判据 7 | W1 |
| W5 | 领域对象 schema：Deliverable/Review(双轨)/ActionItem/Change/PrototypeBatch + 资产库导入（manifest→check_items+必填规则） | 验收判据 4、5 的 schema 部分 | W1 |
| W6 | **For-review 收件箱**（主界面）：提案队列、Approve/Edit、diff 视图、citation 跳转、例外通道（人工直改留审计） | 提案可裁决落库 | W2、W5 |
| W7 | **书记员 v0**：转写稿上传 → 决议/遗留问题/任务提案（带片段引用、CEHub 镜像关联建议） | 验收判据 2 | W3、W4、W6 |
| W8 | **汇报员 v0**：事件流 → 项目状态叙事草稿（论断→事件溯源） | 验收判据 3 | W3、W4、W6 |
| W9 | 字段所有权矩阵 → API 权限层（红线字段 AI 禁写）+ 拆除测试演练 | 验收判据 5、6 | W2、W6 |
| W10 | 试点准备：选 1-2 个真实项目、历史转写稿收集、成员告知（决策 5 细化）、观测项清单（沟通行为变化 + review fatigue） | 试点启动会 | 全部 |

次序：W1→W2→W3 打通燃料管线，**W4 与 W3 并行**（LLM 基座不等连接器），W5→W6 立起裁决面，W7/W8 合拢闭环（M0 的本体），W9 收口纪律，W10 进试点。CRUD 表单从计划中移除——对象实例经 For-review 或例外通道产生。

## 6. 风险

1. **RDS 网络与权限**（唯一外部依赖）：开发期本地跑、RDS 白名单加开发机 IP；上线部署与 CEHub 同 ECS 内网访问
2. **activity_logs 覆盖面**：除评论外可能还有不记 activity 的写路径——连接器观测期（W9 试点前两周）比对 CEHub UI 动作与事件流，缺口记录后决定补触发器还是接受
3. **权威边界**：镜像以 CEHub 为准、一等对象以本系统为准——边界表写进 README，防止双写混乱
4. **worktree 副本混淆**：模板与代码的规范源是主仓库 `~/Desktop/ce-project-hub`，各 worktree 副本不作数
5. **CEHub schema 漂移**：手写迁移无快照约束，镜像同步字段做成配置而非硬编码；连接器测试含「未知字段/新 action 不崩」用例
6. **书记员抽取质量**（M0 头号产品风险）：制造业领域词表（扬程/气蚀/EVT/DVT…）与转写噪音——golden-case 从第一场真实评审会开始积累；For-review 的人工修正就是校准数据，质量不达标时收窄书记员输出类型（先只抽遗留问题，后扩决议/任务）
7. **Token 成本**：AI 在关键路径上意味着从 M0 第一周就产生持续消耗——trace 归因按项目/agent 记账，试点期结束时给出每项目每月成本实测，替代拍脑袋预算
