# V1 风险与提醒周期调度 · 本地验证

日期：2026-09-08。用户在已确认的并行分工下批准开始 V1-A6/A7/A8 周期接线。本任务不修改另一任务的 AI 测试项对话实现。

**周期调度功能、受影响回归与真实进程/HTTP 验证通过。完整工程门禁仍待并行测试文件类型错误收口；未部署，未通过任何 Sprint / V1 Phase Exit。**

## 已实现的行为

- 独立 app-role 进程 `python -m scripts.run_reminder_scheduler`：启动即扫描，每轮结束默认等待 60 秒；支持 `.env` / 环境变量设置 1–3600 秒，以及 `--once`。风险候选、站内提醒与 outbox 派发共用同一轮 UTC 时钟。
- 数据库枚举 active tenant 的所有非 archived 项目，按租户/项目稳定分页；每个服务写入前复核范围。completed / on_hold 项目的未结工作保留既有提醒语义。系统动作审计 `actor_user_id=NULL`，人工确认风险、已读和审批仍要求真实用户。
- 周期锁避免双实例同时扫描；风险/提醒沿用项目行锁。派发按租户锁住配额、去重、outbox 与审计，全部使用一个连接和事务，避免并发超额、重复入箱或持锁后再借连接耗尽池。
- 单项目失败不阻塞其他项目，下一轮可重试；风险扫描失败不妨碍同项目提醒，提醒扫描失败则跳过派发。连接、语句及锁等待有超时；SIGTERM/SIGINT 在项目边界退出，重启按持久化记录安全重扫。
- 截止日或收件人变更时取消旧 scheduled 提醒，创建稳定的新版本；未触发的 cancelled 版本可恢复。兼容旧去重键，保留已触发历史，同一版本不会重发；新的停滞周期有独立提醒。
- `make dev` 同时启动并清理 API / web / reminders。生产 compose、smoke 模板、部署日志/启动/回滚列表已接线；回滚镜像不含新脚本时停止 reminders 并恢复主系统。部署验证识别两种调度失败日志。

没有新增依赖、迁移、UI 或 AI worker 权限。`pdos_worker` / `pdos_agent` 的业务表零写边界保留。调度器不持有 LLM 或钉钉密钥，不调用模型或钉钉 HTTP；外发执行仍由原 connector 和 S5-1 门禁控制。

## 验证与证据

数据库为两个临时容器，未挂载宿主目录，分别仅绑定 `127.0.0.1:58432`（回归）与 `58433`（HTTP），库名均严格为 `pdos_test`，停止后自动移除临时数据。没有连接开发或生产库。依赖使用上一轮按冻结锁文件安装的独立环境 `/private/tmp/pdos-v1-improvement-deps/server/.venv`。

| 验证 | 结果 |
|---|---|
| 受影响回归 | **151 项通过，111.40 秒**。覆盖调度、提醒、派发、风险候选、钉钉回归、工作项、My Work、驾驶舱、事件/审计、真实受限数据库角色以及运行模板；见 [日志](evidence/2026-09-08-reminder-scheduler/regression.log) |
| 调度模块 | 18 项，含启动自动触发、真实进程连续轮次/重启/SIGTERM、分页多租户、范围复核、三阶段失败恢复、双实例锁、静默顺延、配置拒绝；包含于上述 151 项 |
| 提醒生命周期 / 派发 | 分别 11 / 18 项；包括改期/换收件人、旧键兼容、取消恢复、系统/人工审计、单连接池、同/跨项目并发上限和整批出箱审计回滚；包含于上述回归 |
| 开发/部署运行合同 | 28 项；使用 stub 实际执行三种开发服务退出、新旧镜像回滚、发布失败日志正反例，未执行真实部署；包含于上述回归 |
| 完整后端 | **748 项通过，560.88 秒**，见 [完整日志](evidence/2026-09-08-reminder-scheduler/backend-full.log)。运行期间有其他任务的 AI 文件变动，属于工作树回归参考，非冻结候选发布门禁 |
| 静态与编译 | 本轮 13 个 Python 文件 Ruff / format / Mypy 通过，见 [类型结果](evidence/2026-09-08-reminder-scheduler/scoped-mypy.log)；compileall、Shell 语法与两份 compose YAML 解析通过。全后端初次 Ruff / format 通过（356 文件），末次复核遇到并行修改中的 `test_test_plan_sources.py` 两处长行，未改写另一任务文件 |
| 完整类型检查 | **未通过**：最近检查为 295 个源文件中，4 个并行 AI 测试文件有 14 个错误，见 [日志](evidence/2026-09-08-reminder-scheduler/full-mypy.log)。本任务未修改这四个文件，工作树仍在变化，不以专项通过宣告完整 `make check` 通过 |

真实 HTTP 场景使用合成租户、项目和钉钉绑定。通过本机 FastAPI 创建一个昨日到期任务，调用后台单轮脚本，完全没有请求扫描 API：

1. 首轮创建 1 个风险草稿、6 个提醒，触发 5 个，生成 5 条 manual outbox；`GET /api/me/notifications` 返回 200、未读 5。
2. 新进程重复单轮：新增/触发/入箱均为 0，已入箱计数 5。
3. 通过真实 HTTP 将任务从 todo→in_progress→done（两次 200）；下轮取消剩余 1 个 scheduled 提醒、清除风险候选，已触发的 5 条历史仍可查看。
4. 所有 outbox 均为 manual，attempt_count 为 0。此场景为了观察入箱，在隔离进程临时将静默窗口设为 `00:00-00:00`；默认静默窗口和顺延另有专项验证，没有修改生产配置。

真实进程错误路径另行将数据库指向不可达的本机 `pdos_test`：`--once` 退出码为 1，stdout 为空，stderr 仅有 `reminder_cycle_failed error_type=OperationalError`，不含测试密码或连接串，见 [失败证据](evidence/2026-09-08-reminder-scheduler/process-failure.json)。

见 [HTTP/进程结果](evidence/2026-09-08-reminder-scheduler/http-runtime.json)、[API 请求日志](evidence/2026-09-08-reminder-scheduler/http-api.log) 和 [复验脚本](evidence/2026-09-08-reminder-scheduler/http-smoke.py)。本轮 20 个代码/配置/手册文件指纹见 [SHA-256](evidence/2026-09-08-reminder-scheduler/source-sha256.json)。完整回归期间并行 AI 实现与测试仍在更新，因此该回归仅作为工作树诊断记录，不能替代冻结候选的发布门禁。验证库迁移 head 为已有本地候选 `0058_ai_test_plan_changes`，不代表生产迁移。

## 边界与接续

- 来源恢复取消的范围是**尚未触发的 scheduled 提醒**。fired / acknowledged 历史按原合同保留；尚未入箱的已触发历史仍遵循既有派发逻辑，本轮没有扩展为撤回历史通知。
- 周期等待从一轮结束开始计算，实际提醒延迟还包括扫描耗时；没有把 60 秒配置当作生产 SLA 或完成生产容量验收。进程健康检查只验证进程存在，应同时观察每轮 JSON 与失败日志。
- 待另一任务收口后复核联合完整类型门禁；真实 D14-04 单日工作流、S5-1 真实身份/外发与用户人工 Exit 仍按原合同推进。
- 本轮只交付本地代码、配置模板和验证；没有生产操作、远程 push 或真实消息发送。停用自动行为时只停止 scheduler，保留版本键兼容服务与历史数据；若回退到不识别新键的旧扫描实现，保持扫描/派发关闭并核对后再恢复，不能宣称旧实现仍可幂等重扫。不执行 schema 降级。运行步骤见 [手册](../runbooks/v1-reminder-scheduler.md)。
