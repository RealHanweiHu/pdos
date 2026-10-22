# S5-1 钉钉连接器 v1 契约

日期：2026-08-12  
状态：Local implementation complete; real application gate pending
迁移：`0026_dingtalk_connector` + `0027_dingtalk_hardening`

## 1. 范围与非范围

本项交付同一企业内独立 PDOS 应用的四条纵向能力：

1. 用户通过钉钉 OAuth 授权码登录或显式绑定本地账号，不输入 PDOS 本地密码；
2. HTTP AES 回调完成 URL challenge、审批状态通知与幂等消费；审批事件仅接受官方顶层 `EventType/eventId/processInstanceId` 字段，不递归猜测 ID；
3. PDOS 可发起 Gate 外部审批、向已绑定项目群发送 Markdown 通知；
4. PDOS 可投放带 `outTrackId` 的互动卡片，接收签名回调并做受控确认。

不在 v1 范围：读取私聊/群历史、自动建群、通讯录批量同步、按手机号/姓名自动匹配、日历同步、机器人自由对话、钉钉文件采集、Stream 长连接、以钉钉审批结果直接批准 Gate/Finding/Change、创建钉钉应用或模板、生产回调/DNS/Nginx 变更。

外部审批是“外部协作证据”，不是 PDOS SoR 决策。钉钉显示 approved 后，Gate 仍必须由具备当前权限的人在 PDOS 发起正常审批，并重新检查签核/readiness/风险/任务等数据库真值；远端状态不能绕过既有硬闸。

## 2. 官方协议基线与复用结论

当前协议基线：

- 浏览器 OAuth 使用 `https://login.dingtalk.com/oauth2/auth`，scope 至少为 `openid corpid`；授权码通过 `POST https://api.dingtalk.com/v1.0/oauth2/userAccessToken` 兑换用户凭证，再以该凭证调用 `GET /v1.0/contact/users/me`。钉钉端内的当前文档明确要求使用授权组件，不使用旧 `dd.getAuthCode` 静默授权。
- 应用凭证通过 `POST https://api.dingtalk.com/v1.0/oauth2/accessToken` 获取，v1 API 使用 `x-acs-dingtalk-access-token`。
- 群通知使用 `POST /v1.0/robot/groupMessages/send`，请求体包含 `robotCode/openConversationId/msgKey/msgParam`，其中 `msgParam` 是 JSON 字符串。
- 外部审批使用 `POST /v1.0/workflow/processInstances`；interactive card 使用 `POST /v1.0/card/instances/createAndDeliver`，`outTrackId` 是本地幂等/对账键。
- HTTP 事件回调使用 Token + EncodingAESKey；请求签名为 Token/timestamp/nonce/encrypt 排序后 SHA-1，消息为 AES-256-CBC + PKCS#7，响应必须返回加密的 `success`。

参考链接：

- <https://opensource.dingtalk.com/developerpedia/docs/develop/permission/token/browser/get_user_app_token_browser/>
- <https://opensource.dingtalk.com/developerpedia/docs/develop/permission/token/jsapi/get_user_app_token_jsapi/>
- <https://opensource.dingtalk.com/developerpedia/docs/learn/stream/protocol/>
- <https://opensource.dingtalk.com/developerpedia/docs/explore/tutorials/stream/bot/go/card-callback/>
- <https://open.dingtalk.com/document/orgapp/the-robot-sends-a-group-message>
- <https://open.dingtalk.com/document/orgapp/create-an-approval-instance>

老 CEHub 可复用的是协议形状、token 提前刷新、`outTrackId`、外部 create 结果不确定时隔离而非盲重放、卡片失败降级通知的经验。以下做法不复制：手机号反查/姓名匹配、未校验时间窗的回调、递归从任意 payload 找 ID、未验证 AES 尾部 CorpID、把远端 approved 当作本地业务批准、对不确定 create 自动补发。

## 3. 数据合同

`0026` 只增加以下实体，不修改既有业务状态机；`0027` 追加 `agent_id` 纯十进制正整数约束，既有迁移不可变：

### `cehub_core.dingtalk_tenant_bindings`

- `tenant_id` 主键；`corp_id` 全局唯一，避免同一企业落到多个租户；
- 非秘密配置：`client_id`、纯十进制正整数 `agent_id`、`robot_code`、`oauth_redirect_uri`、`callback_route_key`、`approval_process_code`、`card_template_id`、`card_callback_route_key`；
- `status = disabled|active`；凭证、callback token/AES key/card secret 永不入库。

### `cehub_core.dingtalk_user_bindings`

- `tenant_id + user_id` 唯一；`tenant_id + corp_id + open_id` 唯一；
- 保存由钉钉签发并经 OAuth 验证的 `open_id`、组织成员 `staff_id`，可选 `union_id`；`staff_id` 仅用于需要 userid 的审批/卡片接口，禁止把 openId 猜作 userid；不保存用户 access token、refresh token、手机号、昵称或头像；
- 只允许用户通过已登录会话显式自绑定，或 Owner/Admin 解除绑定；禁止客户端直接提交外部 ID 绑定另一个用户。

### `cehub_core.dingtalk_oauth_states`

- 只保存随机 state 的 SHA-256、tenant、可选 link user、mode、相对 return path、过期时间、consumed_at；
- state 至少 256 bit、5 分钟有效、一次性消费；原始 state 不落库。

### `cehub_project.dingtalk_project_channels`

- `tenant_id + project_id` 唯一，保存经人工配置的 `open_conversation_id` 与显示名；
- 只有 Owner/Admin/Project Manager 可绑定；项目和租户范围由服务端复核。

### `cehub_event.integration_outbox`

- `tenant_id/project_id`、`provider=dingtalk`、`operation`、`idempotency_key`、有界 allowlist payload、状态、attempt、next_attempt_at、lease、remote_reference、last_error；
- 状态：`pending→sending→succeeded|retry_wait|failed|uncertain|manual`；同 provider+operation+idempotency 唯一；
- operation v1：`group_markdown`、`gate_approval_create`、`interactive_card_create`、`interactive_card_update`。

### `cehub_event.integration_receipts`

- 保存 callback channel、外部 message/event ID（若有）、ciphertext/body SHA-256、received/processed 时间、结果；不保存原始回调、用户 token、手机号或完整表单；
- 同 tenant+channel+external ID 唯一；同一 ID 异摘要 fail-close，同摘要重放返回成功 ACK 且零二次业务动作。

### `cehub_project.dingtalk_approval_instances` / `dingtalk_interactive_cards`

- Approval 仅支持 `business_type=gate_review`，绑定 tenant/project/gate、originator/approver 本地用户和远端 instance ID；状态 `queued|creating|pending|approved|rejected|terminated|sync_failed|uncertain|manual`。
- Card 绑定 tenant/project/outTrackId/recipient 或 project channel、server-built action、状态 `queued|creating|sent|acknowledged|handled|failed|uncertain|manual`；卡片参数不得包含任意客户端 URL/HTML/secret。

所有 tenant/project/user/gate 关联均为复合外键；新增表进入 metadata、迁移往返、初始 schema、数据库安全/生产权限清单。

## 4. 配置与秘密

服务器环境变量：

- `PDOS_DINGTALK_CLIENT_ID`
- `PDOS_DINGTALK_CLIENT_SECRET`
- `PDOS_DINGTALK_CALLBACK_TOKEN`
- `PDOS_DINGTALK_CALLBACK_AES_KEY`
- `PDOS_DINGTALK_CARD_CALLBACK_SECRET`
- `PDOS_PUBLIC_BASE_URL`
- `PDOS_DINGTALK_DELIVERY_ENABLED=false`（默认关闭）

非秘密 tenant/app 配置通过 Owner/Admin API 写数据库，env 凭证与该 binding 的 `client_id` 必须一致，`oauth_redirect_uri` 必须精确等于 `${PDOS_PUBLIC_BASE_URL}/dingtalk/callback`。应用 token 在进程内复用并于到期前 5 分钟刷新。应用只允许访问固定主机 `login.dingtalk.com`、`api.dingtalk.com`；不接受客户端 base URL，不跟随 redirect，不继承系统代理。真实 secret 不出现在响应、日志、Event/Audit、outbox 或测试 fixture。

## 5. OAuth 与身份绑定

### API

- `POST /api/integrations/dingtalk/oauth/login/start`：公开、有登录限流；输入 tenant slug + 有界相对 return path，返回官方 authorization URL。
- `POST /api/integrations/dingtalk/oauth/link/start`：需要当前内部用户会话；建立 `mode=link` state。
- 公网 OAuth redirect 固定为 `/dingtalk/callback`；该页面把一次性 `authCode + state` 提交给同源 session BFF，后者再调用内部 `POST /api/integrations/dingtalk/oauth/callback`，输出短期 PDOS access token 与 link/login 结果。
- `DELETE /api/integrations/dingtalk/me/binding`：当前用户解除自绑定；Owner/Admin 可通过管理 API解除本租户用户绑定。

### 强制规则

1. state 必须未过期、未消费、摘要匹配；开始远端交换前原子消费，失败后重新开始流程，不复用 state。
2. 用户 token 响应的 `corpId` 必须与 state tenant 的 active binding 相同。
3. `/contact/users/me` 必须返回非空 `openId` 与成员 `userId/staffId`；link 模式只能绑定 state 中的本地 user；login 模式只能命中已有 active binding。
4. unionId/mobile/nick/email 不能作为自动匹配依据；未绑定返回 `DINGTALK_IDENTITY_NOT_LINKED`，不自动创建用户。
5. 本地 user/tenant 必须仍 active；成功登录复用现有 TokenCodec，并落 `USER_SIGNED_IN` + Audit，`authentication_method=dingtalk_oauth`。

## 6. HTTP AES 与卡片回调

### 事件回调

公网 `POST /api/integrations/dingtalk/callback/{route_key}?signature=&timestamp=&nonce=` 由无会话、严格 allowlist 的同源边缘路由转发到同路径 FastAPI，只接受 `{encrypt}`：

1. route key 唯一解析 active tenant；timestamp 必须在服务器时间 ±5 分钟；nonce 1–128 字符；ciphertext 有界；
2. 常量时间比较签名，AES key 必须解码为 32 bytes，严格验证 PKCS#7、4-byte 长度、JSON object 和解密尾部 CorpID；
3. `check_url` 只返回加密 `success`；未知事件加密 ACK、无副作用；审批事件只从固定字段读取 processInstanceId，不递归扫描任意 payload；
4. 审批状态不信任回调 payload，worker 用远端 instance ID 拉取当前状态后更新本地镜像；本地 Gate 不随之改变。

### 卡片回调

公网 `POST /api/integrations/dingtalk/card-callback/{route_key}` 同样由无会话、仅转发两项签名 header 的边缘路由进入 FastAPI，要求 `x-ddpaas-signature-timestamp` 与 HMAC-SHA256 签名，时间窗同样为 ±5 分钟。创建卡片显式声明 `callbackType=HTTP`；回调仅从官方固定字段 `corpId/userId/outTrackId/content.cardPrivateData.params.action` 读取，`userId` 按创建时的 `userIdType=1` 与本地 `staff_id` 匹配，禁止递归扫描或猜成 openId。v1 action 只有 `acknowledge` 和 server-built `open`，均不能直接审批或 Apply 业务对象。

两类回调均先认证、再幂等占位、再处理；重放返回成功但不重复写 Event/Audit。摘要冲突、签名错误、过期时间、错误 CorpID、未知 outTrackId/user/action 均 4xx fail-close。

## 7. 审批、通知、卡片与可靠性

- Gate external approval 只能由 Owner/Admin/Project Manager 对自己可管理的项目发起；originator/approvers 必须是 active 项目内部成员且已有钉钉 binding。请求体中的用户 UUID 只是选择器，外部 userid/openId 由服务端查表。
- 表单由服务端从 Project/Gate/readiness 预聚合生成，客户端不能传自由表单；不得包含文档原文、对象键、Customer PII 或 secret。
- 群通知只能发送到本项目已绑定 channel；title/text 长度受限，链接只能由 `PDOS_PUBLIC_BASE_URL` + server-built relative path 生成。
- token 获取失败、明确 429/5xx 且请求尚未发出可指数退避；审批/群消息/卡片 create 在请求发出后遇超时、连接中断、408/429/5xx 或缺 remote ID 时标记 `uncertain`，不自动补发。
- `outTrackId`、approval request ID、outbox idempotency key 均由服务器生成并稳定复用；人工 replay 必须二次确认，uncertain 先对账后决定。
- 未配置或 `PDOS_DINGTALK_DELIVERY_ENABLED=false` 时，业务写不失败：outbox 进入 `manual` 并给出 PDOS 深链/操作说明；不把外部失能伪装成 delivered。

## 8. 事件、审计与可观测性

新增注册事件：

- `DINGTALK_IDENTITY_LINKED`（security_audit）
- `DINGTALK_APPROVAL_UPDATED`（integration_projection/timeline_projection）
- `DINGTALK_NOTIFICATION_DELIVERED`（integration_projection）
- `DINGTALK_CARD_ACTION_RECEIVED`（integration_projection/security_audit）

身份绑定/解绑、integration 配置、channel 绑定、outbox 人工 replay、审批镜像变化、卡片 acknowledge 均落不可变 Audit。指标至少覆盖 pending/retry/failed/uncertain/manual 数、callback invalid/replay 数、token refresh failure、投递 latency；日志只含本地 UUID、operation、状态和脱敏错误码。

## 9. RBAC

- Owner/Admin：管理 tenant integration、解除用户绑定、绑定项目 channel、查看/replay outbox；
- Project Manager：绑定自己可管理项目的 channel、发 Gate approval/通知/卡片；
- Engineer/Quality：可显式自绑定和查看本项目投递状态，不可改 tenant/channel 或发审批；
- Supplier/Customer：无钉钉 integration 管理、绑定、通知或审批面。

回调处理不继承外部声称角色。卡片 action 通过 external identity 映射回 active 本地用户，再以当前 RBAC/项目成员关系复核。

## 10. 验收

1. migration `0026→0025→0026`、metadata drift、初始 schema、单一 head 全绿；存在不可逆远端/审计记录时 downgrade fail-close。
2. fake DingTalk server 证明 app/user token、OAuth link/login、corp mismatch、unlinked/inactive/cross-tenant、state expiry/replay、无 token 泄漏。
3. 固定 AES 向量证明 challenge round-trip、签名/时间窗/nonce/PKCS#7/message length/tail CorpID；同 ID 同摘要重放 1 次处理，异摘要拒绝。
4. Gate approval、群通知与 interactive card 走 outbox；成功、确定失败、token 失败退避、远端结果 uncertain、人工降级、replay/对账均有测试。
5. remote approval approved 后 Gate 状态不变；正常 PDOS Gate 审批仍重新检查 readiness/签核/RBAC。
6. 真实浏览器仅连 `pdos_test`：本地密码登录→显式 link fake provider→退出→钉钉 OAuth 登录→项目 integration 状态/投递记录可见；外部角色零入口/零请求，console 0 warning/error，390px 无横向溢出。
7. 完整 server/web tests、Ruff/format/mypy/compile、ESLint/TypeScript/build 全绿；无真实钉钉凭据仍可启动且 delivery 明确 manual。
8. 真实钉钉应用 smoke 是独立人工 Gate：人创建独立应用、配置权限/redirect/AES callback/card template/审批模板/机器人和测试群后，完成 1 次免密登录、1 次群通知、1 次 Gate 外部审批回调、1 次卡片 acknowledge。未经单独授权不得执行。

## 11. 回滚

应用回滚关闭 `PDOS_DINGTALK_DELIVERY_ENABLED`，停止新 outbound，保留绑定/outbox/receipt/approval/card 审计和站内人工路径。生产不执行 migration downgrade；回调/应用下线由人先在钉钉后台解绑，再切镜像。删除应用前必须先将所有 `pending/sending/retry_wait/uncertain` 项清零或转 `manual`。
