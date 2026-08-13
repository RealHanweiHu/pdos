# S5-1 钉钉连接器运行手册

日期：2026-08-12
适用范围：PDOS 独立企业内部应用；不复用 CEHub 的应用、回调命名空间或机器人。

## 1. 默认状态与所有权

- 默认 `PDOS_DINGTALK_DELIVERY_ENABLED=false`。OAuth/AES/card 配置缺失时 API 仍可启动，outbox 明确进入 `manual`，不会伪装为 delivered。
- 创建钉钉应用、审批模板、卡片模板、机器人、测试群，以及修改回调、Nginx、DNS、生产环境变量均由人执行；每次生产变更需要单独明确授权。
- 钉钉审批仅是 external evidence。即使远端显示 approved，PDOS Gate 也不改变；本地审批仍走原 Gate RBAC、readiness 和签核硬闸。
- `pdos_agent` 与 `pdos_worker` 不参与本连接器写入。API 与 `dingtalk` worker 使用 `pdos_app`，新增表在 Agent 安全脚本重施加后对 Agent 仍为零写权限。

## 2. 人工创建应用检查表

1. 新建企业内部应用，记录 `client_id`、`client_secret`、`corp_id`、`agent_id`。
2. 配置浏览器 OAuth redirect：`https://pdos.beepump.net/api/integrations/dingtalk/oauth/callback`。
3. 配置事件回调：`https://pdos.beepump.net/api/integrations/dingtalk/callback/<独立 route key>`，生成独立 Token 和 EncodingAESKey。
4. 配置机器人和测试群，记录 `robot_code` 与 `open_conversation_id`。
5. 新建 Gate external approval 模板，记录 process code；模板字段固定为 `Project`、`Gate`、`PDOS status`。
6. 新建 interactive card 模板，配置独立 callback route key 和 HMAC secret；只允许 `acknowledge` 与 server-built `open`。
7. 权限按最小集合逐项申请。OAuth 当前使用授权码换用户 token，再读取 `/v1.0/contact/users/me`；返回的 `openId` 与组织 `userId/staffId` 分开保存，不作相互猜测。

## 3. 服务器秘密与非秘密配置

秘密仅放 ECS mode `0600` 的生产环境文件：

```text
PDOS_DINGTALK_CLIENT_ID=<app client id>
PDOS_DINGTALK_CLIENT_SECRET=<app client secret>
PDOS_DINGTALK_CALLBACK_TOKEN=<event callback token>
PDOS_DINGTALK_CALLBACK_AES_KEY=<43-char encoding AES key>
PDOS_DINGTALK_CARD_CALLBACK_SECRET=<card HMAC secret>
PDOS_PUBLIC_BASE_URL=https://pdos.beepump.net
PDOS_DINGTALK_DELIVERY_ENABLED=false
PDOS_DINGTALK_POLL_SECONDS=2
```

租户 `corp_id/client_id/agent_id/robot_code/redirect/route key/process code/card template` 由 Owner/Admin 通过 PDOS 配置 API 写入。secret、用户 token、手机号、昵称不得写数据库、outbox、Event/Audit 或日志。

## 4. 上线顺序

1. 保持 delivery disabled，执行生产 preflight、镜像构建、`alembic upgrade head`。
2. 重施加 `python -m scripts.apply_agent_runtime_security`，确认 `pdos_agent` 对业务及新 integration 表零写。
3. 启动 `api/web/dispatcher/executor/dingtalk`；检查 `/healthz`、登录和 integration status。
4. Owner/Admin 写 tenant binding，Project Manager 写 project channel；内部用户逐个显式 link，不允许手机号/姓名自动匹配。
5. 用 fake/测试应用先完成 OAuth、AES challenge、群通知、审批、卡片 smoke。
6. 人核对 pending/retry/failed/uncertain/manual 均为预期后，再单独授权将 delivery 改为 true 并滚动启动 API 与 dingtalk worker。

## 5. 监控与对账

状态计数（只读）：

```sql
SELECT status, count(*)
FROM cehub_event.integration_outbox
WHERE provider = 'dingtalk'
GROUP BY status
ORDER BY status;
```

需人工处理：

```sql
SELECT id, tenant_id, project_id, operation, status, attempt_count,
       last_error_code, created_at, updated_at
FROM cehub_event.integration_outbox
WHERE provider = 'dingtalk'
  AND status IN ('failed', 'uncertain', 'manual')
ORDER BY created_at;
```

- `retry_wait`：仅代表 token 阶段或明确未发出请求的可重试错误。
- `uncertain`：请求可能已送达，或发送中 worker lease 过期；绝不直接 replay。先在钉钉后台按 requestId/outTrackId/时间窗查证，再由 Owner/Admin 调 reconcile。
- `confirmed_delivered` 必须录入远端 reference；`confirmed_not_delivered` 转 failed 后，才可带 `REPLAY_CONFIRMED` 人工重放。
- 回调 invalid/replay、token failure 和 latency 以结构化日志、本地 receipt/audit 计数监控；日志只记录本地 UUID、operation、status、error code。

## 6. 降级与回滚

1. 先设 `PDOS_DINGTALK_DELIVERY_ENABLED=false` 并滚动 API/dingtalk worker；新 intent 进入 manual。
2. 不执行生产 migration downgrade，不删除 binding/outbox/receipt/approval/card 记录。
3. 对 `pending/sending/retry_wait/uncertain` 逐项对账，清零或人工转入受控路径；不得批量盲重放。
4. 应用镜像回滚可保留新 schema；旧镜像不运行旧 migrator。
5. 只有在人确认审计保留策略、所有待处理项清零后，才可在钉钉后台解绑回调或删除独立应用。

## 7. 真实应用 Exit Gate（人工）

- 1 次已绑定用户 password-free login；未绑定、错 corp、state replay 均拒绝。
- 1 次项目群通知可达，PDOS outbox succeeded 且 remote reference 可查。
- 1 次 Gate external approval 回调后镜像更新，PDOS Gate 状态保持原值。
- 1 次 card acknowledge，重复回调只处理一次；错签名、过期时间、错 corp/openId/outTrackId 均拒绝。
- 浏览器 console 0 error/warning，390px 无横向溢出；Supplier/Customer 无 integration 入口且 API 返回 403。
