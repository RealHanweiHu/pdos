# AGENTS.md · 交接给任何编码 Agent 的入口

本仓库是 **PDOS（AI-native 产品开发操作系统，工作名）** 的全量建设项目。你的任务是**严格按执行计划推进**，不是重新设计。

## 必读顺序（动手前）

1. `docs/design/2026-08-09-preview-execution-plan.md` — **唯一执行依据**：六 Sprint 工作项+验收判据、基础设施参数、§11 方法论施工纪律
2. `docs/specs/cehub-v3.2-preview/` — 产品规格（11 份，实体/Agent/事件目录/状态机/SoR 边界以此为准）
3. `docs/design/2026-08-09-ui-baseline.md` + `docs/design/ui-baseline-mockup.html` — UI v0.2 已拍板：shadcn/ui + Tailwind v4 + Geist，橙色强调（亮 #c2410c/暗 #fb923c），圆角 8px，双主题；前端严格按此实现
4. `docs/design/2026-08-09-cehub-v32-convergence.md` — 决策背景（为何全量新建、老 CEHub 的角色）

## 当前进度指针

- [x] S0-0 UI 基线 v0.2（已拍板）
- [x] 仓库首次 git commit 已完成：`d28d984`（docs/模板/资产全量入库，未 push）
- [x] S0-1～S0-5 本地工作项、RDS/OSS、生产迁移、ECS 容器与一次性 setup 已完成
- [x] Sprint 0 Exit Gate 已于 2026-08-11 经人确认通过
- [x] S1-1 Requirement 池已完成：需求录入/编辑/Customer 关联、REQUIREMENT event+audit 与真实浏览器验收全绿
- [x] S1-2 Development Case + 转化已完成：一次性 Requirement→Case、Decision 留痕、Case 状态机与真实浏览器验收全绿
- [x] S1-3 Project + Workflow/Stage 实例化已完成：Case→Project 原子动作、七态状态机、七阶段 Timeline 与真实浏览器验收全绿
- [x] S1-4 Task / Issue / Risk 已完成：依赖 readiness、Issue/Risk 状态机、项目权限、同源 BFF 与真实 HTTP 验收全绿
- [x] S1-5 事件全覆盖 + 调试页已完成：22 类已实现事件覆盖、tenant-bound cursor API、只读调试页与管理员权限验收全绿
- [x] S1-6 前端第一版已完成：Dashboard Portfolio/Risk 两卡、Project Workspace 五标签及 Sprint 1 真实浏览器闭环验收全绿
- [x] Sprint 1 Exit Gate 已于 2026-08-11 经人确认通过
- [x] S2-1 LLM Gateway（多供应商）已完成：租户模型治理、两类协议、结构化输出、调用留痕、预算熔断、上下文/出口白名单与 golden-case 人工发布门禁均验收通过
- [x] S2-2 LangGraph 执行环已完成：dispatcher/executor 分离、项目级 debounce、静态路由、冻结 context、三只读工具、失败熔断与隔离容器 smoke 均验收通过
- [x] S2-2b 数据库层安全边界已完成：独立 worker/agent 登录角色、run lease 租户投影、业务表零写、真实受限账号正反向测试与 DBA 幂等手册均验收通过
- [x] S2-3 AI Finding 状态机已完成：受限 Agent 创建、确定性预检、pending_review→accepted/rejected→applied、两次人工动作、apply 真值复核与全链路留痕均验收通过
- [x] S2-4 Phase 1 双 Agent 已完成：两份版本化静态 prompt、Project Intelligence 三类 Finding、Knowledge Lite 知识草稿、订阅/受限写入/评测合同与完整门禁均验收通过
- [x] S2-5 API 面已完成：引用强制的只读 Chat、PDF/XLSX 抽取与私有对象存储、风险建议 pending Finding 通道、幂等外部 Event 接口均验收通过
- [ ] **当前：S2-6 前端 AI 面**，按 `tasks/todo.md` 交付 AI Review 收件箱、Dashboard AI Brief 与 Project AI Chat 标签
- 生产入口经人于 2026-08-11 确认采用现有 Nginx + `pdos.beepump.net`，见 `docs/decisions/ADR-001-production-edge-nginx.md`
- 每完成一个工作项：验收条款 + 项目级 DoD 全部满足，更新执行计划 checkbox 与 `tasks/todo.md` 当前指针，再进下一项

## 不可协商项（违反=返工）

1. **AI 输出人审**：Agent 唯一写出口=创建 finding；接受与应用是两个人工动作；数据库角色 `pdos_agent` 对业务表零写权限（S2-2b 是安全边界，不是可选项）
2. **模型传参不作为政策事实**：工具的租户/项目范围由服务端从 run 上下文绑定
3. **迁移纪律**：Alembic 从第 1 天规范化，schema 与迁移永不脱节；迁移号单调递增不复用
4. **测试隔离**：测试只连 `pdos_test` 库，绝不碰开发/生产库
5. **前缀冻结**：Agent system prompt+工具定义定稿后不插动态内容；动态状态由代码预聚合追加到 context 末尾
6. **不替代 ERP/MES/PLM**；worker 错误路径零 LLM 调用；golden-case 评测集是可信根，自动化不得写入
7. **栈已定**：Next.js + FastAPI + PostgreSQL(10 schema namespace) + LangGraph(Python) + shadcn/ui。不换栈、不加第二 UI 库、不混图标族（Phosphor）

## 环境与资产

- `.env`（本地）由用户从 `.env.example` 复制填写；**模型选择是租户级产品功能**（治理页设置，默认 MiniMax 国内版；下拉=env 配了凭据且 golden-case 评测通过的白名单，key 不暴露给用户）；协议层只有两种形态：OpenAI 兼容（GLM/MiniMax/OpenAI/DeepSeek）+ Anthropic 原生，见 `.env.example` 与计划 S2-1。缺 `PDOS_LLM_API_KEY` 时 Sprint 0/1 照常推进，Sprint 2 需要。新模型入白名单必须先过 golden-case
- 本地库：`docker compose up -d`（PG=pgvector/pg16 端口 55432 + MinIO 9000）——compose 文件在 S0-1 创建
- `certs/ApsaraDB-CA-Chain.pem`（RDS CA）与 `assets/cehub/deliverable-guide-manifest.json`（Sprint 3 检查项资产库，687 条 checkItems，**直接消费勿解析 xlsx 反推**）已随仓库携带
- 参考代码（可选复用）：老 CEHub 仓库在本机 `~/Desktop/ce-project-hub`（gate 签核轮次/租户 fail-close/activityLogTailer 语义值得参考重实现；若无法访问该路径，按规格与计划独立实现即可，复用非必需）

## 必须停下问人的事（不得自行执行）

- RDS 控制台建账号/建库、OSS 建桶、ECS 部署与 Nginx/DNS 变更（一次性动作，运行手册里有步骤）
- 任何 git push 到远程、生产环境操作
- 偏离执行计划的范围变更（先提出，人拍板后再做）
- 每个 Sprint 出口：汇报验收结果，等确认再进下一 Sprint

## 验证要求

- 每个工作项完成的判据是执行计划里写的验收条款，不是"代码写完了"
- Sprint 2 的红队违例测试（注入诱导写业务表→0 穿透）与拆除测试（停 LLM→系统可见失能）是硬验收
