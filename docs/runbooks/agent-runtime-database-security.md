# Agent 运行时数据库安全边界

本手册是 S2-2b 的生产 DBA 交接材料。它只描述一次性人工操作；自动化和编码 Agent 不得创建生产账号、设置密码或执行这些 SQL。

## 1. 边界与职责

- `pdos_worker`：只读 `cehub_event.events`，管理 dispatcher cursor、subscription 和 run 控制记录；没有业务表写权限。
- `pdos_agent`：只读由当前 run lease 绑定的租户/项目投影视图，通过受控函数推进 run，并写当前 run 范围内的不可变 `model_invocations`；没有业务表写权限。
- `pdos_app`：FastAPI 的业务角色。Finding 被人接受后，只有它可以在二次鉴权和数据库真值复核后应用业务变更。
- executor 环境只能出现 `PDOS_AGENT_DATABASE_URL`；不得出现 `DATABASE_URL` 或 `PDOS_WORKER_DATABASE_URL`。dispatcher 只能出现 `PDOS_WORKER_DATABASE_URL`，且不接收模型凭据。

## 2. 上线前置条件

1. 由应用发布流程先执行 `alembic upgrade head`。
2. RDS 管理员确认连接的是目标 PDOS 数据库，执行登录角色模板；再由 `pdos_app`（schema owner）执行权限对象模板。
3. 在密码管理系统中分别生成两个高熵密码；不要把密码写进仓库、shell history 或 SQL 模板。
4. 维护窗口内暂停 dispatcher/executor；FastAPI 可保持运行。

## 3. DBA 执行

RDS 管理员先执行角色模板；同一版本连续执行两次必须均成功：

```bash
psql "$PDOS_ADMIN_DATABASE_URL" --set=ON_ERROR_STOP=1 \
  --file infra/postgres/security/agent-runtime-roles.sql
psql "$PDOS_ADMIN_DATABASE_URL" --set=ON_ERROR_STOP=1 \
  --file infra/postgres/security/agent-runtime-roles.sql
```

然后在管理员独立会话中设置密码（以下占位符必须由 DBA 的安全凭据流程替换）：

```sql
ALTER ROLE pdos_worker PASSWORD '<secret-from-vault>';
ALTER ROLE pdos_agent PASSWORD '<different-secret-from-vault>';
```

最后由 `pdos_app`（schema owner）执行幂等权限对象模板；同一版本连续执行两次必须均成功：

```bash
psql "$PDOS_APP_DATABASE_URL" --set=ON_ERROR_STOP=1 \
  --file infra/postgres/security/agent-runtime.sql
psql "$PDOS_APP_DATABASE_URL" --set=ON_ERROR_STOP=1 \
  --file infra/postgres/security/agent-runtime.sql
```

将两个角色的 DSN 分别注入 `PDOS_WORKER_DATABASE_URL` 与 `PDOS_AGENT_DATABASE_URL`。不要给 executor 注入应用 DSN。运行 `make production-preflight` 后再启动服务。

## 4. 必须验证的证据

在临时事务中分别连接两个角色，验证允许路径和拒绝路径；最后回滚事务，不留下测试数据。

```sql
SELECT current_user;
SELECT has_table_privilege('pdos_worker', 'cehub_event.events', 'SELECT');
SELECT has_table_privilege('pdos_worker', 'cehub_project.projects', 'UPDATE');
SELECT has_table_privilege('pdos_agent', 'cehub_project.projects', 'SELECT');
SELECT has_table_privilege('pdos_agent', 'cehub_project.risks', 'INSERT');
SELECT has_table_privilege('pdos_agent', 'cehub_ai.model_invocations', 'INSERT');
```

期望：worker 的 event SELECT 为 `true`；agent 的 model invocation INSERT 为 `true`；三个业务表权限查询均为 `false`。此外必须确认：

- 未绑定有效 run lease 时，所有 `cehub_ai.agent_*_projection` 返回 0 行。
- 使用有效 lease 时只返回该 run 的 tenant/project；手工伪造 `pdos.tenant_id` 后仍返回 0 行。
- worker 对任一业务表 INSERT/UPDATE/DELETE 均收到 permission denied。
- agent 对业务表读写、跨租户 invocation 和直接 UPDATE `agent_runs` 均收到 permission denied。
- 注入文档只能影响模型文本，不能改变数据库授权结果。

仓库 CI 在隔离的 `pdos_test` 上执行同一模板、真实受限角色完整链路和上述正反向测试。生产验收需保存 DBA 执行日志、权限查询结果及服务启动日志，但不得保存 DSN 或密码。

## 5. 回滚

优先回滚应用镜像并保持 dispatcher/executor 停止。若权限对象本身导致故障，由 DBA 执行：

```bash
psql "$PDOS_APP_DATABASE_URL" --set=ON_ERROR_STOP=1 \
  --file infra/postgres/security/agent-runtime-revert.sql
```

回滚模板会移除投影视图、受控函数和角色授权，但不会删除登录角色或修改其密码。恢复运行前必须重新执行当前发布版本的正式模板并完整复验；不得临时把 `pdos_app` 凭据交给 executor 绕过故障。
