# PDOS vNext 决策台账·冲突清单·改善项（整合版·已生效）

> **版本适用性修订（2026-09-10）**：本文保留8月决定原文。D25默认放行/blocklist、D26授权run内自主辩论继续有效；D3/D19/D32及第四节中模型直写业务草稿、单次转正的文字，按后续[V0/V1合同§3](2026-09-08-v0-v1-acceptance-and-pilot-contract.md)和[共同架构合同](2026-09-10-ai-native-architecture-consistency-contract.md)执行：模型业务Finding接受与独立应用、Agent业务表零直接写。运行快照/只读输出与确定性候选按各自窄合同处理。D35不扩大到非项目外部会议，立项前DCP/TR在产品工作区办理。当前队列为[整合清单](../../tasks/ai-native-integrated-todo.md)，不再按旧清单串行推进。

> 日期：2026-08-25
>
> 状态：**已生效执行**——2026-08-25 用户（PO）指示"开始"：组 1 共 11 项已决策（D17/D25/D26/D32-D38）；组 2/组 3/组 4 按推荐项通过执行；改选任何一项须按版本化修订本台账，不得静默改动
>
> 来源：`2026-08-24-pdos-vnext-unified-requirements.md`（统一需求稿），整合自
> 来源 A `2026-08-24-vnext-control-loop-upgrade-plan-draft.md` 与来源 B《PDOS_Module_Optimization_and_Roadmap_V1.0.docx》。
>
> 配套执行清单：`tasks/vnext-unified-todo.md`（批准后替代 `tasks/vnext-control-loop-todo.md`）。

---

## 一、决策清单（D1-D31）

按拍板方式分四组。每项完整论述见来源 A 第 5 节与统一需求稿第 3/5 节。

### 组 1：已决策（书面确认即可，不再讨论）

| ID | 主题 | 决策 | 决策人/日期 |
|---|---|---|---|
| D17 | CRM 边界 | V5 完全排除 CRM 与销售分析；现有 CRM Requirement ingress 保持现状、不扩展 | 用户，2026-08-21 |
| D25 | Agent 联网 | 开放 agent-reach 联网技能：**默认放行 + blocklist**（仅拦内网地址、登录/凭证页、可执行下载），全量抓取自动落 Evidence Snapshot 留痕；只读 GET，对外发送仍属硬闸区（见 D32） | 用户，2026-08-24；2026-08-25 按 D32 放宽为默认放行 |
| D26 | Agent 间对话 | 开放结构化评审辩论：席位制、立场锚定对象所有权、服务端图内编排、全程 transcript、产出带分歧记录的 Decision Brief；**Agent 可自行发起辩论**，以预算熔断为主控（见 D32）；真值动作仍走硬闸区人批 | 用户，2026-08-24；2026-08-25 按 D32 放宽触发与轮次 |
| D32 | 授权模式 | 从"事前审批"转向"**可逆 + 可观测**"：可撤销且有留痕的动作放开给 Agent 直接执行，人工审批仅保留给不可逆真值动作；详见第四节三级授权模型 | 用户，2026-08-25 |
| D33 | 交付模式 | **不做 MVP**：范围一次冻结（十条功能轴全量 + 盲区 G1-G24 补齐），交付分轨并行、按轴垂直切片持续验收；撤销 I1、V3-1 首发依赖限制、V5-3 最小链等 MVP 化条目。全量交付的排期后移风险已向 PO 声明。详见 `2026-08-25-vnext-full-scope-axis-closure-and-gap-analysis.md` | 用户，2026-08-25 |
| D34 | 使用边界 | **仅内部使用，无供应商外部账户**：不建供应商登录/协同门户与外部隔离面（G7/V4-15 移除）；供应商画像、交期/质量/打样数据保留，由内部 SQE/采购维护；对供应商沟通走既有渠道（邮件/钉钉），必要时人工回填 | 用户，2026-08-25 |
| D35 | 会议集成方式 | **自动创建钉钉会议或腾讯会议**（钉钉视频会议/日程 API、腾讯会议企业版 REST API）：例会按节奏策略自动建会，临时会议 Agent 起草、单击确认创建（确认区）；入会链接自动绑定 Meeting 对象并通知参会人；**转写稿首版人工上传**（会后传闪记/转写文件），深度转写拉取连接器不做（后续可选）；飞书不做；仅处理已绑定项目的会议（边界 6 不变） | 用户，2026-08-25 |
| D36 | 测试数据入口 | **Excel 提交 + AI 读取填充**：工程师上传测试 Excel，AI 解析映射为结构化 Test Run 草稿（自由区），人批量确认转正（确认区）；原始 Excel 保留为 Evidence；测试设备直采不做（G13/V4-13 延后，非 vNext 范围）；任务提前至 Phase 1 工程轨（V1-B10），与结构化 Test Run 同期交付 | 用户，2026-08-25 |
| D37 | 样机信息入口 | **以整机测试报告为准**：AI 从测试报告/Build 记录抽取样机编号、Build Configuration、版本、批次自动建档（与 V1-B10 同一导入管道），人工补充缺项；**不做条码/二维码/扫码与借用归还位置管理**；打样批次台账从报告与 Build 记录推导 | 用户，2026-08-25 |
| D38 | 管理层看板 | 新增管理层看板（Portfolio 域），双层结构：**① 决策请求中心与例外层**（硬闸待批 + Decision Brief 待决、健康度异常、Top 风险与延期传播、关键短缺、高/严重 Issue、Cost Gap）；**② 全项目进度总览层**——所有项目的阶段/Gate 位置、证据聚合进度（非手填百分比）、Baseline vs Forecast 偏差、下一里程碑倒计时、当前阻塞清单（blocking Issue/关键短缺/待批硬闸/上游依赖延迟，确定性判定）、PM 与健康度，可排序钻取到项目控制塔；全部确定性数据 + Executive Agent 解释，一键跳源；随 V3 首发，V4/V5/V6 数据面逐步接入 | 用户，2026-08-25 |

### 组 2：技术必然项（推荐批量采纳 B 项，选 A 均破坏可审计性或安全边界）

| ID | 主题 | 采纳内容 |
|---|---|---|
| D3 | 写出口 | **（被 D32 修订）**Agent 可直接写自由区对象（草稿态 Issue/Action/Knowledge Candidate、关联建议、派生字段、提醒）；正式对象转正走确认区单次确认；真值动作走硬闸区人批 |
| D4 | 自动延期 | 只改 Forecast 并生成影响方案；人批准后重基线 |
| D7 | 物料 SoR | ERP reference + as-of snapshot + 派生齐套，不复制库存真值 |
| D13 | Agent scope | runtime/context/Finding 演进为服务端绑定 typed scope；禁止虚拟 intake project |
| D15 | Build 物料 | Build 冻结 Prototype BOM version/snapshot/digest；ECN 产生新 revision/delta |
| D16 | 提案类型 | typed proposal payload + 白名单 apply adapter + 服务端真值复核 |
| D22 | 产品主数据 | PDOS 持上市前 Concept/Definition/Portfolio/Roadmap；发布后主数据归 ERP/PLM |
| D23 | 策略/定义发布权 | Agent 只起草比较；产品经理审核发布，IPMT/DCP 决策 |
| D24 | 量化指标 | TAM/SAM/SOM、机会分数、组合评分由确定性指标引擎计算；Agent 只解释 |

### 组 3：产品取舍项（需 PO 逐项拍板）

| ID | 主题 | 推荐 | 关键理由 |
|---|---|---|---|
| D1 | AI-only vs AI-primary | AI-primary：人工可录入，Agent 预填/建议；AI 停止时显式失能 | 符合已实现系统与制造业可用性 |
| D2 | Agent 扩张方式 | 运行时 Agent 收敛（6+1）+ 版本化 capability_key；**已被 D26 修订**：开放席位制辩论，但"一模块一 Agent"与自由群聊仍不做 | 运行时 Agent 是乘法成本，capability/席位是加法成本 |
| D5 | Issue 关闭治理 | Open 可暂存；进 Analysis 前强制 Owner/Verifier/日期/关闭条件；高/严重四眼硬规则，低/中项目可配置 | 追责闭环与小团队可用性平衡 |
| D6 | Meeting 实体 | Meeting/Agenda/Decision/Action Item 一等对象 | 否则无会议控制闭环 |
| D8 | 需求关系 | Opportunity/Requirement、Case/Requirement 多对多，兼容现有 primary link | 市场→IPD 是多对多 |
| D9 | 项目工作区 | 9 个制造业业务标签（配合 D31 两层制） | 比 7 个易发现、比 13+ 可控 |
| D10 | 提醒通道 | 先站内提醒/升级 + outbox；钉钉为经授权 delivery adapter | S5-1 真实外发未通过 |
| D11 | Issue vs NCR/CAPA | Issue 管协调；NCR/CAPA 保持质量事实，双向关联/升级（与 C7 裁决配套） | 万能问题对象是经典失败模式 |
| D12 | 8.21 可用性计划 | P0/P1 并入 Phase 1，不再独立实施 | 避免两条路线争人 |
| D14 | Gate 语义 | 保留 Gate 硬闸；新增 Decision Checkpoint 与 Technical Review 作为 readiness 输入 | 语义最清楚 |
| D19 | 会议纪要 Apply | 首次只固化 Minutes；每个提取项单独确认后 Apply | 降低错误扩散 |
| D21 | 第 7 个 Agent | 新增 Product Management Intelligence，并承担辩论"产品经理"席位 | scope 投影与现有 6 个不同构；席位需要立场锚定对象 |

（D18、D20 已分别被 D28、D25 修订，不再单独拍板。）

### 组 4：整合新增项（D27-D31，推荐采纳）

| ID | 主题 | 内容 | 来源 |
|---|---|---|---|
| D27 | 工程对象骨架 | Sample Build Configuration、结构化 Test Run、Requirement-Spec-Test 追溯、Decision 一级对象、Evidence-based Gate、Action 来源对象，并入 Phase 1 工程轨 | 来源 B P0 |
| D28 | Task 降级为 Action | 所有 Action 必须标记来源对象、预期输出、完成证据；个人工作台聚合各来源 Action（扩展并替代 D18） | 来源 B |
| D29 | Test 升一级模块 | Test Plan→Case→Run→Result→Evidence→Issue 结构化模型；关键指标入库不入附件 | 来源 B P0 |
| D30 | Decision 一级对象 | Context/Options/Evidence/Trade-offs/Rationale/Approver/Consequence，P0 上线 | 来源 B P0 |
| D31 | 两层信息架构 | 全局域导航（十项）+ 项目工作区 9 标签 + 独立产品管理工作台 | 两来源合并 |

---

## 二、冲突清单（C1-C10）

两来源之间、以及与现行系统/canonical 之间的冲突及裁决。裁决均已反映在统一需求稿中，此处供 V0 走查确认。

| ID | 冲突 | 来源 A / 现状 | 来源 B / 用户新决策 | 裁决 |
|---|---|---|---|---|
| C1 | Agent 数量与形态 | 现有 6 个冻结；D21 拟加第 7 个；禁止对话 | B 明确"保持五个"；用户要求带立场对话（产品经理/项目经理/结构/硬件/DQE） | 运行时 6+1 收敛；辩论席位与运行时 Agent 解耦（结构/硬件 = Engineering 的两个 persona）；对话仅限图内辩论（D26） |
| C2 | 信息架构 | D9 项目内 9 标签 | B 附录 A 全局 10 项导航 | 两层制并存（D31）：B 管全局域导航，A 管项目工作区 |
| C3 | 阶段划分 | Phase 0-6（控制链交付分期） | P0-P3（对象成熟度分期） | Phase 0-6 为骨架；B-P0 并入 Phase 1 工程轨（D27），B-P1 并入 Phase 2/4，B-P2 分散至各 Phase 的 Agent 介入，B-P3 ≈ Phase 6 |
| C4 | CRM 集成 | D17 已决策排除 | B"集成优先钉钉、ERP、CRM" | 按 D17：CRM 仅保留现有 Requirement ingress，不进产品管理链 |
| C5 | Task 地位 | D18 仅会议 Action 作为 Task kind | B 全面降级 Task 为对象派生 Action | 采 B（D28），D18 废止合并 |
| C6 | Agent 联网 | D20 禁止自由 HTTP，仅离线采集层 | 用户决策允许联网 | agent-reach 受控技能（D25）：联网开放但全部走证据快照管道；采集调度层保留用于订阅式来源 |
| C7 | 问题对象统一度 | D11：Issue 与 NCR/CAPA 分离 | B 5.4：Engineering Issue 统一承载 Engineering/Quality/Supplier/Test Failure/Certification 问题 | 折中：单一 Issue 对象族 + 类型化工作流承载研发协调；NCR/CAPA/8D 保持质量域对象并与 Issue 双向关联——B 的"统一"指类型化，不指合并质量事实 |
| C8 | Evidence Snapshot 时序 | 原 V5-1 在 Phase 5 才建 | D25 使全体席位需要证据快照 | 底座提前至 Phase 2；Phase 5 只扩展产品管理专用连接器 |
| C9 | Meeting 实体 | 现行 UI 已移除会议页签；D6 拟重建一等对象 | B 未涉及会议实体，但 Action 提取依赖会议 | 按 D6 重建；B 的会议 Action 提取落在 D28 的 Action 来源对象上 |
| C10 | 健康度/风险来源 | A 以 Forecast 偏差、提醒 SLA 表达 | B 要求 Project Health Engine 六维健康度 + Risk Radar | 健康度与规则型 Risk Radar 归确定性引擎（改善项 I6/I7）；预测型风险推迟到 Phase 6 后评估 |

---

## 三、改善项清单（I1-I12）

对统一方案本身的改善建议，非新功能需求；各项标注落点。

| ID | 改善项 | 内容 | 落点 |
|---|---|---|---|
| I1 | ~~Phase 5 体量控制~~ | **已被 D33 撤销**：V5 全量建设，不收敛；风险缓解改为轴级垂直切片验收 + Pilot 陪跑 | — |
| I2 | 平台轨显式分离 | V1-10（typed proposal）/V1-11（capability_key）是架构改造，与"我的工作/Issue 闭环"用户轨分开排期与验收，避免 Phase 1 预期失真 | 执行清单 V1 分轨 |
| I3 | scope v3 合同前置 | typed scope v3 触碰全部 Agent 的路由与测试；合同在 V0 冻结（实现可推迟），避免 V1-10 依赖悬空 | V0-3 |
| I4 | 契约漂移尽早修复 | 前后端 Finding/Agent 类型契约漂移（V1-9）在任何新 Finding 类型之前完成，未知类型 fail-close | V1 控制轨最前 |
| I5 | PMI 能力分批灰度 | 第 7 Agent 的 8 个 capability 分两批（research/competitor/market → strategy/definition/matrix），每个独立质量线，不达标单独停用 | V5 |
| I6 | 健康度确定性化 | Project Health Engine 六维（Schedule/Engineering/Quality/Cost/Supplier/Certification）由确定性引擎从对象证据聚合，Agent 只解释；禁止 LLM 打分 | V3/V4 附属交付 |
| I7 | 风险雷达分两步 | 规则型 Risk Candidate（来源对象状态驱动）先行；预测型风险（延期/复发预测）推迟到数据积累后 | V1 规则型 / Phase 6 后评估 |
| I8 | 红队范围扩展 | 新增辩论投毒（reach 抓取的恶意内容影响 Decision Brief）与席位越权（读取非锚定对象）两类零穿透测试 | V2 起随辩论/reach 交付，V6 总验 |
| I9 | 指标基线校准 | 来源 B 的目标值（≥90%/95%/80% 等）以 Pilot 实测为基线校准后再定阈值，不直接作为验收硬线 | V0-4 |
| I10 | 知识闭环提前接线 | Issue Closure→Knowledge Candidate 的自动候选在 V1 Issue 闭环落地时同步接线（shadow），不等 Phase 5 | V1 工程轨附属 |
| I11 | 单日工作流验证 | 按来源 B 11.1：为研发工程师与品质工程师设计"单日工作流"走查，验证系统减少而非增加录入负担；作为 V1 Exit 的可用性门槛 | V1 Exit |
| I12 | 真实模型质量测试 | 每个 capability/席位的 golden cases 必须含真实模型运行，不得只用预制 JSON/schema 测试代替（含辩论 transcript 质量样本） | 全阶段 DoD |

---

## 四、D32 三级授权历史记录（模型业务写部分受2026-09-08合同修订）

原则：**安全通过"可逆 + 可观测"实现，不通过"事前审批"实现。**凡是可撤销、全留痕的动作，Agent 直接执行；人工介入只保留给不可逆的真值动作。审计、快照、事件留痕对 Agent 无感，不构成能力限制。

### 4.1 三级授权

| 级别 | 动作 | 授权方式 |
|---|---|---|
| **自由区（Agent 直接执行，零确认）** | 读取对象图；agent-reach 检索/抓取；分析、总结、比较、Brief；**直接创建草稿态对象**（draft Issue/Action/Risk Candidate/Knowledge Candidate/关联建议）；更新派生字段（Forecast 展示、健康度解释、提醒）；发起辩论；生成 Decision Brief | 全量落 Event/Audit + 快照；草稿态对业务真值无副作用，可一键忽略/清理 |
| **确认区（单次确认，支持批量）** | 草稿转正式对象；建立正式关联；修改正式对象非关键字段；发布 Knowledge；生成 Test Plan | **单动作确认**（原 Accept+Apply 双动作合并）；同类可批量勾选；确认后可撤销（保留前值） |
| **硬闸区（人批，必要时四眼，仅此清单）** | Baseline/Commitment 变更；Gate/DCP/TR 结论；BOM Freeze；ECN 生效；供应商选定；高/严重 Issue 关闭；对外发送（邮件/钉钉外发/任何 POST）；删除或覆盖历史；涉及金额 | 保留双动作与授权角色；高/严重四眼 |

### 4.2 对既有决策的修订汇总

| 原决策 | 修订 |
|---|---|
| 边界 1/2（Finding 唯一写出口、Accept/Apply 双动作） | 改为三级授权：自由区直接写草稿态；确认区单动作；仅硬闸区保留双动作/四眼 |
| D3 | Agent 可直接写草稿态与派生字段（见组 2 修订） |
| D5 | 高/严重四眼保留（硬闸区）；低/中级关闭进确认区单动作 |
| D16 | typed proposal/apply adapter 仅硬闸区必需；确认区简化为"草稿转正"单接口 |
| D19 | 会议纪要：Minutes 与低风险候选项（Action/关联）可批量单次确认；只有涉及硬闸区对象的候选保留逐项确认 |
| D25 | allowlist-first → 默认放行 + blocklist；取消首次访问人工放行 |
| D26 | 触发白名单 → Agent 可自行发起；轮次上限 → 预算熔断为主；shadow 期 → 一场人工比对合格即转正 |
| DoD"shadow→Finding→Apply 三段灰度" | 仅硬闸区相关 capability 保留三段灰度；自由区 capability 直接上线，靠审计与质量指标事后治理 |

### 4.3 保留的最小安全核（这些保护功能，不限制功能）

1. **租户与 scope 隔离**：服务端冻结，跨租户零穿透——泄漏事故会直接摧毁产品信任；
2. **全量审计与证据快照**：对 Agent 无感，只是留痕，是"可逆"的前提；
3. **硬闸区清单**：仅 4.1 表中所列，不得随场景临时扩充，也不得被 Agent 或页面内容绕过；
4. **注入内容标注**：外部抓取内容标记不可信来源，**只标注不拦截**，由引用 preflight 在硬闸区动作时校验；
5. **只读 GET**：联网不带副作用——这是防"对外发送"绕过硬闸，不是限制检索能力。
