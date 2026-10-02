# AGENTS.md · PDOS 编码入口

本仓库按[整合执行计划](docs/design/2026-09-09-ai-native-integrated-execution-plan.md)推进全量建设；[整合清单](tasks/ai-native-integrated-todo.md)是唯一活动状态来源。原 N/P/Q 编号、功能范围、验收判据和明确批准关卡保持。

## 当前执行节奏：加速建设、按影响验证（2026-09-27 用户再次明确）

- 按一个可用业务闭环连续实现，完成入口、领域动作、结果与异常处理后集中验证。文件、API、迁移或一次对话结束都不是独立交付批次；不把每个实现步骤变成“开发—完整验收—长报告”。
- 开发中合并必要的类型/lint/编译检查。权限、数据写入、事务和已知缺陷修复立即做最小受影响验证；低风险文案/展示不新增镜像实现的测试。通过后继续实现。
- 完整构建、HTTP/浏览器整链、亮暗/多尺寸、迁移往返及恢复演练集中到闭环或冻结候选检查点，按影响选取。记录候选与覆盖范围；同一候选无新改动、失败或具体风险不重跑。正式出口仍满足原联合门禁，历史分散通过不能冒充新候选完整通过。
- 测试只用显式 `TEST_DATABASE_URL` 指向已核对的独立临时 `pdos_test`。存续联验库 `localhost:57432/pdos_test` 禁止 repo 测试；不得回退 `.env`。相容检查复用已确认的隔离环境，必要备份保留，环境清理/收尾在检查点集中进行；新建隔离条件或破坏性场景才另建环境。
- Skill 按当前具体问题选用，不自动串联规划、审阅、QA、攻防或图谱流程；不使用 graphify。方法论引用不构成每轮加载 Skill 的要求。默认由主会话连续执行；显式授权的并行仅限独立交付和明确文件归属，公共验证统一执行，不因历史并行记录自动启动多 Agent。
- 进度在唯一清单原位更新“可用能力、必要证据、剩余缺口/下一步”，每个闭环一个简短状态。原始日志放证据目录并链接；AGENTS.md 不追加进度流水，历史不默认加载。
- 遇到权限、外部网络或真实材料阻塞，只暂停依赖部分并记录恢复条件；无条件变化不重复相同探测，继续授权内独立建设。模拟通过不能宣称真实资格、生产启用或人工 Exit 通过。

## 续接入口与按需阅读

1. 先读[清单当前队列](tasks/ai-native-integrated-todo.md#current-queue)，再读取本闭环涉及的 N 项依赖/交付/验收；不要从旧 N0 起重跑，不全文重读历史日志。
2. 施工顺序与验证层级见[计划 §3](docs/design/2026-09-09-ai-native-integrated-execution-plan.md#execution-cadence)。[完整设计合同](docs/design/2026-09-10-pdos-complete-design-contract.md)按当前对象/职责查阅；原规格 `docs/specs/cehub-v3.2-preview/`、[原版计划](docs/design/2026-08-09-preview-execution-plan.md)基础设施参数/§11 及 S0–S5 canonical Exit 保留，首次涉及对应领域再定向阅读。
3. 前端遵循[UI 基线](docs/design/2026-08-09-ui-baseline.md)与[原稿](docs/design/ui-baseline-mockup.html)：shadcn/ui + Tailwind v4 + Geist，橙色亮 `#c2410c` / 暗 `#fb923c`，圆角 8px，双主题，Phosphor 图标。不换栈或新增第二套 UI 库。
4. 决策背景见[全量新建说明](docs/design/2026-08-09-cehub-v32-convergence.md)；只有追溯特定旧结论时读取[入口历史](AGENTS.history-2026-09-27.md)或清单对应历史锚点。归档中的旧“当前/下一步”不是执行命令。

## 当前状态指针

- 当前业务闭环、余项、验证证据和 P1 阻塞统一见[唯一清单](tasks/ai-native-integrated-todo.md#current-queue)，此处不复制版本流水。
- 9/27 存续联验库误操作及恢复边界不能丢失：已恢复备份基线0377，备份后的部分登录/序列记录无法完整重建，不能宣称零丢失。护栏与原证据见清单 N7-02，后续工作不得覆盖该历史。

## 不可协商项（违反=返工）

1. **AI 写入分级**：已批准 [DC-11](docs/design/2026-09-20-ai-direct-write-tier-policy.md) 的对象/操作按 T0/T1/T2 办理；T0 须真实资格与当前授权，T1 预填一次确认，T2 保留具名签核/批准/正式发布/外发。未迁移能力维持 Finding 接受与独立应用。独立 AI 身份经受控领域服务写入，`pdos_agent` 对业务表零直接写权限，永不取得 T2 执行权；不得把政策批准视为资格授予。
2. **模型传参不作为政策事实**：租户/项目范围与权限由服务器从 run 上下文绑定；AI 来源、引用、运行回执、幂等/过期/原子性及撤回守卫保留。
3. **迁移纪律**：Alembic schema 与迁移一致，按实施时真实 head 单调分配，不复用旧预留号；迁移步骤不是逐步完整验收的理由。
4. **前缀冻结**：定稿 system prompt/工具定义不插动态内容，动态状态由代码预聚合追加至 context 末尾。
5. **业务与可信根边界**：不替代 ERP/MES/PLM；worker 错误路径零 LLM；golden-case 是可信根，自动化不得写入。
6. **固定技术栈**：Next.js + FastAPI + PostgreSQL + LangGraph(Python) + shadcn/ui；新增实体/namespace 按已批准共同合同及迁移，不把原版数量当永久上限。

## 环境与资产

- `.env` 由用户依 `.env.example` 填写。模型为租户级功能，凭据不暴露，白名单须 golden-case 通过；缺凭据只阻塞依赖模型的实际调用，不阻塞本地实现。协议支持 OpenAI 兼容与 Anthropic 原生。
- 本地 compose 默认 PG16/pgvector `55432`、MinIO `9000` 是开发环境，不是测试地址授权；每次数据库操作前核对实际目标。
- `certs/ApsaraDB-CA-Chain.pem` 与 `assets/cehub/deliverable-guide-manifest.json`（687 条 checkItems）沿用；直接消费清单，不解析 xlsx 反推。
- 老 CEHub `~/Desktop/ce-project-hub` 仅为可选参考；无法访问时依合同实现，不形成阻塞。

## 必须保留的批准与验收边界

- RDS 建账号/建库、OSS 建桶、ECS 部署、Nginx/DNS、git push、生产操作、真实外发/业务数据出站，以及偏离范围的实质变更，执行前须有对应明确授权；同范围有效授权复用。
- Sprint、原版生产与 Q0–Q6 的人工出口仍汇报并等待原规定的确认。闭环开发检查点不新增阶段审批；等待某项确认不阻断已获授权的独立建设。
- 完成以原条目全部验收为准；原 Sprint 2 的红队零穿透/停 LLM 可见失能等正式验收保留，在适用出口执行，当前不自动启动重复攻防或真人试用。
