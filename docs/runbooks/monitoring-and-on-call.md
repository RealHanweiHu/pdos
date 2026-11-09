# 监控告警与值班

适用欠债总表 D213，以及 v1.1 §10“技术界面显示延迟、错误、费用、重试、队列积压”。

探针、指标端点和告警格式已实现，并在本地隔离环境跑通（[证据](../reports/evidence/w11-ops-20261108/README.md)）。钉钉群和机器人凭据要等 D64，现在只有接口和配置位；部署位置、真实地址随 D210。阈值是建议起步值，值班人和响应时限由你定，都标“〔你〕”。

## 1. 监控项

| 信号 | 指标来源 | 告警条件（建议起步值〔你〕） | 级别 |
|---|---|---|---|
| 探活 | 探针请求 API `GET /health` 和 Web 登录页 | 连续 3 次失败（每分钟一次，约 3 分钟） | 严重 |
| 错误率 | API 进程的 `GET /ops/metrics`：按状态类别累计的响应数；探针取两次之差 | 两次之间至少 20 个请求，且 5xx 占比 ≥ 5% | 严重 |
| 队列积压：事件外发 | 数据库函数 `ops_health_counters`（迁移 `s0_0867`）：每个租户未投递事件数、最早一条的等待秒数 | 最早一条等待 ≥ 300 秒，或未投递 ≥ 200 条 | 警告 |
| 队列积压：Temporal | Temporal `DescribeTaskQueue`：`pdos-next-domain-v1` 的工作流、Activity 两类任务的取任务 Worker 数、积压数、最早任务等待时间 | 没有 Worker 在取任务（严重）；积压 ≥ 100 个，或最早任务等待 ≥ 300 秒（警告） | 严重 / 警告 |
| 模型失败率 | 同一函数：最近 15 分钟小Pai模型调用中失败和结果未知的比例；超过 10 分钟仍未结束的调用数 | 至少 5 次调用且失败或未知 ≥ 20%；或有 1 个调用超过 10 分钟未结束 | 警告 |
| 探针自身 | 取数失败（指标端点、数据库、Temporal 连不上） | 出现即报 | 警告 |

说明：
- 模型失败率按租户算，只数小Pai的模型调用（`agent_tool_calls` 里绑定类型为 `model` 的记录），“结果未知”算失败。模型服务商整体不可用时，探活和错误率可能都正常，这一项是唯一信号。
- `ops_health_counters` 只返回数字，不返回任何 ID 或内容；只对会话设定的租户有效；只有技术调度角色 `pdos_next_dispatch` 能执行，应用、认证、AI 角色都不能。
- 主机、磁盘、RDS 连接数与慢查询用阿里云云监控，随 D210 一起配（D350）。

## 2. 指标端点

`GET /ops/metrics`，Prometheus 文本格式，内容：`pdos_up`、`pdos_database_up`（应用角色能否执行 `SELECT 1`）、`pdos_http_responses_total{class=...}`、请求耗时直方图。只按状态类别计数，不带路径、用户、租户。

- 默认关闭。设置环境变量 `PDOS_METRICS_TOKEN`（至少 32 个字符）后开启，请求要带 `Authorization: Bearer <令牌>`，错误令牌返回 401。
- 不在 OpenAPI 文档里，Web 的 BFF 不转发它；只在内网给探针读（见发布手册第 6 节）。
- 实现在 `server/pdos_next/ops/metrics.py`，只加了计数中间件，不改任何业务逻辑。

## 3. 探针

`python -m pdos_next.ops.probe --config <配置> [--state <状态文件>] [--once]`，在 `server/` 下用 `server/.venv/bin/python` 执行。不带 `--once` 时按配置里的间隔（默认 60 秒）一直跑，部署成常驻进程或定时任务随 D210。

配置示例：`config/ops/monitoring.example.json`，内容是地址、阈值、告警通道和值班的配置位。探针用到的环境变量：

| 变量 | 用途 |
|---|---|
| `PDOS_METRICS_TOKEN` | 读 API 指标端点 |
| `DISPATCH_DATABASE_URL` | 技术调度角色连接，执行 `ops_health_counters` |
| `PDOS_WORKFLOW_TENANTS` | 要统计的租户，逗号分隔，与 Worker 相同 |
| `PDOS_TEMPORAL_ADDRESS`、`PDOS_TEMPORAL_NAMESPACE` | Temporal 地址 |
| `PDOS_ALERT_DINGTALK_WEBHOOK`、`PDOS_ALERT_DINGTALK_SECRET` | 钉钉群机器人地址和加签密钥（等 D64） |
| `PDOS_ALERT_DINGTALK_MOBILES` | 告警时 @ 的手机号，逗号分隔（〔你〕） |

去重：同一告警持续存在时，每 30 分钟〔你〕重发一次；消失后发一条“已恢复”。状态文件只有本人可读，保存连续失败次数、上次计数和当前告警。

## 4. 告警通道：钉钉群

- 用钉钉群的自定义机器人，安全设置选“加签”。地址必须是 `https://oapi.dingtalk.com/...`，其他地址拒绝。
- 消息是 markdown：环境名、每条告警的级别、摘要和告警键、已恢复的告警，末尾指向这页。不带任何业务内容、客户名或原件名。
- 机器人回复错误码时，探针在自己的日志里报错，下一轮继续。
- 没有配置机器人时，告警以 JSON 行写到探针的标准输出，什么也不往外发。
- **待 D64**：建群、加机器人、拿到地址和密钥，放进凭据管家，再配到探针的环境变量里。与产品内钉钉应用（D64 的企业内部应用）是两套凭据。

## 5. 值班（〔你〕待定）

| 项 | 内容 |
|---|---|
| 主值班 | 〔你〕 |
| 备值班 | 〔你〕 |
| 值班时段 | 〔你〕（例如工作日 9–18 点；时段外只处理严重告警） |
| 严重告警响应时限 | 〔你〕（建议 15 分钟内确认、1 小时内给出处理方向） |
| 警告响应时限 | 〔你〕（建议当个工作日内） |
| 升级 | 〔你〕：超过时限无人确认时找谁 |

确认告警：在钉钉群里回复“已接 + 告警键”。处理完写一句原因和处理方式。

## 6. 收到告警先做什么

| 告警键 | 先查 | 常见原因 |
|---|---|---|
| `liveness:api` / `liveness:web` | 进程是否在、最近一次发布、主机资源 | 进程退出、发布中、端口或证书问题 |
| `error_rate:api` | API 日志里 5xx 的接口和报错 | 数据库不可用（同时看 `pdos_database_up`）、新版本缺陷（按发布手册判断是否回滚） |
| `backlog:pollers:*` | Worker 进程是否在、能否连上 Temporal | Worker 退出或卡住；发布后没启动 Worker |
| `backlog:temporal_*` | Worker 日志里的 Activity 报错和耗时 | Activity 依赖不可用、并发不够（`PDOS_WORKER_ACTIVITY_THREADS`） |
| `backlog:outbox_*` | Worker 投递循环的日志 | Worker 停了、调度角色连不上数据库、某个事件反复失败 |
| `model_failure:*` / `model_open:*` | 模型配置页、服务商状态、运行核对页 | 服务商故障或限流、凭据失效、费用上限；小Pai会显示不可用原因，人员可继续用业务入口（AT-45） |
| `probe:*` | 探针自身的连接配置 | 令牌、口令或地址改了 |

处理时不手工改业务表；运行卡住走[中断运行结果核对](pdos-next-run-reconciliation.md)，外发结果不明走[备份手册](backup-and-restore.md)第 5 节第 4 步的核对办法。

## 7. 已知缺口

- D349：Worker 进程本身没有指标端点。Activity 失败只能从 Temporal 队列积压和模型失败率间接看到；需要时用 Temporal SDK 自带的 Prometheus 输出补上。
- D350：主机、磁盘、RDS 指标和云监控告警随 D210。
- 阈值是起步建议，试点两周后按实际数据调整〔你〕。
