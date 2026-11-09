# 发布与回滚

适用欠债总表 D212，以及 D214 的余项“反向代理要设 `X-Real-IP`”。每次试点发版按这页走。

写这页时没有做任何云上操作，ECS、Nginx、DNS 都没动。服务器上的具体命令（目录、服务名、compose 文件）要等部署方案 D210 定了再补；执行前仍须对应授权（AGENTS.md“必须保留的批准与验收边界”）。标“〔你〕”的由你决定。

## 1. 维护窗口与通知

- 提前通知：建议至少提前 1 个工作日〔你〕，在钉钉支持群（D219）发：开始时间、预计时长、期间哪些功能不可用、回滚条件、联系人。
- 窗口时间：建议避开工作时间〔你〕。
- 窗口内 Web 显示维护页；登录会话保留，窗口结束后不用重新登录。
- 每次发版附一段中文说明（D219）：改了什么、对谁有影响、有没有要大家做的事。

## 2. 发布前检查

在候选提交上（API、Web、Worker 用同一个提交号）：

1. 合同校验：`server/.venv/bin/python tools/validate_contracts.py`。
2. 受影响的后端测试，以及前端 `pnpm typecheck`、`pnpm lint`、`pnpm build`，按 README“执行检查”。
3. 迁移清单：这次新增了哪些迁移，每个迁移的单步降级是否在隔离库里往返验证过。注意 D260：从 head 一路降到 base 会在 `s0_0784` 失败，所以回滚只按“降到上一版的 head”来验证，不指望整链降级。
4. 工作流兼容检查：见第 3 节。只要动了工作流代码，这一步不通过就不能发。
5. 写好回滚判据（第 5 节），和发版说明一起发出。

## 3. 工作流代码改动必须用 patch

**为什么。** 等待中的工作流（等回答的小Pai运行、每小时一次的重扫和每天一次的清理计时器、钉钉投递重试）在 Worker 换代码后，会用新代码把整段历史重放一遍。新代码给出的命令顺序和历史不一致时，这个工作流就卡在 “Nondeterminism error” 上，后面的工作都不会再做。

**什么算工作流代码。** `server/pdos_next/workflows/worker.py` 里 `registered_workflows()` 列出的 16 个类，以及它们的 `run`、signal、query 方法里决定命令顺序的逻辑。Activity 的实现不算（每次执行都重新读业务事实），但 Activity 的名字、参数和返回结构要保持兼容。

**规则。**
1. 增删或调换 `execute_activity`、`sleep`、`wait_condition`、子工作流、`continue_as_new`，或改变它们的条件，都要放在 `workflow.patched("<改动名-v1>")` 后面：

   ```python
   # 现有例子：server/pdos_next/workflows/xiaopai.py
   if result["status"] == "needs_reconciliation" and workflow.patched("xiaopai-reconciliation-v1"):
       await workflow.sleep(timedelta(minutes=5))
       return await workflow.execute_activity("reconcile_xiaopai_run", ...)
   ```

   旧历史里没有这个标记，重放时 `patched` 返回假，走原来的路；新运行写下标记，走新的路。
2. 不改工作流类型名、工作流 ID 的格式和任务队列名（`pdos-next-domain-v1`）。事件重投靠确定的工作流 ID 防止跑第二次（见备份手册第 3 节）。
3. patch 的三步：加 `patched` → 所有没有标记的旧运行都结束后，改成 `workflow.deprecate_patch("同名")` → 再过一个保留周期后删掉旧分支。每一步单独发版。
4. 工作流改动尽量单独发版，观察期内不叠加其他工作流改动。

**检查办法：回放检查。** `tools/workflow_replay_check.py` 把正在运行的工作流历史导出来，用本检出的 `registered_workflows()` 重放：

```bash
server/.venv/bin/python tools/workflow_replay_check.py check
```

Temporal 地址取 `PDOS_TEMPORAL_ADDRESS` 和 `PDOS_TEMPORAL_NAMESPACE`（本地用 `--local`）。任何一个历史重放失败，或者历史里有新代码已不注册的工作流类型，命令都会以非零退出码结束并列出工作流 ID。也可以先 `export --out 目录` 存下历史，在候选代码上 `replay --from 目录`。导出的历史只含标识和引用，不含模型原文和凭据，文件只有本人可读。

测试 `tools/tests/test_workflow_replay_check.py` 用一个等待中的示例工作流证明：同样的代码通过；不加 patch 插入一步会报 Nondeterminism 失败；同样的改动放在 `patched` 后面通过；历史里的类型没有注册时拦截；以及第 5 节用到的“记下标记后回滚到旧代码会失败”。

## 4. 发布步骤

1. **迁移前快照。** 云上：RDS 手动快照，记下快照 ID 和时间。本地：`server/.venv/bin/python tools/backup_restore.py backup`。快照完成前不做下一步。
2. **停 Worker。** API 进入维护页。给 Worker 进程发 SIGTERM（`docker stop`、`systemctl stop` 都是先发它）。Worker 的停机办法（D348）：
   - 立即停止取新任务，事件投递循环做完当前一轮就停；
   - 正在跑的 Activity 最多再给 `PDOS_WORKER_SHUTDOWN_GRACE_SECONDS` 秒（默认 60，可设 0–3600）跑完；
   - 到时还没跑完的取消掉，再最多等 15 秒；
   - 仍不结束的（卡在数据库或网络调用里）放弃：进程以退出码 3 结束，这些 Activity 由 Temporal 在心跳超时（小Pai运行为 45 秒）或执行超时后重试。Activity 每次都重读业务事实，小Pai运行的核对出口也不会重复推理或外部动作。
   - 停机中再收到 SIGTERM 或 SIGINT 只记一行日志，不会重新开始停机；要立即结束用 SIGKILL。
   - 所以进程管理器给的停止等待时间要大于“宽限秒数 + 15 秒”：`docker stop -t`、compose 的 `stop_grace_period`、systemd 的 `TimeoutStopSec`，否则会在中途被强杀。停机期间指标 `pdos_worker_stopping` 为 1（[监控手册](monitoring-and-on-call.md)第 2.1 节）。
3. **回放检查。** 用候选代码对正在运行的工作流跑第 3 节的检查。不通过就停在这里，Worker 继续跑旧版本。
4. **迁移。** 用迁移账号执行 `alembic upgrade head`，记下前后的 head。
5. **部署新版本。** API、Web、Worker 用同一提交号；部署配置（签发方、模型连接、扫描档）随发布目录一起检查。
6. **冒烟。**
   - `GET /health` 返回正常；
   - 用一个试点账号登录，打开我的工作、一个项目和一个交接页；
   - Worker 已在取任务：探针（[监控手册](monitoring-and-on-call.md)）的 `backlog:pollers:*` 没有告警；
   - Worker 日志里没有 “Nondeterminism” 或工作流任务失败；
   - 探针跑一轮，没有新的严重告警。
7. **观察。** 建议 30 分钟〔你〕，然后在支持群里通知发布完成。

## 5. 回滚

**判据**（满足任一条就回滚，或在发版说明里另写）：登录或主要页面不可用；5xx 比例持续超过阈值；Worker 出现 Nondeterminism；数据写入错误。

**API、Web 回滚**：直接换回上一个发布目录。前提是这次的迁移对上一版代码兼容（只加不删）。

**Worker 回滚**：先用**上一版**代码对当前的运行历史跑一遍回放检查。新代码一旦在历史里记下了 patch 标记，旧代码就无法继续这些工作流（实测报错 “Non-deprecated patch marker encountered … but there is no corresponding change command”）。检查不通过时不能回滚 Worker，只能修复后再发一版；不要用 Temporal reset 把工作流退回去，那会重新执行其中的 Activity。

**迁移回滚**：优先修复后再发一版。确实要降级时，只降这次新增的迁移，并且只在隔离库里往返验证过才做。降级不安全时（例如新迁移之后已经写入了依赖它的数据），从第 4 节第 1 步的快照恢复，按[备份手册](backup-and-restore.md)第 5 节处理，包括启动 Worker 前的外发核对；快照之后的数据要补录。

## 6. 反向代理（D214 余项）

只把 Web（Next.js）暴露在公网。FastAPI、Temporal、数据库、`/ops/metrics` 只在内网监听。Web 的登录限流按 `X-Real-IP` 计数（`web/src/lib/server/sign-in-proxy.ts`），没有时取 `X-Forwarded-For` 最右一跳，所以反向代理必须**覆盖**客户端自带的同名请求头：

```nginx
location / {
    proxy_pass http://127.0.0.1:3000;       # Web 端口随 D210
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr; # 覆盖客户端传入的值
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Nginx 前面如果还有阿里云负载均衡，`$remote_addr` 会变成负载均衡的地址，所有人共用一个限流计数。这种情况下要用 `set_real_ip_from <负载均衡网段>;` 和 `real_ip_header X-Forwarded-For;` 先还原真实来源，再按上面设置。域名、证书和是否有负载均衡随 D210 定。

上线后核对：带伪造 `X-Real-IP` 的请求连续登录失败，限流仍按真实来源计数。

## 7. 发布记录

每次发版留一条记录：日期、提交号、迁移 head（前 → 后）、快照 ID、回放检查结果（历史数、失败数）、冒烟结果、观察期结论、是否回滚。
