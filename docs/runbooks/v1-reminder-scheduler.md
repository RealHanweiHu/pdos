# V1 风险候选与提醒周期调度

本手册对应 V1-A6/A7/A8 的周期接线。`reminders` 是独立确定性进程，使用 app 数据库角色，依次调用风险候选扫描、站内提醒扫描和提醒 outbox 派发。它不调用模型或钉钉 HTTP 接口，也不改变 `pdos_worker` / `pdos_agent` 的权限。无新增迁移。

## 配置与行为

| 参数 | 默认值 | 含义 |
|---|---|---|
| `DATABASE_URL` | 必填 | app 数据库连接；生产沿用 `pdos_app`，测试只用 `pdos_test` |
| `JWT_SECRET` | 必填 | 共用 Settings 校验所需；不用于伪造用户或登录 |
| `PDOS_REMINDER_SCAN_SECONDS` | `60` | 启动即扫描；每轮结束后等待 60 秒，可配置为 1–3600 秒 |
| `PDOS_REMINDER_QUIET_HOURS` | `21:00-08:00` | Asia/Shanghai 钉钉个人提醒静默窗口；站内提醒仍正常触发 |
| `PDOS_REMINDER_DAILY_DM_CAP` | `50` | 每租户内每位收件人的每日派发上限；与 API 手动派发共享 |
| `PDOS_PUBLIC_BASE_URL` | 本地 `http://localhost:3000` | outbox 内容中的“打开我的工作”链接；生产模板为 `https://pdos.beepump.net` |
| `PDOS_DINGTALK_DELIVERY_ENABLED` | `false` | 关闭时新 outbox 为 `manual`，错误码 `DINGTALK_DELIVERY_DISABLED`，零外发 |

范围为 active tenant 的所有非 archived 项目，保留 completed / on_hold 项目现有未结任务和问题的提醒语义；项目归档、租户停用后不再自动写入。范围由数据库和服务端绑定，不从模型参数取得。系统扫描的审计 `actor_user_id` 为空；人工确认风险、确认已读等动作继续记录真实用户。

风险条件恢复时清除未确认候选，复发时可恢复同一候选。任务完成或问题关闭后取消尚未触发的 scheduled 提醒，已触发和已确认的历史保留。重扫、重启使用既有候选来源键、提醒去重键及 outbox 唯一约束，不重建历史。静默时段或日上限顺延的提醒保留，后续轮次继续处理；未绑定钉钉的收件人仍能在站内查看通知。

## 本地单轮与持续运行

日常本地开发执行仓库根目录的 `make dev`，会同时启动 API、web 和 reminders，并输出三个进程 PID；任一服务退出时一并停止其他服务，Ctrl-C 也会清理三个进程。scheduler 使用本地开发配置，默认每轮等待 60 秒。开发启动不隐式启用 AI worker 或改变外发开关。

以下仅用于本地隔离验证。先准备 `pdos_test` 及依赖，在仓库的 `server` 目录运行；测试数据通过现有本地 API 或 fixture 创建，不能指向开发库或生产库。

```sh
export TEST_DATABASE_URL='postgresql://pdos:pdos@127.0.0.1:55432/pdos_test'
export DATABASE_URL="$TEST_DATABASE_URL"
export JWT_SECRET='test-only-jwt-secret-that-is-at-least-32-bytes'
export PDOS_DINGTALK_DELIVERY_ENABLED=false
export PDOS_PUBLIC_BASE_URL=http://localhost:3000
export PDOS_REMINDER_SCAN_SECONDS=60
.venv/bin/python -c 'from app.db.test_safety import configured_test_database_url; configured_test_database_url()'
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.run_reminder_scheduler --once
```

`--once` 完成单轮后退出；项目失败或整轮失败返回非零。持续运行时省略 `--once`：

```sh
.venv/bin/python -m scripts.run_reminder_scheduler
```

发送 SIGTERM 或 Ctrl-C（SIGINT）请求停止：等待中的进程立即唤醒，正在处理时完成当前项目后停止取下一项目，并释放连接。数据库连接、语句和锁等待均有超时。若容器超过 30 秒退出宽限期被终止，未提交事务由 PostgreSQL 回滚，下次启动按幂等规则重扫。

## 并发、故障与观察

每轮通过 PostgreSQL advisory lock 防止多个 scheduler 同时扫描；竞争实例返回 `skipped_locked=true`，下一轮继续。风险与提醒写入沿用项目行锁；派发配额与去重由服务层的租户级 PostgreSQL 锁保护，覆盖 API 与 scheduler 并发。

一项目失败不阻塞其他项目，下一轮重试。风险扫描失败后仍可处理同项目提醒；提醒扫描失败时跳过该项目派发，避免使用未协调的提醒状态。已成功的项目使用各自短事务提交，后续失败不会撤销它们。数据库连接中断等整轮失败也会在下一轮重试。

stdout 每轮输出 JSON，`event=reminder_cycle`，包含项目数、失败项目数、候选创建/恢复/清除数、提醒计划/取消/触发数、入箱/已入箱/未绑定/静默顺延/限流数，以及锁竞争和中断标记。失败日志只保留租户/项目 ID、步骤和异常类型，不打印连接串、SQL、凭据或提醒正文。

排查顺序：先确认进程与最新轮次日志，再看 `failed_projects`、`skipped_locked`；有站内提醒但未产生个人消息时，依次检查 `skipped_unbound`、`deferred_quiet_hours`、`capped_recipients` 及 outbox 状态。容器健康检查只证明进程存在，完整可用性需要结合轮次结果。不要通过打开外发开关验证周期扫描。

## 运行模板与生产边界

`compose.production.yaml` 的 `reminders` 服务复用 API 镜像，等待迁移完成，保持只读容器文件系统、非 root 用户、无公开端口和 `unless-stopped` 重启策略。它只接收上表变量，不接收 LLM、钉钉或对象存储凭据。API 与 scheduler 同时接收静默时段和日上限，避免手动和自动派发口径不同。`compose.production-smoke.yaml` 提供本地测试容器的 host gateway 映射。

部署脚本已将 reminders 纳入启动、健康等待及日志检查，遇到 `reminder_project_failed` 或 `reminder_cycle_failed` 明确失败标记时拒绝将该次发布验证判为通过。回滚时先以无网络、只读文件系统、无运行凭据的临时容器检查旧 API 镜像是否携带 scheduler 脚本：支持则一并启动；不支持则停止 reminders，恢复原有 API / dispatcher / executor / dingtalk / web，保留主系统回滚路径。回滚不降级数据库，停止 scheduler 不删除提醒或 outbox 历史。

停用自动行为时优先只停止 reminders，保留能识别版本化去重键的提醒服务。若回退到只识别旧去重键的扫描实现，保持提醒扫描/派发停用，先核对已触发历史再恢复；旧实现不能保证对新版本键重扫仍幂等。不能用直接删除提醒或 outbox 的方式处理回滚。

本地模板与验证不等于生产启用。生产部署、配置变更和真实钉钉外发仍须逐次明确授权，S5-1 与 Sprint / V1 Phase Exit 继续单独裁决。`delivery=false` 的 manual outbox 不因 scheduler 重启或将来启用开关而自动重放；经授权后沿现有对账/重放流程处理。
