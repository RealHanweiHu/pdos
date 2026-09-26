# PDOS vNext 统一执行清单（历史交付与验收细则）

> **2026-09-09 后续工作已迁入 [AI-native 整合执行清单](ai-native-integrated-todo.md)**，顺序与验收见[整合执行计划](../docs/design/2026-09-09-ai-native-integrated-execution-plan.md)。本文件保留历史 checkbox、详细证据和验收条款，不再是活动执行队列。新清单逐项映射本文 84 个编号条目，历史完成切片不自动等于完整能力或 Phase Exit 通过。
> 历史：本文件于 2026-08-25 根据用户/PO 指示“开始”进入执行态，当时替代 `tasks/vnext-control-loop-todo.md`。下文涉及“当前”、迁移预留号、整 Phase 前置与施工建议，以新版明确的指针和实际迁移 head 为准；未被修改的验收细则继续继承。
> 2026-09-08 UX10 本地增量：三页查询/加载、移动首屏和失败重试已验证；桌面最终冷缓存 P95 229/317/245 ms，339 项前端与 94 项受影响后端回归通过。详见 [验证记录](../docs/reports/2026-09-08-ux10-first-screen-validation.md)；真实试点及手机网络采样仍待，不提前勾选 Phase Exit。
> **V0-2 已于 2026-09-08 确认：补验 S5-1，与 D14-04 的 V0/V1 联合推进**（用户：“一起验证吧”）。先做本地与资料准备，生产及真实外发仍逐次授权；不据此宣布任何 Exit 通过。

> 本文件是 `docs/design/2026-08-24-pdos-vnext-unified-requirements.md` 的候选任务清单。
> 决策台账（D1-D38）、冲突（C1-C10）、改善项（I1-I12）见 `docs/design/2026-08-25-vnext-decision-conflict-improvement-register.md`；
> 功能轴闭环、盲区（G1-G29）、体验合同（UX1-UX10）、角色/PM 实务核对见 `docs/design/2026-08-25-vnext-full-scope-axis-closure-and-gap-analysis.md`。
>
> 迁移事实：生产最后验证 `0032`；vNext 迁移自 `0034` 单调递增（当前本地 head 随任务推进，见各任务记录）；生产配置与部署状态不受本清单影响（V0-2 联合补验不等于部署授权）。
>
> 交付模式（D33）：**全量范围、不做 MVP**；三轨并行、按功能轴垂直切片持续验收。
> 体验合同 UX1-UX10 为各 Phase Exit 硬条款；文末附"决策/盲区 → 任务"覆盖索引供走查。

> **2026-09-08 验收收口**：[V0/V1 验收与试点合同 v1](../docs/design/2026-09-08-v0-v1-acceptance-and-pilot-contract.md) 统一冻结判据、证据层级、真实链路、指标和签核记录。用户已选定主试点 **D14-04**；用户负责系统开发与系统验收，实际业务由多人协作；业务角色按项目具名分工，真实基线及阈值在运行中校准。V0 冻结与 V1 Phase Exit 仍未通过，历史本地全绿不等于当前快照或真实试点通过。

> **2026-09-08 V1 并行改善补验**：驾驶舱风险单请求聚合/完整摘要、项目阶段批量查询、My Work 未确认风险过滤及最小依赖安全升级已完成本地功能与运行验证。见 [记录](../docs/reports/2026-09-08-v1-usability-performance-validation.md)。V1-A6/A7/A8 周期扫描接线现已完成本地增量，151 项受影响回归及真实进程/HTTP 验证通过，见 [调度记录](../docs/reports/2026-09-08-v1-reminder-scheduler-validation.md)。完整类型门禁和冻结候选复验仍待并行工作收口；未部署，V1 Phase Exit 不勾选。

## 2026-09-09 整体架构复核（本地静态审计，未实施新能力）

用户要求重新确认整个 AI-native 架构。已完成 [十轴职责、运行机制、缺口与验收场景](../docs/design/2026-09-09-ai-native-architecture-reconfirmation.md)：保留数字链与控制链，补明初始规划为十轴共同入口；四专业含 ID 与嵌入式，当前辩论席位尚未覆盖两者。

- AR-01～AR-07 对应初始规划、跨轴计算引擎、业务接线、专业应用出口、授权/调度合同、结果回链与市场/知识闭环；均已关联本文既有工作项，不新增或自动勾选阶段。
- 六个 Agent/13 个 capability 登记不等于完整功能；固定事件分析、规则自动化、专用测试对话、服务/API 与端到端用户能力分开说明。D32 自由区/确认区与代码、shadow 标签与执行门禁仍需统一核验。
- 下方历史 `[x]` 保留其切片交付意义。会议 AI、整项目规划、完整齐套/排程/成本等不得据底座记录宣称可用。无生产操作或新权限变更，各 Exit 保持原状态。

## 2026-09-09 产品主线遗漏审计（未实施新合同）

用户指出初始任务流程应在项目开始时确认。审计发现：当前项目创建仅实例化阶段/Gate，缺少产品内 AI 初始计划生成、审阅、独立应用及正式任务/基线连接。V0-6 模板与 V3 时间控制已有落点，但整项目规划闭环没有形成可用入口和完整验收；静态指引和预设脚本模拟不计作该能力通过。

- 详见 [遗漏审计、能力边界及验收案例](../docs/reports/2026-09-09-ai-native-planning-gap-audit.md)。
- 建议补充 V0-6 与 V3-1～V3-6 的关联合同：项目输入、候选、任务/依赖与负责人、ID 计划、版本化时间、应用幂等及变更监测；在合同收口后按纵向能力实施。
- 本条记录审计和建议，不自动冻结对象/权限合同，不改已有阶段 checkbox，不把未完成的 V3 提前裁决通过。

## Gate V0：产品决策与执行授权

- [x] V0-1：PO 逐项确认决策台账 D1-D38（**2026-08-25 完成**：组 1 共 11 项已决策；组 2/组 3/组 4 按推荐项通过；结论记录于决策台账头部；改选走版本化修订）
  - 验收：38 项均有结论；冲突 C1-C10 裁决走查；盲区 G1-G29 落点确认（见清单文末覆盖索引）
  - 验证：决策台账 + 覆盖索引对账完成
  - 依赖：当前讨论
- [x] V0-2：处置 Sprint 5 Exit 与 vNext 关系（**2026-09-08 选定补验 S5-1，与 D14-04 联合推进**；补验本身未完成）
  - **当前口径**：按验收合同 §8 准备 S5-1 与 D14-04 联合验收；先做本地与资料准备，真实身份/生产/外发按具体操作授权。S5-1 出口未通过，生产 `delivery=false`。
  - 验收：三选一明确；生产 `delivery` 状态不被隐式改变
  - 验证：canonical、AGENTS、`tasks/todo.md` 指针一致
  - 依赖：V0-1
- [ ] V0-3：冻结对象/SoR/权限/事件/迁移兼容合同 + typed scope v3 合同（I3）
  - **草案已产出（2026-08-25）**：`docs/design/2026-08-25-vnext-object-contract-v1.md`——含存量硬规则继承、五域关系图、新对象字段字典（会议/Test Run/SBC/FW/辩论/证据/CCR/排期/提醒）、三级授权 Finding-apply 改造、scope v3 语义、0034-0059 迁移分段；4 个开放项待走查裁决
  - 验收：统一对象关系图与最小字段字典；scope v3 语义冻结（实现推迟至 V5-8）；新增对象状态机、错误码、降级边界完整；vNext 迁移从 `0034` 起
  - 验证：架构/安全/质量/ERP Owner 审查（待安排）
  - 依赖：V0-1
- [ ] V0-4：冻结三级授权模型、辩论协议与 agent-reach 政策（D25/D26/D32）
  - 验收：三级授权清单书面化（自由区/确认区/硬闸区，硬闸区为封闭清单不得临时扩充）；席位表（产品经理/项目经理/结构/硬件/DQE/供应商可选）及立场锚定对象；辩论预算熔断参数、Agent 可自行发起；Decision Brief schema；reach blocklist（内网地址/登录凭证页/可执行下载）与快照留痕政策；注入内容"标注不拦截"策略
  - 验证：安全 Owner 走查最小安全核（租户隔离、全量审计快照、硬闸封闭清单、只读 GET）
  - 依赖：V0-1
- [ ] V0-5：冻结试点与基准指标（I9）
  - 验收：Pilot 项目选定（**D14-04，用户于 2026-09-08 确认**，用经授权现有资料回放完整数字链）；业务/数据/质量/ERP Owner 确认；指标目标值以 Pilot 实测校准后定阈值；匿名化 golden cases（含真实 Excel 测试报告、钉钉/腾讯会议转写样本）就位
  - 验证：能取得匿名化会议、Issue、排期、物料、测试报告样本与当前基线
  - 依赖：V0-2、V0-3
- [ ] V0-6：模板库与配置化合同（G2/G3/G9）
  - **2026-09-08 AI 对话本地增量**：[AI 对话调整测试项](../docs/design/2026-09-08-ai-test-plan-conversation-contract.md) 已接通模板/用户要求 → 多轮候选与依据/差异 → Finding 审阅、独立应用 → 项目修订计划（迁移 `0058_ai_test_plan_changes`）；后续补齐文件/规格/关联需求选择与版本复核，当前 prompt v5。真实 MiniMax-M3/浏览器完成新品类信息不足、客户冲突、文件应用；完整工程与场景边界见 [补验记录](../docs/reports/2026-09-08-ai-test-plan-acceptance.md)。未知条件保留待补，旧报告与公共模板保留；真实要求试配、用户最终关闭与广泛语义质量仍待，不关闭 V0-6。应急启动仅为示例，不添加到 D14-04。
  - **2026-09-08 用户确认补充**：[项目类型与测试模板合同](../docs/design/2026-09-08-project-type-test-template-contract.md)：锂电汽车泵/锂电自行车泵/帐篷泵等按类型选择版本化测试模板，项目可按规格增减项并留痕；报告格式映射不决定必测清单；未测试/不适用/参考/合格/不合格分开。D14-04 类型已由用户确认为**锂电自行车泵**；用户已确认以所提供自行车泵模板为基线，D14-04 仅排除照明灯（17 项整机 + 12 项可靠性），汽车泵等按差异调整；不再逐项重问功能。配置化实现与试配仍待验收。
  - **2026-09-08 测试模板切片**：只读版本化目录 + 计划独立快照/确认来源 + 稳定用例标识 + 已确认结果证据覆盖 + 质量页签配置界面已实现，本地迁移 `0057_test_template_snapshot`；D14-04 29 必测、照明不适用；14 项聚焦与 249 项前端完整测试通过，真实浏览器验证 0/29；完整后端回归 666 项通过。见 [验证记录](../docs/reports/2026-09-08-test-template-validation.md)。这只覆盖测试模板首版，不关闭 V0-6 全部范围。
  - 验收：Stage/Gate/Issue 类型/checklist/字段配置化模板；项目号/文控/样机序列号编号规则；中英双语基座；多产品线流程变体不硬编码
  - 验证：产品/工程/品质 Owner 按两条产品线试配模板
  - 依赖：V0-3
- [ ] V0-7：存量数据导入与冷启动方案（G1）
  - 验收：进行中项目导入向导；AI 解析历史测试报告/问题清单/会议纪要为草稿对象（自由区落草稿、人批量确认）；映射校验与回滚
  - 验证：用 Pilot 项目真实历史资料试导入
  - 依赖：V0-5、V0-6

### Checkpoint V0

- [ ] PO 明确回复"批准 vNext 统一合同与执行顺序"
- [ ] canonical 范围变更按项目纪律版本化，不覆盖历史计划
- [ ] 既有本地候选与冻结合同差异逐项裁决，生产及外部操作授权边界核对完成
  - 2026-09-08 校准：原条款“未发生代码、生产或外部系统变更”属于执行前草案口径；2026-08-25 已获本地开始指令且存在实现，不能再按“无代码变更”验收。保留生产/外部操作独立授权要求，本次不补签历史 Gate。

## Phase V1：个人工作、问题闭环与工程对象骨架（三轨并行）

### V1 控制轨（用户功能）

- [x] V1-A1：修复 Finding/Agent 前后端契约漂移（**2026-08-25 完成**）
  - 已交付：FINDING_TYPES 补 `supplier_delay_risk`/`executive_portfolio_brief` + 中文标签与 Agent 标签；TaskStatus 补 `pending_approval`（标签"待批准"、无转移按钮与后端 frozenset 一致）；列表解析改为"结构损坏抛错、未知枚举逐条跳过并告警"（Finding 列表/Brief/质量控制/任务/问题/风险六处）；新增跨端合同快照测试 `server/tests/test_frontend_contract_sync.py`（后端契约 ↔ 前端枚举集合相等，防再漂移）；tsconfig 排除 iCloud " 2" 副本
  - 验证：web 全量 149 测试通过、typecheck 零错、新增 parser 测试 5 项、合同快照测试 2 项通过；真实浏览器回归待 Phase 1 整体验收（需全栈环境与种子数据）
  - 依赖：V0
- [x] V1-A2：跨项目 My Work 查询合同与服务端聚合（**2026-08-25 完成**）
  - 已交付：`GET /api/me/work?limit=`——按登录用户聚合六类（Task 开放态/Issue owner/Risk owner/CAPA owner/Gate 待签槽位按角色映射/Finding 待审）；每类含项目引用、到期日排序（nulls last）、limit 截断 + 全量 counts；新增 `Action.MY_WORK_VIEW`（内部五角色授权，供应商/客户 403）；成员边界：非管理员仅见本人所属项目内条目；实现 `app/domain/my_work.py` + `app/api/my_work.py`，每类恒定 2 条 SQL、零 N+1
  - 验证：6 项 API 测试通过（跨项目聚合排序/成员边界/跨租户隔离/Gate 槽位随角色 + CAPA/外部角色 403/limit 与计数）；RBAC 冻结矩阵测试显式更新并通过（18 项回归绿）；性能基线并入 Phase 1 出口验收
  - 依赖：V0
- [x] V1-A3：My Work 前端与角色自适应落地页（**2026-08-25 完成**）
  - 已交付：`/my-work` 页面（六分区：任务/问题/风险/CAPA/Gate 待签/AI 待审，逾期红标、项目 chip、截断提示"共 N 条显示前 M"、每行深链跳源到项目对应标签或 AI Review）；导航新增"我的工作"（外部角色隐藏）；**工程/质量角色登录 `/` 自动落地 My Work（UX1 零点击）**，owner/admin/PM 保留驾驶舱并可切"组合视图"；全空引导态（G4）、外部角色受限态、错误重试态；解析器沿用"结构损坏跳行告警"策略
  - 验证：新增组件测试 5 项（分区/深链/逾期/截断、空态、坏行跳过、403 受限、工程角色重定向）；web 全量 154 测试 + typecheck 通过；真实浏览器 320/1440 走查并入 Phase 1 出口验收（需全栈种子数据）
  - 依赖：V1-A2
- [x] V1-A4：Issue 责任与关闭合同（**2026-08-25 完成**，D5/C7）
  - 已交付：**迁移 `0034_issue_accountability`**（vNext 首条迁移）——issues 增列 issue_type（五类 CHECK）/verifier_user_id（复合 FK）/closure_criteria/closure_evidence_ref/reopen_count；**四眼约束固化进 DB CHECK**（高/严重 owner≠verifier）；有损降级守卫。领域层：open 可暂存、进 analysis 强制 Owner+Verifier+目标日期+关闭条件（仅拦转移，存量行兼容）、高/严重关闭仅限 Verifier 本人。权限拆分：新增 `issue.assign/execute/verify` 三 Action（分派字段需 assign——工程师不能自派；关闭走 verify），RBAC 冻结矩阵同步。API/前端契约全量同步（含 fixtures）
  - 验证：6 项专项测试（权限拆分正反例/分派不全 409/四眼 409+DB 约束/高严重仅 Verifier 关闭/低级 Owner 可关/存量行兼容）+ 生命周期回归测试更新 + RBAC 22 项 + 前端 154 项 + typecheck 全绿；迁移守卫拒绝与降级/升级往返实测通过；低/中级关闭的项目级配置钩子留待 V0-6 模板政策
  - 依赖：V0
- [x] V1-A5：Issue 验证、退回、重开与关闭证据纵向切片（**2026-08-25 完成**）
  - 已交付：状态机扩边 verification→action（退回）、closed→action（重开）；**只有 Owner 能提交验证**（他人 409）；**只有 Verifier 能退回**（退回原因入审计 context）；高/严重关闭**必须附关闭证据**（ISSUE_CLOSURE_EVIDENCE_REQUIRED）；证据只能经关闭转移写入（PATCH 不可触达=不可静默覆盖）；重开自增 reopen_count、清 closed_at/证据，**原关闭记录完整保留在审计快照**（实测可查回）。前端问题面板重做：验证态双按钮（通过关闭/退回）+ 高严重关闭内联证据必填 + 退回原因必填 + 重开按钮 + 类型/重开次数徽章
  - 验证：新增 2 项流程测试（非 Owner 提交/非 Verifier 退回/证据缺失 409/重开计数与审计快照回查）+ 全部回归绿（后端 11、前端 154、typecheck）；真实浏览器闭环并入 Phase 1 出口验收
  - 依赖：V1-A4
- [x] V1-A6：规则型 Risk Candidate（**2026-08-25 完成**，I7 第一步 + D32 自由区首例）
  - 已交付：**迁移 `0035_risk_candidates`**——risks 增 draft_state（draft/confirmed/cleared）、origin_key（租户级部分唯一索引=幂等键）、rule_key/source 引用；确定性规则引擎 `domain/risk_candidates.py` 首批三条规则（任务逾期/问题逾期/测试失败，影响度按优先级/严重度映射，零 LLM）；扫描端点 scan（新建/来源恢复自动 cleared/条件复发同行复活，全程 Event+Audit）；**确认区单动作** `/risks/{id}/confirm` 草稿转正；正式风险列表只显示 confirmed（草稿不进 My Work/驾驶舱）；未确认草稿禁止编辑/转移（409 RISK_NOT_CONFIRMED）
  - 验证：3 项专项测试（三规则生成与影响度映射/重扫幂等+恢复清除+复发复活同一行/确认转正与草稿编辑守卫）+ 回归绿（work-items、my_work、AI apply 路径、前端 154）；迁移守卫与往返实测通过。2026-09-08 已接 V1-A7/A8 周期进程，自动范围复核、系统审计与恢复/复发通过本地验证；联合门禁状态见页首
  - 依赖：V1-A4
- [x] V1-A7：Reminder Policy、扫描与站内通知（**2026-08-25 完成**，自主循环时段交付）
  - 已交付：**迁移 `0036_reminders`**（cehub_event.reminders：dedupe_key 租户唯一=重放不重发、状态机 scheduled→fired→acknowledged/cancelled 双 CHECK 固化）；确定性策略引擎八类提醒——接单、T-3/T-1/到期/逾期+1/+3 阶梯（任务按 assignee、问题按 owner）、停滞 7 天、待验证（发给 Verifier）、**逾期+3 升级至项目负责人**（escalation_level=1）；来源恢复自动取消未发提醒、已发历史保留；scan 端点支持 as_of 时钟注入（可测试）；新事件类型 REMINDER_STATE_CHANGED 入目录；**站内通知中心**：`GET /api/me/notifications`（未读计数 + 按策略 digest 汇总）+ 收件人限定 ack；My Work 页新增通知区块（未读徽章、升级标记、"知道了"确认）
  - 验证：历史 4 项时钟/幂等/取消/收件人隔离测试 + 目录/审计回归 + 迁移守卫与往返 + 前端 155 项 + typecheck 全绿。2026-09-08 补齐独立周期触发，与 V1-A6 共用时钟；提醒生命周期专项增至 11 项，周期专项 18 项，含真实连续进程/重启/SIGTERM；真实 HTTP 来源恢复取消 scheduled、fired 历史保留。无新迁移，联合门禁状态见页首
  - 依赖：V1-A2、V1-A5
- [x] V1-A8：钉钉 delivery adapter（**2026-08-25 完成**，自主循环时段交付；S5-1 Gate 完整保留）
  - 已交付：**迁移 `0037`** 扩展 outbox operation 白名单加 `reminder_dm`；派发适配器 `integrations/reminder_delivery.py`——已触发提醒复制为钉钉**个人机器人消息**（batchSendOTO），幂等键 `reminder:{id}` 复用 outbox 租户唯一约束；**S5-1 门禁沿用现有 outbox 模式**：`delivery=false` 时落 `manual` 态 + DINGTALK_DELIVERY_DISABLED（零外发、可对账、授权后可重放），enabled 时才入 `pending`；未绑钉钉的收件人跳过计数；"打开我的工作"链接由服务端从校验过的 public_base_url 构建；投递执行器新增 reminder_dm 分支
  - 验证：4 项专项（禁用停手 manual+重派幂等/未绑定跳过/启用转 pending/OTO 客户端 fake provider 载荷断言）+ 钉钉 outbox/delivery/api 全家桶 20 项回归 + 迁移守卫与往返全绿；真实外发仍需 S5-1 人工授权（环境开关 PDOS_DINGTALK_DELIVERY_ENABLED）
  - 2026-09-08 周期派发增量：租户锁下配额/去重/入箱/审计同一连接和事务；18 项专项覆盖系统 actor、单连接池、手动/周期同与跨项目竞争及整批回滚。开发/部署模板与旧镜像回滚接线完成，真实 HTTP 的 5 条 outbox 均 manual、attempts=0；完整记录见页首，未据此部署或通过 S5-1
  - 依赖：V1-A7
- [x] V1-A9：现有 Agent 事件覆盖、运行可见性与现场 Finding（**2026-08-25 完成**，自主循环时段交付）
  - 已交付：**事件路由完备性合同**——目录全部 61 个事件类型必须有显式 route（12 个）或 no-route（49 个，按四类理由分档）决策，完备性测试双向校验（无漏判、无悬空引用），未来新增事件强制拍板；补路由 2 条高价值事件（ISSUE_STATUS_CHANGED→Project、NCR_CREATED→Quality）；**运行可见性**：`GET /api/ai/projects/{id}/runs`（防抖/排队/运行中/完成/降级/失败 + 事件数 + 错误码）+ 项目 AI 页"Agent 运行状态"卡（状态徽章、诚实空态"队列为空不代表就绪"）+ **本项目待审 Finding 计数直达 AI Review**（现场入口）
  - 验证：完备性测试 + 路由冻结测试更新 + 运行列表/成员边界 2 项 API 测试 + dispatcher/ai_api 回归 + 前端 156/156 + typecheck；顺手修复环境性抖动（iCloud 盘负载致 import 长达 200s，vitest 超时 5s→20s，account-security 用例隔离验证为环境抖动非代码问题）
  - 依赖：V1-A1
- [x] V1-A10：Review Inbox 与确认疲劳治理 + AI 治理看板（UX3/G23/G24）（**2026-08-26 完成**，自主循环时段交付）
  - 已交付：**digest**——`GET /api/ai/review-inbox` 按项目聚合三类草稿（硬闸 Finding 按能力接受率+置信度排序、规则风险候选、导入待确认批次）+ 归档计数，/ai-review 页新增摘要条与候选/归档区块；**TTL 归档可恢复**——migration 0046 给 findings/finding_actions 加 archived/restored 状态与转移 CHECK，`FindingService.archive_stale`（14 天默认、成员范围过滤、全量 action+event+audit）+ `restore`，API `POST /api/ai/findings/archive-stale`、`POST /api/ai/findings/{id}/restore`，前端一键归档+恢复；**批量确认 diff 预览与撤销**——/ai-review 候选区块复用 C1 的 confirm-batch/unconfirm/dismiss，确认前预览 draft→confirmed 及 L×I 分值，确认后可一键撤销整批；**推送疲劳护栏**——`PDOS_REMINDER_DAILY_DM_CAP`（默认 50/人/日）+ `PDOS_REMINDER_QUIET_HOURS`（默认 21:00-08:00 Asia/Shanghai）在 dispatch 入口强制（静默时段整体顺延、按 payload.recipient_user_id 记数限流），dispatch 响应新增 deferred_quiet_hours/capped_recipients；**AI 治理看板**——`/governance/ai` 管理页 + `GET /api/ai/usage`（预算/熔断/按 agent+prompt_version 聚合）+ `GET /api/ai/capabilities`（C2 合同+质量控制）；**失能态逐触点清单**——`GET /api/ai/touchpoints` 列 6 个 AI 触点（brief/chat/文档解析/风险建议/测试导入/事件 Agent），模型不可用或预算耗尽时逐触点给出 enabled/degraded/disabled 与人工替代路径（导入触点降级仍可零模型复用已识别模板）
  - 验证：后端——归档往返+审计链（test_findings_api）、inbox 聚合分组/计数（含归档后迁移）、touchpoints/usage 合同（test_ai_api）、静默时段顺延与日上限限流正反例（test_reminder_delivery，含出箱真实时钟与 as_of 日界对齐）；前端——ai-api 守卫 6 项（含不安全 href 拒绝）、extras 组件 4 项（diff 预览先行、批量撤销、忽略、归档恢复）、治理页 2 项（含 narrowed 熔断显示与非管理员拦截）；`make test` 全绿（web 156 vitest + server 477 pytest）+ lint/typecheck 全绿（顺手清偿 my-work effect 同步 setState lint 债）；真实浏览器走查按既定模式推迟到 Checkpoint V1 Phase Exit 统一执行
  - 依赖：V1-A3、V1-C1
- [x] V1-A11：组织模型、代理与交接（G5/G6）（**2026-08-27 完成**，自主循环时段交付）
  - 已交付：migration 0047——`departments`（租户内唯一名、自引用父子）、`user_delegations`（窗口有序/双方相异/撤销一致性 CHECK + 按代理人索引）、`users.department_id/manager_user_id`（含 `manager_not_self`），带"存在组织结构/汇报线/委托即拒绝回滚"守卫；**汇报线与升级链**——`escalation_chain` 深度上限 12 且防环，设置归属时从拟任上级向上回溯，成环拒绝（409 `REPORTING_CYCLE`）；**休假委托**——`OrganizationService.grant/revoke`，`ProjectAccessService` 变为委托感知：代理人**只借用委托人的项目可见范围，不借用角色**（`is_allowed` 仍按代理人自身角色判定），窗口外/已撤销一律不生效，直接成员路径零额外查询；四眼因代理人始终以本人身份行事而天然保持（DB `four_eyes_distinct` 仍是最终防线）；**离职批量移交**——`hand_over` 只移交在办的问题负责人/验证人、任务、风险、项目负责人与直接下属（已关闭/已完成的历史保留原负责人以维持审计真实），同时撤销相关委托并停用原账号，写一条带分类计数的 `USER_RESPONSIBILITY_TRANSFERRED` 事件与审计；新增 4 个事件类型（`DEPARTMENT_CREATED`/`USER_DELEGATION_GRANTED`/`USER_DELEGATION_REVOKED`/`USER_RESPONSIBILITY_TRANSFERRED`，均显式登记为 no-route）；7 个管理端点 `/api/admin/organization/*`（USER_MANAGE 鉴权）；前端 `/governance/organization` 管理页（部门、归属、代理状态徽章、交接前确认对话框并回显各项计数）+ 导航项
  - 验证：`tests/test_organization_api.py` 6 项（升级链与成环拒绝、委托窗口内外正反例+撤销幂等、未开始/已过期/自我代理拒绝、委托下四眼仍被 DB 拒绝、移交只动在办工作且历史留原主+事件仅一条、全端点仅管理员）；`tests/test_project_access_policy.py` 新增 3 项（借范围不借角色、非成员委托人不授权、直接成员不走委托查询）；迁移 0046↔0047 往返 + 元数据漂移 + 冻结表清单 + RBAC 回归通过；`make test` 全绿（web 160 vitest + server 486 pytest），lint/typecheck 全绿
  - 修复：`use_alter` 自引用外键写在 `create_table` 内不会下发到数据库（元数据漂移检查捕获），改为建表后独立 `create_foreign_key`
  - 依赖：V1-A4
- [x] V1-A12：信息架构重组（D9/D31/D38 导航落地）（**2026-08-27 完成**，自主循环时段交付）
  - 已交付：**全局十域导航**——侧栏按 Home/Portfolio/Products/Projects/Engineering/Quality/Delivery/Knowledge/AI Workbench/Admin 分组既有页面，域内空则整域隐藏（外部角色不再看到项目组合/知识/AI 工作台），移动端仍为扁平条；项目内域（Engineering/Quality/Delivery）深链到工作区对应标签；新增 `/portfolio` 组合页（按目标日期紧迫度排序、逾期计数、钻取到项目；证据聚合与 Baseline/Forecast 偏差随 V3 管理层看板接入）；**项目工作区 9 标签**——概览·控制塔｜计划·资源｜工作项｜物料·供应｜工程·变更｜例会·决策｜Gate·交付物｜试制·测试·质量｜文档·知识，概览·控制塔吸收原「时间线」与「AI 对话」，工作项合并原「任务/问题/风险」，工程·变更承接原「产品工程」；**旧路由兼容**——`LEGACY_TAB_ALIASES` + `resolveTab` 让改造前生成的链接（书签、已发钉钉卡片、历史证据 href）落到吸收它的域，未知标签返回 null 而不猜测；发链方（`ai.py`/`findings.py`/`my-work-view`/`ai-review-inbox-view`）改发新键；**UI baseline 升至 v0.3**（记录两层架构、标签合并映射与兼容规则，AGENTS.md 同步）；计划·资源与物料·供应的数据面分别属 V3/V4，以显式「本域数据将在哪一期接入、今天在哪里看」呈现，不用空白页冒充已交付
  - 验证：`project-workspace-tabs.test.ts` 4 项（九域自解析、六个退役键的吸收去向、退役键全覆盖不留死链、未知标签拒绝猜测）；`workspace-shell.test.tsx` 4 项（管理员十域齐全、项目内域指向对应标签、工程师隐藏管理项、外部成员整域移除且保留产品/项目）；既有 173 项前端用例按新 IA 更新后全过（外部成员可见标签 2→1、概览多一个 AI 对话活动区的断言收敛）；`make test` 全绿（web 177 vitest + server 486 pytest），typecheck/lint 全绿
  - 修复：`review_inbox.py` 自 V1-A10 起就在发 `tab=work-items`，而该标签在旧十标签体系中不存在（点击落回默认页）；九标签方案使其成为真实目标
  - 依赖：V1-A3

### V1 工程轨（D27，数字链对象骨架）

- [x] V1-B1：Requirement/Spec 分层与验证追溯（**2026-08-25 完成**，自主循环时段交付）
  - 已交付：**迁移 `0039_req_spec_traceability`**——requirements 增 tier（customer/market/product 三层 CHECK）+ parent 自引用（客户需求→产品需求层级）；specifications 增 requirement_id/owner/verification_method/acceptance_criteria/**criticality（standard/key）**；test_cases 增 specification_id（Spec↔Test 关联，Verification Coverage 成立）；**确定性覆盖率服务** `GET /spec-coverage` 四桶——无规格需求（项目需求链）、关键 Spec 无验证路径、验证失败、**Spec 变更晚于最后执行=需重验**；Spec 创建 API 全字段透传；前端类型/守卫/fixture 同步
  - 验证：2 项专项（全字段创建/四桶确定性对账）+ 迁移守卫与往返 + **全量 schema 漂移测试 60+ 项**（顺带完成 11 个 head 版本钉从 0033→0039 的纪律性更新、冻结表清单登记 reminders 表——0034-0039 六条迁移与 metadata 零漂移实证）+ 前端 156 项 + typecheck；期间修复 revision ID 超 32 字符问题（alembic_version 列宽约束）
  - 依赖：V0
- [x] V1-B2：Sample Build Configuration（D37 报告驱动建档）（**2026-08-27 完成**，自主循环时段交付）
  - 已交付：配置表既有 PCB/结构/FW 版本、关键零件供应商、Build Date、来源（manual/report_extract）与草稿态（V1-B10 管道产出）；本次补齐 migration 0051——**BOM 修订关联**（`development_bom_id` 链到 development_boms，BOM 行自带 version，链接本身即修订号；列表 join 出 `bom_code`/`bom_version`）与 **Issue→Sample 关联**（缺陷记在具体哪台机器上：不同装机配置上的同一现象不是同一个发现），带"存在 BOM 修订或 Issue 样机归属即拒绝回滚"守卫；**Sample Comparison** `POST /npi/sample-configurations/compare`——六个可比字段（bom_revision/pcb/structure/fw/build_date/key_component_suppliers）逐一对齐并直接给出 `differing_fields`
  - 关键判断：供应商映射按**排序键值对**比较，JSON 键顺序不制造假差异；无配置记录的样机单列 `missing_configuration_sample_ids` 而非混入结果显示成空行（一行空白读起来像"没有差异"，是误导）
  - 验证：`tests/test_sample_comparison_api.py` 7 项（BOM 修订入库并 join 出 code+version、比较精确命名差异字段且相同字段不误报、供应商键序不算差异、缺配置样机单独报告、退化输入 422/401、Issue 命名样机+越界样机拒绝、Test Run 样机绑定守卫）；迁移 0050↔0051 往返；`make test` 全绿（web 177 vitest + server 511 pytest），ruff 全绿
  - 修复：Issue 引用越界样机原本只被数据库外键拦下并暴露为原始错误，补服务层 `_validate_sample` 范围校验后返回干净 404，与其他引用对象一致
  - 说明：Shipment 对象属交付域（V4），未在本期建立；`samples.prototype_bom_id`（计划 BOM）与配置表 `development_bom_id`（实际装机 BOM 修订，可由测试报告抽取）语义不同，两者并存为有意设计
  - 依赖：V1-B10
- [x] V1-B3：结构化 Test Run（**2026-08-25 完成**，D29/G28，目标驱动时段交付）
  - 已交付：**迁移 `0040_test_runs`** 新表——同一用例多次执行终于可表达（run_number 租户内唯一递增）；结构化字段全套：conditions（对象）/metrics（数组：name/value/unit/target/verdict）/equipment/environment/操作者/样机关联/证据文档关联/draft_state（为 B10 AI 导入预留草稿态）；**长周期测试**：in_progress + expected_completion_at（G28），完成单次终结（重复完成 409）；终态自动回写父用例状态与执行人；**失败自动建 Issue**：无关联时自动创建 test_failure 类 Issue（严重度按用例映射，open 暂存态），再次失败复用同一 Issue 零重复；TEST_FAILED/ISSUE_CREATED/NPI_RECORD_CHANGED 事件同事务齐备；API：记录/完成/列表三端点
  - 验证：3 项专项（终态记录与用例同步/失败自动建单与幂等复用/长周期流转与重复完成拒绝）+ 冻结清单登记 + npi 回归 + **经 0000 全链降级/升级往返实证**；顺带修复 initial_schema fixture 与有损守卫的测试序耦合（降级前显式清测试库）
  - 依赖：V1-B1
- [x] V1-B4：Decision 一级对象（**2026-08-25 完成**，D30，自主循环时段交付）
  - 已交付：**迁移 `0038_decision_contract`**——decisions 补齐一级对象合同：context/options（数组）/trade_offs/consequence/evidence_refs（数组）/owner/approver/issue 关联；**decision_kind 从自由字符串收敛为 11 值 CHECK**（存量 4 系统类 + 7 新类，迁移前置脏值扫描）；**硬闸衔接**：follow_up_state（none/pending/completed）+ 必填备注，"待执行硬闸动作"显式可见、执行后回写（轴 2 断点闭合）；DecisionService + API（创建/列表/follow-up 完成），手工创建仅限 6 个人工类 kind（gate_review 等系统类保留给对应服务，422 拒绝越权写入）；DECISION_RECORDED 事件复用既有目录定义入项目时间线
  - 验证：3 项 API 测试（完整合同字段+时间线事件断言/follow-up 单次完成/跨项目引用 404+系统类 kind 422+存量 kind 兼容）+ 旧 Decision 写入方（development_cases/change_governance）回归 8 项全绿 + 迁移守卫与往返；Issue/Test 等更多关联在对应对象落地后经 evidence_refs 与后续关联列扩展
  - 依赖：V0
- [x] V1-B5：Action 来源对象与完成证据（**2026-08-26 完成**，D28，目标驱动时段交付）
  - 已交付：**迁移 `0043_task_action_contract`**——tasks 增 kind（六类 CHECK：task/meeting/issue/gate/change/risk_action）、source_entity(+id)、expected_output、completion_evidence_ref；**DB CHECK 固化"Action 必有来源"**（kind≠task 强制 source 双列非空）；创建时按 kind 校验来源对象在项目内真实存在（issue/risk/gate/ECR 四类已接，meeting_action 待 V2 会议实体）；**Action 完成必须附完成证据**（TASK_EVIDENCE_REQUIRED 409），普通任务语义不变；**完成后反向更新来源对象**——issue/risk 来源自动 touch + ISSUE_UPDATED/RISK_UPDATED 事件 + 专项审计（issue_action.completed）；My Work 天然聚合（assignee 制）；无第二套待办真值（Action=Task 的 kind）
  - 验证：2 项专项（来源必填 404/证据缺失 409/证据完成+来源反哺审计实测、普通任务不受影响）+ work-items/my_work/initial-schema 回归 + 迁移守卫与往返 + head 钉推进 0043 + 前端 156 项与 typecheck（类型/守卫/fixtures 同步，未知 kind 前向兼容跳行）
  - 依赖：V1-A2
- [x] V1-B6：Evidence-based Gate 首版（**2026-08-27 完成（模板部分待 V0-6）**，自主循环时段交付）
  - 已交付：migration 0052——**四种裁决**取代原二选一（gates.status 增 `conditional`/`hold`）：「带条件通过」叫成「通过」就把条件丢了，「暂缓」也不是「驳回」（工作没做错，只是在等）；**条件放行必须逐条写明负责人/到期日/关闭证据**，直接落成 V1-B5 的 `gate_action` 任务（source_entity=gate），因此自动进「我的工作」并受既有完成证据强制约束，而非一句没人回看的评审意见；服务层两头卡死（带条件的干净通过、不带条件的条件通过都拒绝，二者都是自相矛盾的记录）；条件放行仍要求就绪度通过——它推迟的是剩余工作，不是已要求的证据；**无证据不得完成**从服务层提升为数据库 CHECK（`NOT is_gate OR status <> 'completed' OR evidence_reference IS NOT NULL`），直连数据库也绕不过；**Build 用途枚举**新增（engineering_build/certification_sample/customer_sample/reliability_test/production_trial），默认工程试制
  - 既有底座（前期已交付）：Entry/Exit 就绪度阻塞（阻塞任务/严重 Issue/高分风险/未完成 gate checklist 项）、签核轮次与四眼、祖父豁免、只读快照
  - 验证：`tests/test_gate_api.py` 新增 5 项（条件放行落成带负责人+到期日+关闭证据的 gate_action、条件只属于条件放行的双向拒绝、暂缓是可重开的独立结局、gate 交付物无证据入库被 DB 拒绝而带证据成功、送样用途枚举含认证送样+默认值+非法值拒绝）；迁移 0051↔0052 往返；`make test` 全绿（web 177 vitest + server 516 pytest），ruff 全绿
  - 修复：条件任务需与项目 workflow 配对才满足 `ck_tasks_stage_pair_consistent`；gate 往返测试与本次新增的有损降级守卫冲突（前序测试残留数据），按 `test_initial_schema` 同一做法在往返前清空租户数据
  - **待 V0-6（需人拍板）**：PVT/MP Gate 转产交接 checklist 模板内容（Frozen BOM Handoff、SOP/治具就绪引用、认证状态、遗留 Issue 清单）属模板库范畴，V0-6 验收要求「产品/工程/品质 Owner 按两条产品线试配模板」，需 Owner 走查确认
  - 依赖：V1-B1、V1-B3、V0-6
- [x] V1-B7：Issue Closure→Knowledge Candidate 自动候选（I10）（**2026-08-27 完成**，自主循环时段交付）
  - 已交付：migration 0048——memories 增 `source_issue_id`（租户内唯一 + 三列来源互斥 CHECK 由二选一扩到三选一 + 项目内 Issue 复合外键），带"存在 Issue 来源候选即拒绝回滚"守卫；`app/domain/knowledge_candidates.py` **确定性规则**（零模型调用，符合 D32 自由区只留给规则引擎）——从关闭人已填的根因/解决方案/关闭标准组装 `## 小节` 正文，标题「经验：{Issue 标题}」，tags=(issue_closure, issue_type, severity)，applicability 记录来源类型与严重度；**来源与证据保留**——source_refs 含 `issue` 与 `closure_evidence` 两条引用；**发布走确认区单动作**——候选落 `draft` 态不改变任何真值，沿用既有 memory verify 四眼（作者不能自己发布）
  - 关键判断：**空关闭不产候选**（只有关闭标准而无根因/解决方案时返回 `nothing_learned`，空壳笔记会教团队"知识库是噪音"）；**重开再关不重复**（唯一约束 → `already_exists`）；**候选生成不绑架关闭**（生成逻辑在关闭事务提交之后，冲突被吞掉并返回原因码——关闭是用户的动作，知识捕获是附带收益）
  - 验证：`tests/test_knowledge_candidates.py` 6 项（候选内容+来源+证据引用、重开再关不重复、空关闭零候选、发布需第二人（自发布 409/他人 200）、正文组装纯函数正反例、预置冲突候选下关闭仍成功）；memory/issue 回归 + 迁移 0047↔0048 往返 + 冻结清单；`make test` 全绿（web 177 vitest + server 492 pytest），ruff check/format 全绿
  - 修复：alembic autogenerate 按名比对 CHECK 约束、不比对表达式——扩宽后的 `source_mutually_exclusive` 未被检测，迁移中显式 drop+recreate，否则数据库会留旧两路约束且漂移测试看不出来
  - 依赖：V1-A5
- [x] V1-B8：客户需求变更链（G18）（**2026-08-27 完成**，自主循环时段交付）
  - 已交付：migration 0050 `customer_change_requests`（cehub_product，7 值状态 CHECK、生命周期一致性 CHECK 强制每个状态携带该步应有的时间戳与字段、`reply_four_eyes` CHECK、工期范围、项目内 code 唯一、客户/需求/ECR/五类用户复合外键），带"存在已批准商务答复即拒绝回滚"守卫；**双轨隔离**——CCR 是独立对象与独立 URL 前缀 `/api/projects/{id}/customer-changes`，可**引发**内部 ECR 但永不**是** ECR（`engineering_change_request_id` 只记录因果，工程轨保留自己的审批链）；**确定性影响分析**——沿 V1-B1 追溯链（需求→子需求→规格→测试用例）实际计数并给出 `retest_required`（已通过用例需重测数=这次变更买来的工期代价），不问模型"可能影响什么"，答复可随时回数据库对账；**对外报价硬闸**——拟报价人不能自批（服务层 403 + DB CHECK 双重），且步骤不可跳过（未做影响分析直接报价 409）；六个端点（列表/创建/分析/报价/批准/客户决策/关联 ECR），沿用 CHANGE_VIEW/EDIT/APPROVE 权限
  - 验证：`tests/test_customer_changes_api.py` 6 项（影响分析按真实追溯链计数且无关需求分支不泄漏、受理→分析→报价→批准→客户确认→关联 ECR 全链+六条审计动作、自批 403 与他人批准 200、跳步 409 正反例、CCR 不出现在 ECR 列表、越界引用与跨项目 404/401）；迁移 0049↔0050 往返 + 冻结清单登记；`make test` 全绿（web 177 vitest + server 504 pytest），ruff 全绿
  - 说明：D34「不考虑供应商外部账户，只内部使用」下，"对外发送"落为内部可追溯的批准动作（谁拟、谁批、何时），实际传递走线下渠道；与 S5-1 出箱门禁一致
  - 依赖：V1-B1
- [x] V1-B9：知识主动推送（轴 10 补链）（**2026-08-27 完成**，自主循环时段交付）
  - 已交付：migration 0049 `knowledge_pushes` 推送台账（context_kind 三值 CHECK / rank 1-20 / 相似度 basis points / engagement 一致性 CHECK / `(tenant, context_kind, context_entity, memory)` 唯一），带"存在已引用推送即拒绝回滚"守卫；**补上真实缺口——跨项目检索**：既有 `MemoryService.search` 限定单项目，而"相似项目、失败案例"本质是跨项目的组织记忆，新增检索跨项目但租户内隔离，非管理员仅见自己参与项目的记忆（`member_scoped` 走 project_members EXISTS）；**三个触发时机**（project_kickoff / change_request / part_selection）各自用确定性规则从触发对象（项目名+描述 / ECR 标题+原因 / 规格标题+验收标准）组装查询，不调模型编造；**三层降噪**——相似度下限 0.30、单次上限 5 条、`(context, memory)` 唯一使被跳过的建议不再反复冒出（重复检索标 `already_seen` 而非灌重复行）；**指标真实测量**——`POST /api/knowledge/pushes/{id}/engage` 记录实际点开（首次生效，重复点开不虚增），`GET /api/knowledge/push-metrics` 给出推送量/引用数/命中率/分上下文明细
  - 验证：`tests/test_knowledge_push.py` 6 项（立项拉出他项目相关经验且排除不相关的、草稿态永不推送、重复检索标 already_seen 且台账不增、引用驱动命中率且只计一次+未知推送 404、非管理员只见自己项目的记忆而 owner 可见全部、未知上下文 422 与触发对象缺失 404 且零台账）；迁移 0048↔0049 往返 + 冻结清单登记；`make test` 全绿（web 177 vitest + server 498 pytest），ruff 全绿
  - 修复：`:member_user_id IS NULL` 传 NULL 时 Postgres 无法推断参数类型（AmbiguousParameter），需显式 `CAST(... AS uuid)`
  - 依赖：V1-B7
- [x] V1-B10：Excel 测试报告 AI 导入（**2026-08-26 完成**，D36，目标驱动时段交付）
  - **2026-09-09 DUP-01 修复**：真实 D14-02 复传发现同内容新增批次；按用户要求补同租户/项目/计划/内容复用、批次状态提示与概览刷新。四个原件场景零新增，并发与失败回滚保护、相关后端 30 项、前端完整 343 项及最终增量 10 项、类型/构建及浏览器通过。见 [修复验收](../docs/reports/2026-09-09-d14-02-import-deduplication-fix.md)。不改变完整 V1-B10 试点与阶段出口待办。
  - **2026-09-08 真实样本补验未通过**：历史勾选保留为原平表交付记录，不代表真实多页报告适配。修复前解析器仅取首表，把两份样本封面当数据；后续已补多页解析，重新识别 18/12 个测试页，21 项聚焦回归通过，详见模板合同 §6。本轮后端完整回归 661 项、前端完整测试 246 项、静态/类型检查与 Webpack 构建通过，见 [补验记录](../docs/reports/2026-09-08-test-report-import-validation.md)；类型模板覆盖及真实试点仍未收口。详见 [合同与复现](../docs/design/2026-09-08-project-type-test-template-contract.md)。Phase Exit 不得据原勾选推定通过。
  - 已交付：**迁移 `0041_test_report_import`**（autogenerate 生成保证零漂移）——import_mapping_versions（模板指纹+版本化映射+superseded 链）与 test_report_import_batches 两表；**架构核心：LLM 只提列映射、行数据由确定性代码按映射抽取**——同模板首次经 quality_intelligence 网关校准（提示词 v1 含注入防护声明），人确认后映射入库，**二次上传零模型调用**（测试实证 gateway 调用数不增）；上传即入 documents 管道（原始 Excel=Evidence 附件）；样机 SN 自动匹配、未知用例/未知结果值逐行跳过留痕、映射置信度入批次；**runs 落 draft 态零副作用**（用例状态不动），confirm 单动作批量转正 + 用例同步 + 失败自动开单（复用 B3 sync 函数）+ 映射版本固化
  - 验证：2 项端到端（模型路径草稿导入含跳行/确认转正+失败开单+映射持久化+重复确认 409+二次导入 mapping 路径）+ 迁移守卫与往返 + 15 项回归 + head 钉推进 0041；多模板脏数据 golden 扩展（合并单元格/多 sheet）与解析准确率看板接线随 Pilot 真实报告补充
  - 依赖：V1-B3
- [x] V1-B11：固件/软件版本轻对象（**2026-08-26 完成**，G25，与 B2 同迁移交付）
  - 已交付：fw_releases 轻表（项目内版本唯一、发布人/说明/时间）；Sample Build Configuration 引用具体 FW 版本；**版本从测试报告 AI 抽取自动 find-or-create**（幂等）；开发过程留 Git、PDOS 零代码管理；固件缺陷走 Issue 类型化（V1-A4 已备 engineering/test_failure 类）
  - 验证：导入端到端断言固件版本落库与幂等复用；关联完整性经外键约束保证
  - 依赖：V1-B2

### V1 平台轨（I2，架构改造独立验收）

- [x] V1-C1：三级授权执行层（D32）（**2026-08-26 完成**，自主循环时段交付）
  - 已交付：**自由区**——规则扫描直落草稿（A6 既有）+ 新增 `POST /risks/{id}/dismiss` 一键忽略（migration 0045 `dismissed_at` 标记：忽略在本次事发期内持续生效，来源恢复后自动复位，再次触发会重新浮出）；**确认区**——`POST /risk-candidates/confirm-batch` 批量转正（逐条返回 confirmed/already/not_found）+ `POST /risks/{id}/unconfirm` 撤销（仅限规则候选，审计 `risk.candidate_unconfirm`；confirm 事件 ID 改为每次唯一以支持撤销后重确认）；**硬闸区**——Finding apply 重构为类型化适配器白名单注册表（`FindingService._APPLY_ADAPTERS`，未注册 payload fail-close），migration 0044 将 `apply_lifecycle_consistent` CHECK 扩展到对象合同封闭清单（risk/memory/issue/task/test_run/sample_build_configuration/knowledge_candidate/schedule_change_proposal/material_exception）
  - 验证：`tests/test_three_tier_authorization.py`（批量确认分桶、撤销留痕+重确认、忽略持续/复活语义、误用 409）；`test_finding_schema.py` 新增 CHECK 白名单正反例；`test_agent_database_security.py` 新增 `pdos_agent` 对 6 张 vNext 新表零授权 sweep（information_schema.role_table_grants + 直连 SELECT/DELETE 拒绝）；迁移 0043↔0045 往返通过；head pin 批量更新至 0045；顺带清偿本轮 sprint 的 ruff 债（`ruff check .` + `format --check` 全绿）并补上 `test_project_access_api` 工程师动作清单（issue.execute/issue.verify/my_work.view）；完整门禁 `make test`（web 156 vitest + server 464 pytest）全绿
  - 依赖：V0-4
- [x] V1-C2：capability_key 运行合同（D2）（**2026-08-26 完成**，自主循环时段交付）
  - 已交付：`app/ai/capability_contract.py` 封闭注册表——12 个冻结 CapabilityKey（agent 前缀强制），每条合同独立承载 zone（hard_gate/confirm，模型能力禁入自由区）、rollout（三期 agent 硬闸能力=shadow）、prompt_version（逐能力钉版）、finding_types、projections、tools（来自 tool_definitions_for_agent）、quality_control；`resolve_capability`/`capability_for_finding`/`capabilities_for_event` 未知即 fail-close（UnknownCapabilityError）；Finding 预检的散落 allowed_types 收编为合同解析（`finding_writer.preflight_assessment` 走 capability_for_finding）；新增 `GET /api/ai/capabilities` 能力级指标端点（合同 + 按 (agent_key, finding_type) 关联质量控制快照，FINDING_VIEW 鉴权，no-store）
  - 验证：`tests/test_capability_contract.py` 6 项冻结测试——前缀冻结+注册表全覆盖、finding_type 唯一归属且覆盖全部 FindingCandidateType、路由矩阵与 `_EVENT_AGENT_ROUTES` 一致且仅解析硬闸能力、未知能力 fail-close 正反例、prompt 版本与 prompt 文件/PROMPT_VERSIONS 同步、zone/rollout 不变式（硬闸必有 finding+tools+quality control，confirm 无 finding，三期 shadow）；`test_ai_api.py` 新增端点合同断言（12 键序、zone/rollout/版本、401）；预算/熔断沿用既有两层（租户级 token 熔断在 gateway budget circuit、能力级 narrowing 在 finding quality projection，均有既有测试）；完整门禁 `make test`（web 156 vitest + server 471 pytest）+ ruff check/format 全绿
  - 依赖：V1-A1、V1-C1

### Checkpoint V1

- [x] 一条 Issue 完成"发现→负责人→行动→提交验证→独立确认→关闭/退回→提醒"（**2026-08-28 实测**）
  - 在种子 Pilot 项目上以真实多角色令牌走通七步：非负责人提交验证被拒（409 `ISSUE_SUBMIT_REQUIRES_OWNER`）→ 负责人提交验证 200 → 非验证人关闭被拒（409 `ISSUE_CLOSE_REQUIRES_VERIFIER`）→ 验证人无证据关闭被拒（409 `ISSUE_CLOSURE_EVIDENCE_REQUIRED`）→ 验证人退回行动 200 → 负责人再次提交 200 → 验证人凭证据关闭 200；关闭后 V1-B7 自动生成 `draft` 知识候选（正文由根因+关闭标准确定性组装，含 Issue 与关闭证据两条来源引用），审计 `issue.transition`×4 + `memory.create`，事件 `ISSUE_STATUS_CHANGED`×4 + `MEMORY_DRAFT_CREATED`
- [ ] Pilot 项目一条真实数字链端到端跑通（需求→规格→样机→测试→问题→决策→Gate 证据），关键数据不再只存附件；其中测试与样机数据经 Excel AI 导入产生
- [ ] 研发/品质工程师"单日工作流"走查通过：录入负担减少而非增加（I11）
- [x] Agent 输出按三级授权落地：自由区直落草稿全留痕、确认区单动作、硬闸区双动作（**2026-08-28 浏览器实测**）
  - 自由区：规则扫描确定性产出 2 条风险候选并落草稿，`risk.candidate_create`×2 留痕，界面可单条忽略；确认区：勾选后单动作批量确认，确认前逐条 `draft → confirmed` diff 预览，写入后提示"确认后可撤销"，`risk.candidate_confirm`×2 留痕，两条风险进入真值列表；硬闸区：Finding 的 accept 与 apply 在 UI 与服务端均为两个独立人工动作（既有 `test_findings_api` 与本次收件箱界面同时佐证）
- [ ] 完整门禁与真实浏览器验收通过，人工确认 Phase Exit
  - **2026-08-28 真实浏览器验收已执行**（自主循环时段）：`server/scripts/seed_pilot_chain.py` 把数字链做成可重复种子（需求→子需求→规格→测试用例→试制批次→样机+装机配置→失败测试运行→问题→决策→Gate→客户变更，含组织/汇报线/休假代理）；本地起 API+Web 后以品质角色登录，走通：A12 十域导航与九标签渲染、旧链接 `tab=product-engineering` 兼容跳转到「工程·变更」、规则引擎从种子确定性识别 2 条风险候选、收件箱按三级授权呈现自由区草稿、勾选批量确认弹出逐条 `draft → confirmed` 预览、确认写入后候选归零且两条风险进入真值列表、审计留下 `risk.candidate_create`×2 与 `risk.candidate_confirm`×2
  - **验收抓到的真缺陷（已修）**：BFF 路由层从未跟上后端——前端调 `/api/me/work` 而 Next.js 无对应路由，「我的工作」页在真实应用里一打开即「暂不可用」；组件测试全部 mock `fetch`，故 A5 交付至今未暴露。同类缺口共 9 处（`/api/me/*`、`/api/ai/review-inbox|touchpoints|usage|capabilities|findings/archive-stale`、`/api/admin/organization/*`、风险候选 4 条）。按仓库既有的受控 catch-all 代理模式补齐（路径分段白名单 + 转发会话令牌），并新增 `src/app/api/bff-coverage.test.ts` 守卫：扫描前端全部 `fetch("/api/...")` 目标与实际路由处理器对账，缺一即失败（含"两侧都非空"的自检，防止扫描静默为空而假通过）
  - **2026-08-28 真实模型端到端验证**（用户提供 MiniMax cn key，模型 MiniMax-M3）：golden 评测 3/3 一次通过（`attempts: 1`），实跑算出的 suite digest 与已发布资格文档一致，等于独立复核该资格仍成立——结构化输出解析、provider adapter、prompt 格式在真实模型上全部成立（M3 输出 `<think>` 推理块未破坏解析）；租户治理显示 MiniMax-M3 为 eligible/available；真实 AI 对话回答严格建立在数据库真值上（四条服务端映射引用：Issue/任务/项目/Gate，准确反映刚关闭的 Issue 与 preparing 的 Gate，无编造）；证据不足时 fail-close 返回 `insufficient_evidence` 且零引用；完整门禁在真实 key 存在下仍全绿（测试继续走 FakeGateway，隔离正确）
  - **配置修正**：`.env` 中 MiniMax 原指向国际站且型号为 M2.7，按 cn 区实测两端点后改为 `https://api.minimax.chat/v1` + `MiniMax-M3`；OpenAI key 归位 `PDOS_LLM_OPENAI_API_KEY`（未跑 golden，故不进白名单——闸门按设计生效）
  - **运维风险（需留意）**：`uvicorn` 直接启动不加载 `.env`，`ModelCatalog.from_environment(os.environ)` 因此读不到供应商配置，表现为 `eligible_models` 为空、AI **静默不可用而非报错**；`scripts/dev.sh` 路径无此问题，生产拉起方式需确保环境变量真正注入
  - **顺带清理**：`web/src/app/api/` 下 6 个 iCloud " 2" 空壳路由目录（逐个比对确认零文件且正名目录俱在后删除）；它们本会成为 Next.js 路由树里可访问的死路径
  - **2026-08-28 `make check` 全链修复**：此前整场只跑 `make test`（vitest+pytest，**不含 typecheck**），因此未察觉本会话新增代码把 `make typecheck` 从绿弄成 **221 个 mypy 错误 / 37 个文件**（经比对：37 个全为本次新建或修改，零个原有文件失败）。现已清零（257 文件 Success），`make check`（audit-dependencies → lint → typecheck → test → build）整链通过
  - 其中数条**并非注解噪音，而是真实的类型不诚实**：`TestReportImportService` 的 `gateway`/`object_store` 声明为必需但 confirm 路径传 `None`（B10 本就设计为确认阶段零模型调用，签名未表达；现改为可选并在解析路径显式检查）；`FindingService.list` 方法遮蔽内建 `list`，令同类内所有 `-> list[...]` 标注静默失效；`_APPLY_ADAPTERS`（C1 的 apply 白名单，安全边界）挂在类定义之外，类型系统完全看不见；`InboxItem.created_at` 标成 `object` 实为时间戳；`app/domain/my_work.py` 将整片 SQLAlchemy 行对象标成 `object`，等同关闭该文件的类型检查
  - **方法教训**：修复中曾用正则批量改测试文件，两次破坏语义（把 `.one()` 当 `.all()` 包 `list()`、破坏多行 import 括号配对），已手工修回并以受影响的 25 项测试确认行为无损。正则适合改文本，不适合改代码结构
  - **仍需人工**：Phase Exit 的正式确认、以及下方 Checkpoint V0 的 PO 批准与 V0-2~V0-7 冻结项

## Phase V2：例会决策闭环 + 证据/联网/辩论底座

- [x] V2-1：Meeting/Agenda/Transcript/Link 数据与权限合同（D6/D35）
  - 验收：会议类型/项目范围/参会人/议题/来源/保留策略明确；Meeting 可绑定钉钉会议链接或腾讯会议；私聊与未授权会议不可接入
  - 验证：迁移、tenant/RBAC、审计与删除/归档政策
  - 依赖：V1
  - **2026-08-28 交付**：迁移 `0053_meeting_contract` 建 5 张表（`meetings` / `meeting_participants` / `meeting_agenda_items` / `meeting_transcripts` / `meeting_transcript_segments`），全部带 `tenant_id` + `UniqueConstraint(tenant_id,id)` + 携租户复合 FK；域服务 `app/domain/meetings.py`、API `app/api/meetings.py`、BFF `web/src/lib/meetings-bff.ts` + `meetings/[[...meetingPath]]/route.ts`；新增 RBAC 动作 4 个（`meeting.view` / `meeting.manage` / `meeting.transcript_upload` / `meeting.link_manage`）与事件 `MEETING_STATE_CHANGED`；15 项后端测试 + 3 项 BFF 路由测试
  - **三条设计决定**（都写在代码注释里）：① 会议强制 project 作用域——项目成员是本系统唯一的授权锚点，无项目的会议没有任何东西可校验"未授权会议不可接入"；跨项目会议需要 portfolio 级授权模型，属 V6。② 外部会议按整体绑定——provider/会议号/入会链接/绑定人/绑定时间五列同进同出（DB CHECK），provider 白名单 + 强制 https，聊天深链（`dingtalk://im/chat?...`）与 http 均被拒；已绑定不可静默改绑。③ 转写稿按内容寻址——同样字节重传返回原记录（`reused_existing=true`）而非分叉，V2-5 的引用锚点因此稳定。参会人必须已是项目成员，否则 400——邀请列表不能成为扩大项目可见范围的通道。
  - **DB CHECK 抓到一个真实设计漏洞**：从 `scheduled` 直接完成的会议（没人点过"开始"）会写入 `actual_end_at` 而无 `actual_start_at`。修法是不编造：没有观测到的开始就不记录结束时间，而不是拿计划时间冒充事实；已加测试 `test_completing_a_never_started_meeting_invents_no_actual_times` 钉住
  - **顺带修好守卫**：`bff-coverage.test.ts` 的 `covers()` 此前只认必选 catch-all `[...x]`，不认可选 catch-all `[[...x]]`，且对必选 catch-all 少算一段（允许零段匹配）。已同时修正两处
  - **两个冻结契约测试各抓到一处不诚实**：① `test_every_catalog_event_has_an_explicit_route_or_no_route_decision` 要求每个事件显式声明有路由或无路由——`MEETING_STATE_CHANGED` 判定为**无路由**，并同步把事件目录里虚报的 `agent_dispatcher` 消费者删掉（V2-5 建成 `meeting_minutes` capability 后再接）。② `test_project_access_http_path_is_tenant_bound_and_membership_gated` 的工程师动作清单需同步新增两项
  - **流程教训**：此条目连跑六轮 `make check`（每轮 12-18 分钟），分别被 import 排序、`ruff format`、`tsc` 可选 catch-all 类型、mypy `list` 遮蔽、两个冻结契约各挡一次——这些本地几十秒就能串起来跑完。后续条目一律先跑 `ruff format && ruff check && mypy && pytest <相关测试> && tsc`，全绿再进全链
- [~] V2-2：钉钉/腾讯会议自动建会（D35）**（fake provider 全绿，真实凭证待授权）**
  - 验收：例会按节奏策略自动创建（模板带默认参会人与议程）；临时会议 Agent 起草、单击确认创建（确认区）；钉钉视频会议/日程 API 或腾讯会议企业版 API；入会链接自动绑定 Meeting 并通知参会人（走 outbox，受 S5-1 约束）；改期/取消同步；转写稿会后人工上传
  - 验证：fake provider、创建/改期/取消幂等、API 失败降级为手工建会；真实租户凭证另行授权、服务端托管
  - 依赖：V2-1
  - **2026-08-28 交付**：迁移 `0056_meeting_recurrence` 建 `meeting_recurrences`、给 `meetings` 加 `recurrence_id`/`occurrence_date`、并**显式扩宽** outbox operation 白名单加入 `meeting_invite_dm`；`app/domain/meeting_scheduling.py` + `app/integrations/conference.py`；12 项测试
  - **幂等靠唯一约束而不是靠调用方记得**：`uq_meetings_tenant_recurrence_occurrence` 保证「一条节奏策略 + 一个发生日 = 恰好一场会」。这条很关键，因为生成器是定时跑的——重试或重复触发绝不能产出两场周一评审。同一发生日的 provider idempotency_key 也相同，重跑不会开第二个会议室
  - **建会顺序刻意是"先建会、后订会议室、允许失败"**：provider 挂了会议照样存在（只是没有链接），失败原因随结果返回。为一次会议 API 抖动丢掉整个议程，是比"没有入会链接"糟得多的结果——这就是验收里"API 失败降级为手工建会"的落地形状
  - **未配置的 provider 明确报错而不是编一个假链接**：`UnconfiguredConferenceProvider` 直接抛"credentials are not configured"。指向不存在地址的入会链接，比明显缺失的链接更糟
  - **踩到并记录一个环境陷阱**：`.env` 的 `DATABASE_URL` 指向**开发库 `pdos`** 而非 `pdos_test`。`. ../.env && alembic upgrade head` 迁移的是开发库，测试库由 pytest fixture 自己迁移。我用 psql 查 `pdos_test` 去验证刚跑的迁移，看到旧状态一度误判"CHECK 扩宽没生效"。另外 `alembic upgrade 2>&1 | tail -3` 会把失败信息连同非零退出码一起吞掉——已改为看 `$?` 或重定向到文件
  - **仍需人工**：真实钉钉视频会议 / 腾讯会议企业版 API 的**租户凭证**需要单独授权并服务端托管。凭证到位前 `UnconfiguredConferenceProvider` 是默认行为；`InMemoryConferenceProvider` 仅供测试与本地开发。另：会前通知走 outbox 且受 S5-1 约束（`PDOS_DINGTALK_DELIVERY_ENABLED=false` 时入库为 `manual` 不外发）
- [ ] V2-3：会议模板、议程、参会人与复查 API/UI
  - 验收：周会/物料会/专项会/TR/DCP/试制复盘/**项目复盘**模板；议程与复查项管理
  - 验证：API、BFF、桌面/移动浏览器
  - 依赖：V2-1、V0-6
- [ ] V2-4：会前例外装配
  - 验收：自动聚合逾期 Action、关键 Issue、物料短缺、Forecast 变化、Gate 缺项；每项可跳源
  - 验证：确定性聚合测试、截断/分页、无数据与失败态
  - 依赖：V2-3、V1-A7
- [ ] V2-5：Knowledge Lite `meeting_minutes` capability 与 golden cases
  - 验收：从转写片段提案 Minutes 与 Decision/Action/Issue/Risk/Change 候选；每字段有引用或明确无据
  - 验证：中文制造词表、真实钉钉/腾讯会议转写样本、说话人不确定、注入、跨项目、预算测试（I12）
  - 依赖：V2-1、V1-C2
- [ ] V2-6：会议提案确认与会后闭环（D19，按 D32 简化）
  - 验收：Minutes 与低风险候选（Action/关联/草稿 Issue）批量单次确认；仅涉硬闸对象候选逐项确认；下次会议自动复查未关闭项
  - 验证：批量确认/撤销、重放幂等、Event/Audit、真实会议演练
  - 依赖：V2-4、V2-5
- [x] V2-7：Evidence Snapshot / Research Source 底座（C8 提前）
  - 验收：来源许可/用途/频率/保留、抓取时间、source version、digest、新鲜度、冲突可记录；快照不可静默覆盖
  - 验证：迁移、租户/RBAC、重复内容、版本变化、过期
  - 依赖：V1
  - **2026-08-28 交付**：迁移 `0054_evidence_snapshot_base` 新建 namespace `cehub_evidence` 与 `research_sources` / `evidence_snapshots` 两表；域服务 `app/domain/evidence.py`、API `app/api/evidence.py`；新增 RBAC 动作 3 个（`evidence.view` / `evidence.capture` / `research_source.manage`）与事件 `RESEARCH_SOURCE_CHANGED`、`EVIDENCE_SNAPSHOT_CAPTURED`（均判定无 Agent 路由，V2-8 agent-reach 再接）；13 项测试
  - **不可覆盖靠数据库触发器而非应用层自觉**：`evidence_snapshots_immutable` 触发器拒绝任何对正文列（digest / content_ref / captured_at / taint / trust_tier / source_version 等）的 UPDATE，只放行 `superseded_by_id` / `conflicts_with_id` / `conflict_note` 三个链接列。理由：引用指向的东西如果能被就地改写，结论就会保留引用而证据已变——这正是"快照不可静默覆盖"要防的。已有测试直接用裸 SQL 撞触发器验证（`test_the_database_itself_refuses_to_rewrite_a_captured_snapshot`）
  - **D25「标注不拦截」落地为出生标签**：web/api 来源抓回的内容一律出生为 `untrusted_external`，且**不允许在抓取时自称 verified**（会 400）——提升为 verified 必须是独立的人工动作并留审计。file/internal_system 与无来源的人工上传出生为 `internal`
  - **内容寻址 + 版本区分**：同一 (来源, digest, source_version) 重复抓取返回原快照（`reused_existing=true`），避免同一份观测被计成多份佐证；但**同样字节 + 不同 source_version 是新的一次观测**（是复核而非重复），单独建行
  - **冲突只记录不裁决**：两份快照互相矛盾时记录 `conflicts_with_id` + 必填 `conflict_note`（DB CHECK 保证有 id 必有说明）。两个来源打架本身就是发现，静默选一个会把它藏掉
  - **引用 preflight 单点收口**：`domain/quality_evidence.py` 的 `kind` 从 `{document, event}` 扩到 `{document, event, evidence_snapshot, test_run, decision}`，未列出的 kind 一律 fail-close。快照按租户校验而非项目——共享证据库的意义就是一次抓取服务所有项目
  - **补记 V2-1 的一处遗漏**：`test_agent_database_security.py` 的 `VNEXT_BUSINESS_TABLES`（pdos_agent 零直接授权清单）是手工维护的，V2-1 交付时漏加 5 张会议表；本次一并补入会议表与两张证据表，已验证 `pdos_agent` 对它们零 grant
- [x] V2-8：agent-reach v1（D25 默认放行）
  - 验收：web_search/web_fetch（只读 GET）/source_snapshot 入 Tool Registry；默认放行 + blocklist（内网/登录凭证页/可执行下载），无首次访问审批；抓回自动落快照、结论引快照 ID；外部内容标注不可信（标注不拦截），硬闸动作时引用 preflight 校验；全体席位可用
  - 验证：注入样本标注、恶意页面、超大内容、限流退避、无 POST/凭证负例（I8）
  - 依赖：V2-7、V1-C2
  - **2026-08-28 交付**：`app/ai/reach.py`（策略 + 抓取 + 搜索）；`web_fetch` / `web_search` / `source_snapshot` 三个工具进入 `TOOL_DEFINITIONS` 公共集（D25 全体席位可用，不做按 agent 分支）；56 项测试（44 策略 + 11 抓取 + 工具契约），**全程零网络访问**——resolver 与 transport 均可注入
  - **默认放行的安全性不来自"挑网站"，而来自四条不随目标变化的硬限制**：① 只读 GET，不带 cookie/凭证/认证头，工具在对端无法产生副作用；② 任何主机名都要解析，且**每一个解析出的 IP 都必须全球可路由**——挡住 loopback / RFC1918 / link-local / 云元数据 169.254.169.254，且**每一跳重定向都重新校验**；③ 登录与 OAuth 路径直接拒（抓登录页永远不是研究），可执行载荷按扩展名**和** Content-Type 双重拒；④ 抓回必落快照，结论只能引 snapshot_id
  - **SSRF 的两个真实绕过路径都有针对性测试**：`test_a_redirect_into_the_metadata_endpoint_is_refused_at_the_hop`（开放重定向指向云元数据端点——只查首跳的实现会中招）与 `test_a_rebind_to_loopback_between_hops_is_caught`（跳与跳之间 DNS 重绑定）。另有 `test_one_public_address_among_several_does_not_excuse_an_internal_one`：split-horizon 解析返回一公一私时必须按私有地址拒绝，不能因为"有个公网地址"就放行
  - **注入样本按 D25「标注不拦截」处理**：页面里的 `IGNORE ALL PREVIOUS INSTRUCTIONS...` 原文照落快照并带 `untrusted_external` 标签，**不拒抓**——拒掉反而会把"某来源正在尝试注入"这个事实藏起来
  - **`web_search` 目前无搜索供应商，行为是明确报错而非返回空列表**。理由：Agent 分不清"没搜到"和"搜索没开"时，会把后者当成不存在的证据来汇报。`is_available` 属性可查，错误文案里明写 "this is not an empty result set"。**这是一处需要人给搜索 API 凭证才能补齐的缺口**，已在下方"仍需人工"记录
  - 已配置搜索供应商时，命中结果在交给模型前先过一遍同一套策略，被拒的链接直接丢弃——不给模型永远打不开的链接
- [x] V2-9：辩论 runtime v1（D26）
  - 验收：LangGraph 辩论图（主持/席位/收敛/预算熔断节点）；席位立场投影服务端冻结；Agent 可自行发起、场景不设白名单；Decision Brief 一场人工比对合格即转正进确认区/硬闸区流程；transcript 全程落库可回放
  - 验证：席位越权负例、辩论投毒样本、复读检测、预算熔断、真实模型 transcript 质量样本（I8/I12）
  - 体验（UX7）：异步执行不阻塞前台；结束推送 Brief 摘要；transcript 席位/轮次/引用可视化回放；用户可随时插入人工意见成为辩论输入
  - 依赖：V1-C2、V2-8
  - **2026-08-28 交付**：迁移 `0055_debate_runtime` 建 4 表（`debate_sessions` / `debate_seats` / `debate_turns` / `debate_briefs`，均在 `cehub_ai`）；域服务 `app/domain/debates.py`、LangGraph 运行时 `app/ai/debate_runtime.py`（主持 → 席位 → 收敛 → 熔断四节点）；事件 `DEBATE_STATE_CHANGED`（无 Agent 路由）；15 项测试，席位发言全部走注入的 stub，零模型调用
  - **核心判断：辩论比单次模型调用更有价值，前提是各席位从"不同证据"出发**。这就是立场投影的作用——开场前服务端把每个席位锚定到一份具体的对象清单，席位**不能引用锚定之外的对象**（`DebateSeatAuthorityError`）。没有这条，"多智能体"会退化成同一个模型产出六份自己的改写
  - **投影在 convene 时写入一次，此后永不更新**，模型输出无法扩大自己的可达范围；有测试跑完整场辩论后比对投影未变
  - **熔断与收敛放在图里而非提示词里**：预算在**每个席位发言前**检查（不是每轮一次，避免单次超长发言超支）；预算耗尽停为 `budget_stopped` 而非 `converged`——**被成本截断的辩论和真正收敛的辩论不是同一个东西**，混为一谈会让残缺论证看起来完整
  - **复读检测按席位而非全局**：同一席位换标点重说算复读（`normalize_for_repetition` 忽略大小写与标点、折叠空白但不删除空白），连续两轮全员只复读即判 `no_new_arguments` 收敛；**两个席位独立得出相同结论是"一致"不是"复读"**，必须保留——有专门测试钉住这条区分
  - **投毒样本的处理是"不采纳但留痕"**：越权引用的发言不入 transcript 作为席位发言，但主持人会记一条"席位越权"——一个席位试图在锚定之外argue，本身就是值得在回放里看到的发现，静默丢弃反而把它藏了
  - **Brief 默认是 draft，转正必须有人**：DB CHECK 强制非 draft/rejected 状态必须有 validator 与时间戳；驳回必须写理由。D26 的"一场人工比对合格即转正"是带署名的状态迁移，不是自动交接
  - **审计写入器挡了我一次**：debate 快照里的 `spent_tokens` 命中了 `SENSITIVE_KEY_PARTS` 的 "token" 子串检查。这是守卫在正常工作——子串检查分不清"令牌"和"计数"，所以已按既有做法把 `budget_tokens` / `spent_tokens` 显式加入 `NON_SENSITIVE_METRIC_KEYS` 白名单（与既有的 `input_tokens` / `output_tokens` 同理），而不是绕过检查
  - **第三次被手工维护的清单测试挡住**（前两次是 `VNEXT_BUSINESS_TABLES` 漏加会议表、RBAC 动作清单）：`test_agent_runtime_schema.py` 对 `cehub_ai` 断言精确表集合，新增 4 张 debate 表未同步。这类清单**漏加不会失败，只会静默失去保护**，所以必须主动跑。已一次性把所有清单测试跑通并固化为加表时的必跑集（约 2 分钟，对比全链 13 分钟）：`pytest tests/test_*_schema.py tests/test_rbac_policy.py tests/test_project_access_api.py tests/test_agent_runtime_contract.py tests/test_agent_database_security.py`
  - **仍需人工**：D26 要求的"一场真实辩论经人工比对合格转正（分歧项完整率达标）"属 Checkpoint V2，需要真实模型跑一场并由人比对
- [~] V2-10：全局搜索 + 移动现场录入 + 图纸预览（G11/G14/G21）**（部分交付，见下）**
  - 验收：跨对象+附件全文+知识统一检索；手机端拍照/语音→AI 结构化草稿 Issue/Test 记录，样机按编号自动匹配（D37 无扫码）；PDF/STEP/Gerber 在线预览与版本对比（不做 CAD Vault）
  - 验证：检索相关性、移动端真实设备、大文件预览性能
  - 依赖：V1-B3、V1-C1
  - **2026-08-28 已交付（G11 全局搜索 + G14 服务端样机匹配）**：`app/domain/search.py` + `app/api/search.py` + BFF `web/src/app/api/search/[[...searchPath]]/route.ts`；18 项后端测试 + 3 项 BFF 路由测试
  - **检索为什么用子串而不是 tsvector**：语料以中文为主，Postgres 内置分析器**不做中文分词**，`to_tsvector` 会把整句当一个词元、静默返回不可用的结果。确定性 ILIKE 在英文词干化上更差，但在真正要找的「密封面粗糙度」上好得多。这是将来接入分词扩展时的替换点，已写在模块文档里
  - **可达范围在查询里过滤，不在结果里过滤**：看不到的命中根本不会被取出，因此**结果数量也无法泄露别人项目的存在**。owner/admin 覆盖整租户；其他人覆盖自己参与的项目 + 持有有效委托的项目（V1-A11 只借成员身份不借角色）
  - **多词是 AND 不是 OR**；标题命中权重 3、正文 1；摘要取首个命中词周边窗口，让命中自己解释为什么命中；附件走 `document_fragments` 全文而非文件名——**答案在附件正文里，文件名只是标签**
  - **G14 的确定性部分**：`SampleMatcher` 按打印的样机编号在现场笔记里做大小写无关匹配（D37 明确不用扫码）。**一条笔记里出现两个编号时返回 `ambiguous=true` 而不是猜**——猜错缺陷属于哪台样机，正是让现场记录变得不可信的那类错误；`SN-1` 与 `SN-12` 并存时长编号优先
  - **本条目未完成的部分（需要人/资产，不是我可以自行决定跳过的）**：
    - **G14 移动端采集前端**：拍照 OCR / 语音转写 → 结构化草稿的**客户端**部分未做。服务端匹配与草稿写入路径已具备，但采集本身是移动前端能力，验收明确要求"移动端真实设备"验证，我无法在此环境完成
    - **G21 图纸预览**：PDF 可用浏览器原生能力，但 **STEP / Gerber 渲染需要专门的查看器库**，当前依赖集中没有，且验收要求"大文件预览性能"需要真实图纸样本。需要先定库选型（这是需要拍板的技术选择）与提供样本文件

### Checkpoint V2

- [ ] 真实试点会议完成"自动建会→议程→转写上传→AI 提案→批量确认→任务/问题/决策→下次复查"，无引用结论不能应用
- [ ] 一场真实辩论完成并经人工比对合格转正（分歧项完整率达标）
- [ ] reach 全部抓取有快照、红队零穿透；人工确认 Phase Exit

## Phase V3：项目时间、健康度与管理层看板

> **2026-08-28 停在此处的理由（非阻塞判断，是风险判断）**：V3-1 的**依赖**（"V0"）与 V1/V4-1 相同、已满足，但它的**验收**是"产品/PMO/工程 Owner 示例走查与兼容策略"。四类时间语义（Baseline/Forecast/Commitment/Actual）、依赖边类型与跨项目依赖边界都是**建模决策**，Owner 走查正是用来校验这些决策的。与 V2-2 的会议 provider 不同（可换实现、藏在接口后），数据合同一旦建错，代价是迁移 + 冻结测试 + 11 处 pin 的连锁返工。**在校验手段缺席时抢先冻结数据合同，是本项目最不该省的一步。** 因此 V3 起的建模项等 Owner 走查后再动；期间已把 V2 与 V4-1 中不依赖人工前置的部分做完。


- [ ] V3-1：四类时间与 schedule node/dependency 合同（D33 全量）
  - 验收：Baseline/Forecast/Commitment/Actual 语义；FS/SS/FF/SF + lag；多站点日历/时区（G8）；Task/Gate/Build/Test/认证节点全部为 schedule node（PM3）；跨项目依赖边界冻结
  - 验证：产品/PMO/工程 Owner 示例走查与兼容策略
  - 依赖：V0
- [ ] V3-2：Baseline 版本与 Forecast Snapshot
  - 验收：基线不可静默覆盖；Forecast 可派生；任何快照可重算/解释/审计
  - 验证：迁移、并发、版本、回放、有损 downgrade guard
  - 依赖：V3-1
- [ ] V3-3：确定性依赖传播与关键路径引擎
  - 验收：只传播到可达后继；float/日历/lag/cycle fail-close 正确；错误路径零 LLM
  - 验证：属性/边界测试、性能基线、固定案例手算对账
  - 依赖：V3-2
- [ ] V3-4：跨项目 Forecast 影响 API 与计划视图
  - 验收：基线/预测差、传播路径、受影响 Gate/Build/Test/客户节点可视；无隐式基线变化
  - 验证：API、UI、320/1440、复杂图分页、真实试点案例
  - 依赖：V3-3
- [ ] V3-5：Schedule Change Proposal 与人审重基线（D4）
  - 验收：多恢复场景可比较（辩论可介入）；批准生成新 Baseline version（硬闸）；Commitment 另行确认
  - 验证：权限、四眼、Event/Audit、重放、回滚依据
  - 依赖：V3-4
- [ ] V3-6：Project Agent 延期解释与方案建议
  - 验收：引用引擎结果不自行算日期；解释原因/影响/假设；无据 no_action
  - 验证：golden cases、受限工具、真值表零写
  - 依赖：V3-3、V1-C2
- [ ] V3-7：Project Health Engine 六维健康度（I6）
  - 验收：Schedule/Engineering/Quality/Cost/Supplier/Certification 从对象证据确定性聚合；项目 Brief 自动显示目标/关键变更/Top Risks/决策/下一步；Agent 只解释不打分
  - 验证：健康度手算对账、证据缺失降级态
  - 依赖：V3-3、V1-B6
- [ ] V3-8：Forecast 误差采集前移
  - 验收：Phase 3 上线即记录 Forecast vs Actual 误差序列，为 V6 校准积累历史
  - 验证：序列完整性、重算一致
  - 依赖：V3-2
- [ ] V3-9：管理层看板（D38 双层）
  - 验收（决策请求中心与例外层）：硬闸待批 + Decision Brief 待决队列（等待天数与升级）；健康度异常项目；关键里程碑/Gate 倒计时与 Conditional Pass 未闭项；Top 风险与跨项目延期传播；里程碑兑现率（北极星）趋势；每项一键跳源
  - 验收（全项目进度总览层）：所有项目一表——阶段/Gate 位置、证据聚合进度（非手填百分比）、Baseline vs Forecast 偏差天数、下一里程碑倒计时、当前阻塞清单（blocking Issue/关键短缺/待批硬闸/上游依赖延迟，确定性判定含阻塞时长）、PM、健康度色标；按偏差/阻塞/健康度排序，钻取项目控制塔
  - 体验：手机端一等公民；首屏 <1.5s（UX10）；Executive Agent 每日/每周 Brief（站内 + outbox 受 S5-1 约束）
  - 后续接入（各 Phase 交付时挂接）：V4 短缺/供应商暴露/Cost Gap；V5 机会管道/DCP 队列；V6 资源冲突/AI 治理看板
  - 验证：例外过滤正确性、进度聚合对账、管理层角色矩阵、320/1440、真实浏览器
  - 依赖：V3-7、V2-9

### Checkpoint V3

- [ ] "A 延 6 天、B 延 3 天、C 因 float 不变"固定案例通过；Forecast 自动变、Baseline/Commitment 不变
- [ ] 管理层看板双层可用：一位管理层用户手机端完成"看全局进度→查阻塞→批一项硬闸"走查
- [ ] 辩论"项目经理"席位接入真实 Baseline 投影；人工确认 Phase Exit

## Phase V4：物料齐套 + 工程与品质闭环深化

- [~] V4-1：现有 BOM item、Build/Sample/Test 的 BFF/UI 操作面补齐**（BFF 层完成，UI 面板待建）**
  - 验证：现有 NPI API 合同、BFF allowlist、桌面/移动浏览器
  - 依赖：V0
  - **2026-08-28 先做了量化盘点**：写脚本把后端 OpenAPI 的 178 条 `/api` 路由与 `web/src/app/api` 下的 BFF 路由目录做反向对账，结果 **65 条后端路由在前端完全不可达**。其中最大一块是**整个 NPI 执行面**（builds / samples / sample-configurations / sample-signoffs / test-plans / test-cases / test-runs / test-imports / test-reports / certifications）——V1 建的数字链有一整段在应用里根本调不到，且**没有任何测试会因此失败**
  - **已交付**：`web/src/lib/npi-bff.ts` + `npi/[[...npiPath]]/route.ts`，按 **method + 路径形状** 逐条白名单（21 条），非 UUID 占位、方法不符、未列路径一律 404 不转发；4 项路由测试。未覆盖路由从 65 降到 45
  - **同时把这个反向检查固化成常驻守卫** `server/tests/test_bff_reachability.py`：每条后端路由必须**要么可达、要么在豁免清单里具名**。豁免分四类——`SESSION_HANDLED`（token 不能进客户端 JS，走 session BFF）、`SERVER_SIDE_ONLY`、`OPERATIONAL_ONLY`（worker 端点，设计上无 UI）、`UNREACHABLE_BACKLOG`（45 条真实欠账）。另有三条自检：**backlog 里已可达的条目会失败**（防止修好了却留着假欠账）、**豁免了不存在的路由会失败**（防止改名后留下静默豁免）、**两侧扫描为空会失败**（防止断言变成空真）
  - **为什么需要两个方向的守卫**：`bff-coverage.test.ts` 管的是"前端调了不存在的路由"（我的工作页就是这么坏的）；这条管的是"后端有能力但前端够不到"。后者更隐蔽——**前者会在页面上报错，后者只是功能悄悄不存在**
  - **2026-08-28 续：UI 面板已建**。`project-npi-panel.tsx` + `project-npi-api.ts` + `project-npi-types.ts`，挂在「工程·变更」页签（不新增第 10 个页签，D9/D31 的 9 页签 IA 不动）。功能：试制批次列表与状态推进（开始/完成试制）、批次内样机展开与登记、测试计划与用例列表、用例判定通过/失败；只读角色只见数据不见写操作。6 项组件测试
  - **写请求体逐字段对齐服务端**：后端 pydantic 模型全部 `extra="forbid"`，多一个字段就是 422。我第一版凭直觉写的三个请求体全错——`createBuild` 多写了 `workflow_id`、`updateBuild` 用了 `planned_quantity/notes` 而实际是 `status/completed_quantity`、`recordTestResult` 用了 `note` 而实际是 `result_notes`。已逐条对着服务端模型改正，并把 `BUILD_PHASE_LABELS` 里的 `mp` 删掉（build_batches.phase 的 CHECK 只允许 evt/dvt/pvt）。测试直接断言发出的 JSON 体，防止再漂
  - **顺手修了两个前端真实缺陷**：① 初始加载在 effect 里同步 setState（`react-hooks/set-state-in-effect`），改为 effect 内异步取数；② 取数无取消标志——切换项目时前一个项目的慢响应可能落到后一个项目的面板上。虽有 `key={project.id}` 重挂缓解，仍加了显式 cancelled 标志
  - **live 浏览器验证未能完成（如实记录，已查明根因）**：web dev server 可起（:3000），但 **API 在 preview 沙箱下无法运行**。三次尝试逐步定位到根因：① 沙箱禁止读 `.env`（`Operation not permitted`）；② 改用不含密钥的本地变量后 `uv run` 进程存活却不监听、无日志；③ 绕开 uv 直接用 `.venv/bin/uvicorn`，报 `PermissionError: .venv/pyvenv.cfg`。**结论：preview 沙箱禁止读取仓库内的点目录/点文件（`.env`、`.venv`），因此 Python 后端无法在该运行时下启动**——这是环境限制，不是配置错误。已把临时加进 `~/Desktop/.claude/launch.json` 的 `pdos-api` 条目删除，不留坏配置。因此**本会话新增的 6 个前端面板都没有真实浏览器端到端验证**。已有的覆盖是：组件测试断言实际发出的 URL 与 JSON 体、BFF 路由测试断言代理到正确后端路径并带鉴权、`test_bff_reachability.py` 断言路由存在——三者合起来覆盖了两端契约，但**未证明活的端到端跳转**。这是已知的验证缺口，**需要在普通终端里跑 `scripts/dev.sh` 后由人走查一遍**（考虑到本会话最大的教训正是"组件测试 mock fetch 所以看不见 BFF 缺失"，这一步不应省略）
  - **其余欠账**已在 `UNREACHABLE_BACKLOG` 中按域分组列明（证据库、知识推送、ECR/ECN/交接、客户变更、交付物检查、Gate 明细）
  - **2026-08-28 续：决策域已打通（欠账 45→43）**。「例会·决策」页签此前是"数据面将在 V2 接入"的占位符，而后端 `/api/projects/{id}/decisions` **从 V1 起就在服务** ——记录存在、没人读得到。已补 `decisions-bff.ts` + 路由 + `project-decision-panel.tsx`：决策日志（类型/结论/理由/跟进态）、手工记录决策、记录跟进说明；只读角色只见日志不见写操作。5 项组件测试 + 2 项 BFF 路由测试
  - 手工可记的决策类型只有 6 种（technical_choice / supplier_choice / process_decision / rebaseline / definition_release / ccr_response）——Gate 与变更决策由各自流程写入，**不给手工入口，避免手敲副本与真实记录分叉**
  - 有一条测试专门钉住"**读取失败不得渲染成『尚无决策记录』**"：403 必须显示拒绝原因，而不是一个看起来正常的空列表
  - **2026-08-28 续：工程变更域已打通（欠账 43→29）**。页签叫「工程·变更」但里面**一条变更都没有**——ECR→ECN→ERP 交接链自 V1 起在后端，前端零入口。已补 `changes-bff.ts` + 路由 + `project-change-panel.tsx`：ECR 列表与状态、提出变更、开始/提交影响分析、批准/驳回、ECN 子列表。6 项组件测试 + 3 项 BFF 路由测试
  - **BFF 按 method+形状逐条白名单（14 条）而非整体透传**：交接的四个动词（queue / ready / export / replay / reconcile）在服务端各自有不同的确认契约（如 export 要 `confirmation: "EXPORT_CONFIRMED"`、queue 要 16 位以上 idempotency_key），整体透传会让一个拼写错误打到另一个动作上。有测试专门验证 `exprt` 打不通、`delivery`（读）不能当写用、ECR 的写动词不能当读用
  - **审批与编辑是两个权限**：面板的批准/驳回按钮由 `CHANGE_APPROVE` 的角色集合（owner/admin/project_manager，已对着服务端 RBAC 实测确认）控制，与 `canEdit` 分开——做影响分析的人不能自己批准自己的变更。面板只呈现当前状态允许的那一个转移，不给出服务端会拒绝的按钮
  - **2026-08-28 续：客户变更（CCR）域已打通（欠账 29→23）**。`customer-changes-bff.ts` + 路由 + `project-customer-change-panel.tsx`：CCR 列表与状态、分析影响、起草报价答复、四眼批准、客户接受/拒绝。5 项组件测试 + 3 项 BFF 路由测试
  - **CCR 与 ECR 在界面上刻意分成两段**：客户提出变更与工程决定变更是不同事件、不同责任人。CCR 可以*引发*一个 ECR，但不是同一个对象——合成一张表会让"谁承诺了什么"变得说不清
  - **四眼原则在界面上是"不给按钮 + 明说原因"**：报价起草人自己看不到"批准对外答复"，看到的是"需另一人批准（四眼原则）"。只藏按钮不解释，会让人以为是权限坏了
  - **写错一次并靠实测纠正**：我凭印象把 CCR 的分析后状态写成 `analyzed`，实际 DB CHECK 是 `impact_analyzed`。因为状态值同时控制标签和按钮显隐，写错的表现是"分析完之后没有任何按钮"——一个不会报错、只会让人卡住的缺陷。已改正
  - **影响面展示的是确定性计数而非一句总结**：需求/规格/测试用例条数与需复测数，都是 V1-B8 里沿追溯链数出来的，可随时回数据库对账
  - **2026-08-28 续：交付物检查已打通（欠账 23→20）**。`deliverable-checks-bff.ts` + 路由 + `project-deliverable-check-panel.tsx`，挂在「Gate·交付物」页签补齐名字的后半截：检查项列表、按模板生成、标记完成/不适用、Gate 必需项计数。5 项组件测试 + 3 项 BFF 路由测试
  - **又一次靠核对服务端纠正了两条界面规则**（不是靠猜）：① 我原以为"只有 Gate 必需项完成时才要证据"，实际服务端对**任何**项完成都要求 `evidence_reference`；② 我原本给 Gate 必需项也放了"标记不适用"按钮，实际服务端直接拒绝（`hard gate cannot be bypassed`），且非 Gate 项标记不适用必须带 `note`。现在面板拒绝的东西与服务端拒绝的东西完全一致——**用户不应该把规则当成提交时的报错来学**
  - 同一个输入框在"完成"时承载证据引用、在"不适用"时承载理由，因为服务端在这两种情况下各要一个且只要一个；测试分别断言两种提交的 JSON 体
  - **顺带修掉一个真实的测试隔离缺陷（不是我这次改坏的，是一直存在的）**：`test_ai_api.py` 与 `test_model_governance_api.py` 依赖**开发者 shell 的环境变量**。模型目录直接读进程环境，而这两个文件里有断言"模型不可用"和"合格模型清单恰好是某几项"的用例——它们从不清理供应商变量。后果：在 `.env` 里放入真实模型凭证后（本会话按用户要求做过），`. .env && make check` 会失败，而不带 .env 跑就通过。**更危险的是反向**：一个断言"不可用"的用例在有凭证时会变成另一个用例，仍然"通过"，但已经不在验证原本的东西
  - **2026-08-28 续：Gate 决策已可记录（欠账 20→17）**。此前 Gate 面板能开签核轮次、能收签核，**却没有任何地方写入 Gate 决策本身**——评审做完了留不下结论，而记录结论正是整个评审存在的目的。已补三条 Gate 明细路由（decisions / requirements / grandfather-exemptions）与 `project-gate-decision-form.tsx`。4 项组件测试
  - **有条件通过必须带条件、普通通过必须不带**（服务端两侧都拒绝）。表单据此：选"有条件通过"时展开条件表单并要求四要素齐全（做什么/谁负责/何时/以什么证据关闭）才可提交；选普通通过时**根本不发 `conditions` 字段**而不是发空数组——发空数组会被服务端按"带了条件"拒绝。有测试断言 `"conditions" in body === false`
  - **决策表单只在确定性缺项清零后出现**，Gate 未就绪时不给入口——不能越过未关闭的例外去批 Gate
  - **2026-08-28 续：知识推送 + spec-coverage + 证据库全部打通，`UNREACHABLE_BACKLOG` 清零**。至此**每一条后端路由要么可达、要么在具名豁免清单里**（session 托管 / 服务端渲染 / 运维端点三类）
  - 知识推送 BFF 对 `context_kind`（`^[a-z_]{1,32}$`）与 `context_entity_id`（UUID）在网关层重新校验，并**只转发服务端声明的这两个查询参数**——多余参数直接丢弃，不做原样透传；有测试断言 `limit=999&tenant_id=...` 不会被带到后端
  - 证据库落在 `/knowledge` 页面（与知识检索并列，两者回答的是同一个问题："我们到底知道什么、凭什么知道"）。展示来源的许可/用途/保留/频率，以及快照的 taint 标签、digest、版本、陈旧与冲突。**BFF 里刻意没有任何"编辑快照"的路径**——快照不可覆盖，纠正的方式是新抓一份并 supersede；有测试断言 `POST /snapshots/{id}`、`/edit`、`/delete` 全部 404，让路由表本身反映这条不变量
  - 冲突按"记录而非裁决"展示：两份快照矛盾时显示双方与冲突说明，不替用户选一边
  - 修法是新增 `tests/provider_environment.py`，**从 `PROVIDER_SPECS` 派生**要清理的变量名（含每供应商前缀的 `_API_KEY` / `_BASE_URL` / `_MODEL`，以及 `ANTHROPIC_API_KEY`），而不是手写清单——手写的那版我第一次就漏了 `PDOS_LLM_MINIMAX_MODEL`，它会静默覆盖 fixture 自己设的模型名。现已双向验证：**带真实 .env 与完全空环境（`env -i`）下都是 11 项通过**
- [ ] V4-2：Project Material/ERP snapshot SoR 合同
  - 验收：BOM、项目需求、ERP 事实、供给引用、数据时点、替代料、质量冻结边界明确
  - 验证：ERP/采购/工程/质量 Owner 联合走查
  - 依赖：V3-1
- [ ] V4-3：按 Build/阶段生成物料需求
  - 验收：Build 冻结 Prototype BOM version/snapshot/digest（D15）；需求关联 BOM item、数量、need-by schedule node、批次；ECN 只产生 delta/new revision
  - 验证：迁移、BOM/Build 兼容、重复生成幂等
  - 依赖：V4-1、V4-2
- [ ] V4-4：供给引用、as-of snapshot 与齐套计算
  - 验收：首版 ingress（只读 API/文件导入）拍板；captured_at/source_version/freshness SLA；总齐套/关键齐套/短缺/长周期/stale 确定性计算；不冒充实时库存
  - 验证：ERP fixture 对账、过期/缺失/部分到货/冻结测试
  - 依赖：V4-3
- [ ] V4-5：物料工作区与影响追踪
  - 验收：短缺追到 Task/Build/Test/Gate/Project；同一物料/供应商跨项目暴露可见
  - 验证：API/UI/权限/性能/真实浏览器
  - 依赖：V4-4、V3-4
- [ ] V4-6：物料短缺→Issue/Forecast/Meeting/Gate 闭环
  - 验收：短缺先成确定性 Material Exception（自由区草稿）；转 Issue 走确认区；进入会议议程；按 versioned policy 阻断 Build/Gate（硬闸）
  - 验证：端到端事件链、提醒、重放、ERP 零写
  - 依赖：V4-5、V2、V3
- [ ] V4-7：Change Impact Graph
  - 验收：Part→BOM→Spec→Test→Certification→Cost→Supplier→Sample→Open Issue 影响图；自动生成 Retest/Re-review/Re-certification 与通知清单；执行层 Effectivity 归 ERP
  - 验证：影响图对账、清单完整性、大图性能
  - 依赖：V4-3、V1-B3
- [ ] V4-8：Living FMEA
  - 验收：Failure Mode 关联 Requirement/Part/Design Function/Control/Test；新 Issue 未被覆盖时生成 Update Proposal（草稿）；不自动改 S/O/D
  - 验证：覆盖检查 golden、提案质量、品质 Owner 走查
  - 依赖：V1-A4、V1-B3
- [ ] V4-9：Supplier Engineering Profile + Compliance Matrix
  - 验收：供应商工程画像（样品交期/响应/问题率/历史 Failure，内部维护 D34）；Market→Regulation→Evidence→Status 合规矩阵；变更自动检查合规影响；认证送样批次跟踪
  - 验证：画像聚合对账、合规联动用例
  - 依赖：V4-2、V1-B6
- [ ] V4-10：Supplier Agent 增强 + EOL/PCN 监控（G29）
  - 验收：催交/替代/拆借建议（草稿）；agent-reach 订阅厂商通告，命中在用器件生成告警草稿
  - 验证：golden、跨租户、敏感信息零泄漏
  - 依赖：V4-4、V2-8
- [ ] V4-11：辩论席位投影深化（D26）
  - 验收：DQE 席位接入 FMEA/CAPA 投影；结构/硬件席位接入 Impact Graph 与结构化 Test 数据；ECR 场景 Decision Brief 分歧项完整率达 V0 阈值
  - 验证：席位投影正反例、真实 ECR 演练
  - 依赖：V2-9、V4-7、V4-8
- [ ] V4-12：打样批次与模具/治具台账（G12/G26/PM2）
  - 验收：EVT/DVT/PVT 打样轮次台账（批次、交期承诺 vs 实际、良率如报告含则抽取）从测试报告与 Build 记录推导；样机全息视图按编号进入；模具 T0/T1/T2 试模轮次、模具变更与供应商交期并入台账；测试治具/装配工装作为长周期工装项进齐套视图；无条码/扫码/位置管理（D37）
  - 验证：台账推导对账、工装齐套联动
  - 依赖：V1-B2、V4-4
- ~~V4-13：测试设备直采~~（D36 延后，非 vNext 范围；入口为 V1-B10 Excel AI 导入）
- [ ] V4-14：成本目标分解、多币种与项目 NRE 预算（G10/G27）
  - 验收：Target Cost 逐级分解到子系统/模块；多币种报价与汇率时点口径；Cost Gap 超标自动触发 Issue/辩论并回告产品定义假设（轴 8/9 衔接）；项目 NRE 预算 vs 实际轻量跟踪（开模/认证/打样/测试费），核算归 ERP
  - 验证：滚算对账、汇率时点、超标触发用例
  - 依赖：V4-3、V1-B4
- ~~V4-15：供应商外部账号~~（D34 移除：仅内部使用）
- [ ] V4-16：变更冻结期政策（PM4）
  - 验收：PVT/MP 前 quiet period 可配置；冻结期内 ECR 自动升级审批链；冻结例外留痕
  - 验证：政策版本化、升级链用例
  - 依赖：V4-7、V0-6

### Checkpoint V4

- [ ] 一批真实 Build 完成 BOM→需求→ERP snapshot→齐套→短缺→排期/问题→关闭；ERP 抽查一致、零反向写
- [ ] 一次真实 ECR 走完"辩论→Decision Brief→人审 ECN→Impact Graph→重验清单→执行验证"
- [ ] 模具/治具长周期项出现在齐套与关键路径中；人工确认 Phase Exit

## Phase V5：AI 产品经理工作台与市场到 IPD（D33 全量建设）

- [ ] V5-1：产品管理域与 SoR 合同
  - 验收：研究/竞品/细分/机会树/实验/策略/定义/矩阵对象、Owner、状态、发布权限冻结；明确排除 CRM（D17）；与研究来源/ERP/PLM 边界明确
  - 验证：产品、市场研究、工程、质量、财务、IPMT Owner 联合走查
  - 依赖：V0
- [ ] V5-2：采集调度器与产品管理连接器扩展
  - 验收：订阅式采集、限流退避、失败隔离、去重、版本 diff、来源冲突（底座在 V2-7/V2-8）
  - 验证：fake source、内容变化、超大内容、网络失败
  - 依赖：V2-8、V5-1
- [ ] V5-3：竞品与竞品产品情报纵向切片
  - 验收：市场边界→Competitor/Product→规格/功能/细分/价格带/区域/认证/生命周期；参数矩阵、定位、优劣势、威胁、差异化结论可跳快照；版本变化定期提醒
  - 验证：边界错误、冲突来源、未知值、版本 diff、过期证据、桌面/移动
  - 依赖：V5-2
- [ ] V5-4：Market Space、市场细分与 JTBD
  - 验收：品类边界/地域/周期/替代方案；Segment 绑定客户问题/JTBD/购买标准/未满足度；TAM/SAM/SOM 保存公式/参数/范围并由指标引擎复算（D24）
  - 验证：指标复算、事实/估计/假设区分、反证与数据缺口状态
  - 依赖：V5-2
- [ ] V5-5：Opportunity Solution Tree 与验证实验闭环
  - 验收：单一可衡量 Desired Outcome；Opportunity 绑证据与版本化 `Importance × (1 - Satisfaction)`；收敛前 ≥3 Solution Candidate；VUVF 假设/实验阈值/Owner/结果；失败实验保留为知识
  - 验证：树关系/循环、评分复算、少于 3 方案告警、实验证伪回写
  - 依赖：V5-3、V5-4
- [ ] V5-6：Product Strategy Canvas、Concept 与 Definition
  - 验收：Canvas 九区；Definition 含目标客户/场景/差异化/目标规格/成本价格带/法规/服务/上市窗口/成功指标；每项标 evidence/assumption/decision；版本化发布（硬闸：产品经理审核发布）
  - 验证：九区完整性、证据反链、草稿/评审/发布/替代状态、不可变发布
  - 依赖：V5-5
- [ ] V5-7：产品家族、矩阵与路线图
  - 验收：Line→Family→Platform→Series→Model/Variant；市场/场景/价格带/区域/渠道/规格/生命周期矩阵；空白/重叠/蚕食/平台复用识别；场景比较由指标引擎算、Agent 解释
  - 验证：层级循环、重复定位、矩阵冲突、不复制 ERP/PLM 主数据（D22）
  - 依赖：V5-6
- [ ] V5-8：typed scope v3 实现（合同已在 V0-3 冻结）
  - 验收：run/context/Finding 支持服务端绑定 tenant/market_space/product_line/opportunity/product_definition/portfolio/project；模型自报 scope 无效；禁止虚拟 Project（D13）
  - 验证：迁移、受限投影、跨 scope/跨租户、上下文泄漏
  - 依赖：V5-1、V1-C1
- [ ] V5-9：Product Management Intelligence Agent（D21/I5）
  - 验收：8 capability 分两批上线（先 research/competitor/market，后 strategy/definition/matrix），每 capability 独立质量线、不达标单独停用；上线即承担辩论"产品经理"席位（锚定已发布 Definition/定价带/Canvas）
  - 验证：真实模型 golden、no-action、引用、来源冲突、注入、指标层一致性、成本延迟
  - 依赖：V5-3 至 V5-8、V1-C2
- [ ] V5-10：Definition→Requirement→DCP/TR→IPD 兼容链（D8/D14）
  - 验收：批准 Definition 只生成候选 Requirement；Opportunity↔Requirement、Case↔Requirement 多对多保留 primary 兼容；DCP 商业决策与 TR 技术评审分离，结果为 Gate readiness 输入；批准后才实例化 IPD v2 项目模板；Agent 零自动立项/批准
  - 验证：旧链无损、幂等、事务回滚、Gate 兼容
  - 依赖：V5-6、V5-7、V2、V3、V4
- [ ] V5-11：实验、质量、服务与生命周期反馈回链
  - 验收：用户研究/实验/试点/投诉/质量/服务/退市结果回到原 Opportunity/Strategy/Definition/矩阵位置与关键假设；verified Memory 才进 Agent context
  - 验证：端到端引用、权限、新鲜度、检索过滤
  - 依赖：V5-10、现有 Quality/Memory

### Checkpoint V5

- [ ] 一个真实品类完成"采集→竞品/市场分析→细分/JTBD→机会树→实验→策略→定义→矩阵→候选需求→DCP/IPD→结果反馈"可跳源闭环
- [ ] 量化指标可复算；陈旧/冲突/未知不伪装成事实；Agent 无自动发布/立项/批准；人工确认 Phase Exit

## Phase V6：共享资源组合排程与 vNext Exit

- [ ] V6-1：Resource Pool/Calendar/Capacity/Reservation 合同
  - 验收：人员、技能组、设备、**测试台架**、模具、治具工装、实验室、试制线的身份/容量/日历/租户边界冻结；现有 project-scoped Resource 无损兼容
  - 验证：兼容迁移、资源 Owner 走查、跨租户负例
  - 依赖：V3、V4
- [ ] V6-2：资源预约纵向切片
  - 验收：预约含项目、schedule node、容量、时段、Owner、状态；重叠容量确定性校验；实验室/台架排队可视（轴 6 断点 b）
  - 验证：API/UI、并发预约、日历边界、真实资源样本
  - 依赖：V6-1
- [ ] V6-3：资源受限排程与版本化优先级政策
  - 验收：只用版本化政策；相同输入输出稳定；无政策 fail-close；错误路径零 LLM
  - 验证：固定手算案例、并发/性能
  - 依赖：V6-2、V3-3
- [ ] V6-4：组合情景比较与人工应用
  - 验收：加班/替代设备/外协/降级/顺延情景；情景不改真值；应用走确认区/硬闸区
  - 验证：场景摘要哈希、权限、过期真值、重放幂等
  - 依赖：V6-3、V1-C1
- [ ] V6-5：Executive Agent 组合例外简报
  - 验收：只解释确定性组合结果，不排名个人；每项有来源和假设；接入管理层看板（V3-9）
  - 验证：capability golden、隐私/注入、前端回归、成本指标
  - 依赖：V6-3、V1-C2
- [ ] V6-6：性能、通知降噪、预测校准、安全红队与迁移演练
  - 验收：组合规模性能基线达标；通知重复/噪音受控；预测校准用 V3-8 历史序列；对象级数据保留策略（G17）；红队含辩论投毒与席位越权零穿透（I8）、跨租户/越权/过期引用/未审外发零穿透
  - 验证：负载、红队、迁移往返、真实受限账号、灾备演练
  - 依赖：V6-4、V6-5
- [ ] V6-7：试点业务指标验收、运行手册、回滚方案与 vNext Exit 报告
  - 验收：指标与 V0-5 校准基线对比完整；未达阈值有明确 NO-GO/延期例外；不把本地候选冒充生产事实
  - 验证：业务/Data/Quality/Security Owner 联合签字、人工 Exit Gate
  - 依赖：V6-6
- [ ] V6-8：报表导出中心、合规证据与开放 API（G15/G16/G19/G20/G22）
  - 验收：8D/DFMEA/Gate 评审包/项目周报一键导出客户模板（Word/Excel/PPT）；对客户报告白名单字段口径；ECN/Gate 电子签名留痕；ISO9001/IATF16949 按条款证据链导出；客户审厂证据包组装；对外 API 与事件 Webhook
  - 验证：导出格式走查（品质/PM 真实模板）、白名单泄漏负例、API 权限
  - 依赖：V4、V1-B6

### Checkpoint V6 / vNext Exit

- [ ] 跨项目依赖与共享资源案例通过确定性对账
- [ ] 里程碑兑现率、预警提前量、Issue 关闭、会议、齐套、数字链覆盖（需求追溯/样机配置/结构化测试/Gate 证据）与 Agent 指标达 PO 阈值
- [ ] `pdos_agent` 对真值表直接写为 0；越权/注入/辩论投毒红队 0 穿透
- [ ] 完整 `make check`、真实 HTTP/浏览器、迁移、观测与回滚门禁通过
- [ ] 人工确认 vNext Exit 后，才更新 canonical 与发布计划

---

## 附：决策/盲区 → 任务覆盖索引（V0-1 走查用）

| 决策 | 落点 |
|---|---|
| D1 AI-primary 显式失能 | V1-A10 |
| D2/D21 capability + 第 7 Agent | V1-C2、V5-9 |
| D4 Forecast/重基线 | V3-2/V3-5 |
| D5 Issue 治理 | V1-A4/A5 |
| D6/D19/D35 会议 | V2-1~V2-6 |
| D8/D14 需求关系与 DCP/TR | V5-10 |
| D9/D31/D38 信息架构与看板 | V1-A12、V3-9 |
| D10 提醒 | V1-A7/A8 |
| D13 typed scope | V0-3、V5-8 |
| D15 BOM 冻结 | V4-3 |
| D16/D32 三级授权 | V1-C1 |
| D24 指标引擎 | V5-4、V4-14、V3-7 |
| D25 agent-reach | V2-8 |
| D26 辩论 | V2-9、V4-11 |
| D27-D30 工程骨架 | V1-B1~B6 |
| D34 仅内部 | V4-15 移除 |
| D36/D37 Excel/报告驱动 | V1-B10/B2、V4-12 |
| G1-G4 冷启动/模板/空态 | V0-6/V0-7、V1-A3 |
| G5/G6 组织代理 | V1-A11 |
| G8 多站点时区 | V3-1 |
| G9/G10 多语言/币种 | V0-6、V4-14 |
| G11/G14/G21 移动/图纸/搜索 | V2-10 |
| G12/G26 批次/模具治具 | V4-12、V6-1 |
| G13→D36 测试入口 | V1-B10 |
| G15-G17/G19/G20/G22 报表合规 API | V6-8、V6-6 |
| G18 客户变更 | V1-B8 |
| G23/G24 AI 治理/失能 | V1-A10 |
| G25 固件版本 | V1-B11 |
| G27 NRE 预算 | V4-14 |
| G28 长周期在测 | V1-B3 |
| G29 EOL/PCN | V4-10 |
