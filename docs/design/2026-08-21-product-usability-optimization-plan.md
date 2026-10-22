# PDOS 产品可用性优化方案

日期：2026-08-21
状态：**待 PO 拍板**，尚未产生任何代码或生产变更
输入：生产首用反馈"产品不好用"，最刺痛的两条为 **AI 不出东西（空转）** 与 **找不到东西（导航绕）**

## 结论

这两条主诉都不是表层缺陷，各自对应一条结构性断链：

1. **AI 空转**：从"用户动作"到"用户看见 AI 产出"之间有四道闸，当前至少三道是关的。**只打开模型资格这一道，用户体感不会变。**
2. **导航绕**：IA 按系统的领域模型组织（11 个顶级入口 × 10 个项目标签），而"我的工作"这条读路径在后端根本不存在——数据层有 `assignee_user_id` / `owner_user_id`，API 层没有任何跨项目按人聚合的查询。

优化顺序由此确定：先把 AI 链路四道闸全部打通（P0），再重建以人为中心的读路径（P1），其余为支撑。

---

## 一、AI 空转：四道闸

### 闸 1 · 模型资格（进行中）

`app/ai/model_catalog.py:193` 的 `eligible_models()` 要求同时满足两个条件：provider 在环境里已配置，**且** `server/golden/model-qualifications.json` 中存在 `status="passed"`、suite digest 与 `golden/model-gateway-v1.json` 精确匹配的条目。

生产上 `provider=minimax` 的凭据已就位，但仓库里那份资格文件是空的 → 0 eligible model → 全链 fail-close。这是 8-21 生产报告里"系统保持 fail closed"的机理。

**当前状态**：工作区有未提交改动正在解这道闸——`model-qualifications.json` 已写入 MiniMax-M3 `passed`；`app/ai/gateway.py` 的 `json_document()` 新增了剥离 `<think>…</think>` 前缀的逻辑，说明 M3 是带思维链输出的推理模型，原先的 JSON 解析会被它打断。

**验收口径**：不是"API 返回 200"，而是资格发布后生产 governance API 返回 ≥1 eligible model，且真实项目上跑出第一条 finding。

### 闸 2 · 触发面覆盖不到日常动作（最被低估的一道）

`app/events/catalog.py` 中声明 `agent_dispatcher` 为消费者的事件有 **27** 个；`app/ai/runtime_contract.py:42` 的 `_EVENT_AGENT_ROUTES` 实际路由的只有 **10** 个。

**实际路由的 10 个**（全部是低频里程碑事件）：

`PROJECT_STAGE_CHANGED` · `ISSUE_CREATED` · `TEST_FAILED` · `GATE_APPROVED` · `DOCUMENT_UPLOADED` · `DEVELOPMENT_BOM_CREATED` · `DEVELOPMENT_BOM_ITEM_ADDED` · `CHANGE_RECORD_CHANGED` · `COMPLAINT_CREATED` · `SUPPLIER_DELAY_REPORTED`

**声明了却没有路由的 17 个**（恰好是用户日常高频动作）：

`TASK_STATUS_CHANGED` · `RISK_CREATED` · `RISK_STATUS_CHANGED` · `RISK_UPDATED` · `REQUIREMENT_CREATED` · `REQUIREMENT_UPDATED` · `PROJECT_CREATED` · `PROJECT_STATUS_CHANGED` · `ISSUE_STATUS_CHANGED` · `NCR_CREATED` · `NCR_STATUS_CHANGED` · `CAPA_ACTION_CREATED` · `CAPA_ACTION_STATUS_CHANGED` · `COMPLAINT_STATUS_CHANGED` · `EFFECTIVENESS_REVIEWED` · `MEMORY_ARCHIVED` · `MEMORY_VERIFIED`

后果很直接：一个工程师整天在「任务」标签里推进度，`agents_for_event()` 对 `TASK_STATUS_CHANGED` 返回空元组，**不产生任何 agent run**。而能触发 Agent 的那 10 个事件，一个项目一个月可能只发生几次。

**即使闸 1 打开，AI 依然会接近静默。这是"空转"的真正来源。**

### 闸 3 · 15 分钟去抖 + 零进度可见性

`app/worker/dispatcher.py:48` 默认 `debounce_minutes=15`。run 先落到 `debouncing`，窗口结束才 seal 成 `queued`，再由 executor 执行。用户操作后最快也要 15 分钟 + 执行时间才可能看到结果。

去抖本身是对的设计（避免连续编辑触发分析风暴）。问题在于这段时间里 UI 完全不告诉用户"有 3 个分析正在排队"。用户操作完 → 界面无反应 → 结论是"这系统没有 AI"。

### 闸 4 · 产出不回到现场

Finding 只落在 `/ai-review` 这一个顶级页面。用户在「项目 → 任务」里干活，AI 对这个项目的判断却在另一个导航后面。钉钉 `delivery=false`，也推不出去。

产出与现场分离，意味着即使有产出，多数人也不会遇见它。

---

## 二、导航绕：IA 按系统模型组织

### 现状盘点

- **顶级导航 11 项**（`web/src/components/workspace-shell.tsx:25`）：驾驶舱 / 需求池 / 开发案例 / 项目 / 知识库 / AI Review / 事件流\* / 模型治理\* / 成员与角色\* / 账户安全 / 钉钉集成　（\* = admin only）
- **项目工作区 10 个标签**（`web/src/components/projects/project-workspace-view.tsx:71`）：概览 / 时间线 / 任务 / 问题 / 风险 / 产品工程 / Gate / 文档 / 质量·CAPA / AI 对话
- 组合起来，一条信息可能落在约 90 个位置之一

其中 4 项（事件流、模型治理、成员与角色、钉钉集成）是运维与治理工具，却和业务入口平铺在同一列。

### 根因：缺"我的工作"读路径

数据层是有归属的：`work_items` 有 `assignee_user_id`，issues / risks / CAPA / complaints 有 `owner_user_id`。

但 19 个 API 模块里**没有任何跨项目按人聚合的查询**。前端只能逐项目拉取——驾驶舱的 `requestRankedRisks`（`web/src/components/dashboard/dashboard.tsx:28`）就是对每个项目各发一次请求，再在浏览器里合并排序。

结果：产品无法回答"今天要我做什么"这个唯一真正高频的问题。用户只能自己从项目 → 标签 → 列表里翻找。这就是"绕"。

### 驾驶舱是管理者视角

当前驾驶舱 = 项目卡片列表 + 风险排行 + AI brief。对 PM / Owner 合适，对占人数多数的工程师和质量人员没有落点。

---

## 三、优化方案

### P0 · 打通 AI 链路（1–2 周）

| # | 动作 | 改动位置 | 验收 |
|---|---|---|---|
| 0.1 | 完成 MiniMax-M3 golden-case 评测授权 → 人工复核 → 发布资格 | `server/golden/model-qualifications.json`（已在工作区） | 生产 governance API 返回 ≥1 eligible model |
| 0.2 | 把 17 个已声明未路由的事件接进路由表，按 Agent 职责分配 | `app/ai/runtime_contract.py:42` | catalog 声明与 routes 一致；新增一致性测试，防止两者再次漂移 |
| 0.3 | 分级去抖：里程碑事件（GATE / STAGE / TEST_FAILED）缩到 2–3 分钟，高频编辑事件保持 15 分钟 | `app/worker/dispatcher.py:48` | Gate 通过后 3 分钟内出现 finding 或明确的 no_action |
| 0.4 | 暴露"分析中"状态：项目页与驾驶舱显示排队/运行中的 agent run 数 | 新增 run 状态只读接口 + UI | 用户操作后 5 秒内看到"N 项分析已排队" |
| 0.5 | Finding 回到现场：项目工作区内联显示本项目未处置 finding，任务/风险行上显示相关徽标 | `project-workspace-view.tsx` | 不进 `/ai-review` 也能遇见 AI 产出 |

**P0 整体验收（业务口径，非技术口径）**：上线后连续 2 周，AI 在真实项目上产出 ≥20 条 finding，其中 ≥30% 被人采纳（accepted → applied）。低于这个数说明 prompt 过于保守（`AgentAssessment` 默认走 `no_action`），要做的是校准 prompt，而不是继续加功能。

### P1 · 重建以人为中心的读路径（2–3 周）

| # | 动作 | 说明 |
|---|---|---|
| 1.1 | 新增跨项目工作聚合接口 `GET /api/work/assigned`：按当前用户聚合 task / issue / risk / CAPA / 待签核 Gate / 待处置 finding | 所有后续 IA 改造的地基，顺带消除驾驶舱 N+1 |
| 1.2 | 驾驶舱角色自适应：工程师与质量默认落「我的工作台」，PM / Owner 默认落现有组合视图，可切换 | 登录后 0 次点击看到待办 |
| 1.3 | 项目工作区标签 10 → 6：任务/问题/风险合并为「工作项」（单列表 + 类型筛选 + 内联编辑）；产品工程/文档/质量CAPA 折叠为「工程与质量」二级 | 消除横向标签溢出与位置记忆负担 |
| 1.4 | 顶级导航分区：业务入口在上，4 项治理工具收进底部「设置」分组 | 普通用户可见入口从 8 降到 6 |

### P2 · 关闭外部闭环（卡在人的授权）

- **S5-1 钉钉真实应用 Exit Gate**：打开 `delivery`，把 finding、Gate 待办、风险升级推到人所在的地方，并支持从卡片一键处置回写。
- **完成 Sprint 5 切换退役**：宣布 `pdos.beepump.net` 为主入口，CEHub 转只读。双轨期每延长一周，用户对新系统的耐心就少一分。

这两项是产品级阻塞而非技术债。排在 P0 / P1 之后是因为都卡在授权，不代表不紧急。

### P3 · 用 AI 抵消录入成本（"AI-native" 的真正兑现）

- 需求与任务支持"粘贴原文（客户邮件、会议纪要、检验报告）→ Agent 预填字段 → 人只改不填"。
- 复用现有 `context_builder` / `finding_writer` / `risk_suggestions`，不需要新架构。
- 8-21 那轮修复往表单里加了描述 / 阶段 / 计划日期 / 负责人 / 依赖，方向对但代价大；这一项是它的解药。

### P4 · 性能收尾

- 驾驶舱风险聚合并入 1.1 的单接口，去掉 N+1。目前只有 4 个项目，问题被掩盖；项目上到几十个时首屏会明显退化。

---

## 四、不建议现在做

- **继续往表单加字段。** 8-21 已经证明这条路只会让录入更重。
- **在 AI 链路打通前重做视觉与组件。** 房子没通电，装修没有意义。
- **新增第 8 个 Agent 或开新 Phase。** 现有 7 个 Agent 的触发面都还没接满。

---

## 五、里程碑

| 时间 | 里程碑 | 判定 |
|---|---|---|
| 第 1 周 | 闸 1 + 闸 2 打通 | 生产 ≥1 eligible model；catalog / routes 一致性测试通过 |
| 第 2 周 | 闸 3 + 闸 4 打通 | Gate 通过后 3 分钟内可见结果；项目页内联显示 finding |
| 第 4 周 | P0 业务验收 | 2 周内 ≥20 条 finding，采纳率 ≥30% |
| 第 6 周 | P1 落地 | 工程师登录后 0 点击看到待办；项目标签 ≤6 |
| 待授权 | P2 闭环 | 钉钉 `delivery=true`；CEHub 只读 |

---

## 六、风险与缓解

| 风险 | 缓解 |
|---|---|
| P0.2 一次接 17 个事件会显著抬高 LLM 调用量与成本 | 分两批：先接 `TASK_STATUS_CHANGED` / `RISK_*` / `REQUIREMENT_*` / `ISSUE_STATUS_CHANGED`（高频、价值明确），观察一周成本与采纳率，再接 NCR / CAPA / COMPLAINT / MEMORY 一组 |
| P0.3 缩短去抖窗口会增加同一项目的重复分析 | 先确认 `_route_event` 的窗口合并逻辑在短窗口下仍能有效去重，再调参；分级去抖只对里程碑事件生效，高频编辑事件不动 |
| MiniMax-M3 的 `<think>` 输出已经打断过一次 JSON 解析 | 资格发布前确认 golden suite 覆盖带思维链的响应形态，否则生产上会以 `degraded` 形式静默失败，用户又会看到空 |
| 打开触发面后 finding 质量不足，反而制造噪音 | P0 验收用采纳率而非产出量把关；采纳率 <30% 时优先校准 prompt，必要时回退部分事件路由 |

---

## 附：本方案的证据边界

诊断基于代码走查与 8-21 生产首用修复报告，**未在生产环境实际操作或采样**。四道闸的机理来自静态分析（`model_catalog.py` / `runtime_contract.py` / `dispatcher.py` / `catalog.py`），事件路由的 27 vs 10 是脚本精确比对结果。P0 各项验收标准需要在真实租户上跑一轮才能确认阈值合理。
