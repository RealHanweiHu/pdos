# 全执行计划完成审计

> 审计日期：2026-08-14
> 唯一基准：`docs/design/2026-08-09-preview-execution-plan.md`
> 最终代码 release：`82de9d215c5b0101aaba8cbff2d1adf6d751ceef`

## 1. 结论

在 2026-08-14 经人批准的 Sprint 5 / Cutover Exit 口径下，六个 Sprint 的建设与本次生产切换已经完成，当前没有待执行的主计划工作项。

- canonical 共 35 个工作项：34 个为 `[x]`；唯一未勾选项为 S5-1。
- S5-1 的本地连接器、隔离测试、发布级 compose smoke 与真实浏览器/API 验收已经完成；真实钉钉 password-free login、群通知、审批和 card smoke 未执行，也未伪记为通过。
- Data Owner、发布 Owner、业务 Owner 已明确接受上述 S5-1 真实应用 Gate 为延期残余风险，并批准 Sprint 5 / Cutover Exit；生产继续强制 `PDOS_DINGTALK_DELIVERY_ENABLED=false`。
- Sprint 0～5 的人工出口均已确认；最终 release 已部署到生产 migration `0030`，完成 CEHub 全量迁移 apply、独立目标抽查、同参数幂等重放、主入口声明及声明后 1844 秒只读观察。

因此，本次“完成所有执行项目”的验收范围已经达成；S5-1 仍作为显式延期风险存在，不属于被改写为 PASS 的完成项。未来执行真实钉钉 smoke、开启外发、恢复 CEHub 写入、修改 DNS/Nginx 或最终停机，均是新的受控操作，需另行明确授权。

## 2. 逐 Sprint 对照

| Sprint | canonical 状态 | 权威实现/运行证据 | 人工出口 | 判定 |
|---|---:|---|---|---|
| Sprint 0 | 6/6 `[x]` | `docs/reports/2026-08-11-sprint-0-exit.md`；`tasks/todo.md` 的 RDS/OSS/ECS、setup、Nginx/TLS、登录和 30 分钟观察记录 | 2026-08-11 已确认 | 完成 |
| Sprint 1 | 6/6 `[x]` | `tasks/todo.md` 的 Requirement→Case/Decision→Project→Task/Issue、事件回放、Timeline、权限、双主题浏览器与完整门禁记录 | 2026-08-11 已确认 | 完成 |
| Sprint 2 | 8/8 `[x]` | `tasks/todo.md` 的 Gateway、LangGraph、`pdos_agent` 零业务表写、Finding 双人工动作、双 Agent、AI API/UI、红队与拆除测试；`docs/reports/2026-08-12-sprint-2-production-deployment.md` | 2026-08-12 已确认并选定 C4s/S18-01 | 完成 |
| Sprint 3 | 7/7 `[x]` | `docs/reports/2026-08-12-sprint-3-exit-draft.md`；C4s/S18-01 的生产 dry-run、apply、独立抽查与重放报告 | 2026-08-12 已确认 | 完成 |
| Sprint 4 | 4/4 `[x]` | `docs/reports/2026-08-12-sprint-4-exit-draft.md`，覆盖 CAPA、verified Memory、Phase 2 Agent 与 Context Builder v2 | 2026-08-12 已确认 | 完成 |
| Sprint 5 | 3/4 `[x]`；S5-1 `[ ]` | S5-2～S5-4 各验收报告；`docs/reports/2026-08-13-sprint-5-exit-and-cutover-candidate.md`；S5-1 本地完成但真实应用 Gate 延期 | 2026-08-14 三方确认 Exit，并接受 S5-1 残余风险 | 按批准例外完成 |

计数由唯一执行计划表格直接核对：`6 + 6 + 8 + 7 + 4 + 4 = 35`，其中 34 个完成、1 个按批准例外保持未完成标记。

## 3. 不可协商项复核

| 不变量 | 当前证据 | 判定 |
|---|---|---|
| AI 输出必须人审 | Finding 仅能进入 `pending_review`；Accept/Reject 与 Apply 是两个独立人工动作；服务端 Apply 重查数据库真值 | 满足 |
| `pdos_agent` 对业务表零写 | Sprint 2 红队、独立角色与生产安全 SQL 重施/验证均通过；生产部署后边界复核通过 | 满足 |
| 模型参数不作为政策事实 | tenant/project 范围由 run lease、服务端投影与工具绑定；跨租户/跨项目负例 0 穿透 | 满足 |
| 迁移单调且 schema 同步 | Alembic 从 `0001` 单调推进至生产单一 head `0030_phase_three_agents`；迁移往返、metadata drift 和生产 migrator 均有门禁 | 满足 |
| 测试库隔离 | 自动化只连接 `pdos_test`，生产步骤均经独立人授权与运行手册执行 | 满足 |
| prompt/tool 前缀冻结 | Phase 1～3 prompt 版本化；Context Builder 动态状态仅追加在冻结前缀之后，回归已覆盖 | 满足 |
| 不替代 ERP/MES/PLM | ERP Handoff 仅交付冻结 EBOM/effectivity；未配置 ERP API 时保持 manual，SoR 边界未扩张 | 满足 |
| worker 错误路径零 LLM / golden 根只读 | 拆除演练、错误路径和 golden-case 人工晋级门禁均已进入质量流程 | 满足 |
| 冻结技术栈和 UI 基线 | Next.js + FastAPI + PostgreSQL + LangGraph + shadcn/ui/Tailwind v4；Geist、Phosphor、双主题与橙色基线保持一致 | 满足 |

## 4. 最终生产与切换证据

- release / Git / OCI revision：`82de9d215c5b0101aaba8cbff2d1adf6d751ceef`。
- inventory fingerprint：`a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d`。
- source fingerprint：`d3d903b6bfa05958678b00502e565f0629d34d634242c8adb49c5a6f06d56b54`。
- 有序项目：`WqWcl0wK,aBnbEdQG,xY8-PGbc,zGpNH0Xq`；目标 tenant：`e340c240-d8f0-429c-aac5-69ab9b42fac5`；actor：`4bdba865-c5b1-4ca1-aa85-be467e1fad42`。
- 全量 apply 后目标独立抽查为 4 Project、117 Task、25 Gate、14 external file reference、141 migration mappings；重放除新增 Migration Run 审计外，业务表和 mapping 的 count/content hash 均未改变。
- `pdos.beepump.net` 已由业务 Owner 声明为正式主入口；四项目登录/查询与 Workspace 验收通过，浏览器 console warning/error 为 0。
- 正式观察窗共 61 个样本、1844 秒；五个 PDOS 容器、HTTP/TLS、镜像 revision、restart、fatal/500 日志、CEHub 归档状态与 `delivery=false` 全部通过。
- CEHub 保持只读归档：读取正常，写探针被 PostgreSQL `25006` 拒绝；容器 running、restart=0；未恢复写入。

完整生产证据：

- `docs/reports/2026-08-14-sprint-5-production-release-revalidation.md`
- `docs/reports/2026-08-14-sprint-5-production-apply.md`
- `docs/reports/2026-08-14-sprint-5-main-entry-observation.md`

## 5. 显式残余风险与后续控制

S5-1 仍缺少以下真实企业应用验证：

1. 已绑定用户的真实 password-free login 及未绑定/错 corp/state replay 负例；
2. 项目群通知到达、outbox `succeeded` 与 remote reference 对账；
3. 外部审批回调只更新镜像且不改变 PDOS Gate；
4. card acknowledge 成功及重复回调仅处理一次；
5. 人工确认 S5-1 独立 Exit Gate。

约束保持不变：canonical S5-1 与 `tasks/todo.md` 对应 Gate 继续未勾选，生产 `delivery=false`。任何真实外发或上述 Gate 执行必须重新获得明确授权，并在成功后形成独立证据；本次 Exit 确认不自动授权这些动作。

## 6. GitHub 交付状态

只读核验时，GitHub `main` 指向最终代码 release `82de9d215c5b0101aaba8cbff2d1adf6d751ceef`，没有开放 PR。生产 revalidation、apply、观察、Exit 确认及本审计均位于本地 `codex/sprint5-production-evidence` 证据分支；这些提交只修改文档，不改变已部署代码。远端发布该证据分支并创建 PR 是审计轨迹的最后交付动作，必须按仓库规则在获得明确 push 授权后执行。
