# S5-1 钉钉连接器发布就绪报告

- 日期：2026-08-13
- 分支：`codex/sprint-5`
- 范围：S5-1 独立钉钉企业内部应用连接器；不包含 S5-2 ERP Handoff

当前判定：**本地候选就绪；真实应用与生产变更 NO-GO**

## 1. 判定摘要

S5-1 本地实现、迁移、数据库权限、fake provider、真实 Chromium、生产镜像和公网回调边缘合同已完成。候选版本具备 fail-close 配置校验、`delivery=false` 默认开关、durable outbox、明确的不确定状态、只读 readiness/Exit Evidence 检查以及不降级数据库的回滚路径。

当前不得勾选 canonical S5-1，也不得进入 S5-2。尚缺的都是必须由人持有的真实应用门禁：独立应用与最小权限、真实回调/模板/测试群、生产秘密、租户 binding、真实用户和外部可达性验证，以及本次生产操作的明确授权。

本报告不包含任何钉钉 secret、用户 token、手机号、昵称或真实回调 route key。

## 2. 已冻结的自动化证据

| 门禁 | 结果 | 证据 |
|---|---|---|
| Production compose smoke | PASS | 隔离 `pdos_test` 升级到 `0027`，重施加 Agent 最小权限；API、dispatcher、executor、DingTalk worker、Web 均 healthy |
| 容器权限 | PASS | API/dispatcher/executor/DingTalk worker UID=`10001`，Web UID=`1001` |
| 公网回调应用链 | PASS | 无会话 AES callback 经 Next BFF 到 FastAPI；不存在的 route 返回 `404 DINGTALK_CALLBACK_ROUTE_UNKNOWN`，零回执写入、零外部调用 |
| Web tests | PASS | 35 files / 121 tests |
| Server tests | PASS | 357 tests |
| Lint / format | PASS | ESLint、Ruff、Ruff format |
| Static types | PASS | TypeScript；mypy 203 source files |
| Production build | PASS | Next.js production build 生成 OAuth、AES callback、card callback 与 integration routes；Python compileall 通过 |
| 部署合同 | PASS | 15 tests；部署后公网 callback edge 探针成为硬门禁，Exit Evidence CLI 进入非 root API 镜像 |
| Exit Evidence 合同 | PASS | PostgreSQL read-only transaction；完整 SHA + 防篡改 Gate 基线；登录、三类 delivery、审批镜像/Gate 不变、回调、卡片幂等与 outbox 对账 fail-close |

以上执行只接触本机 `pdos_test`、本机候选容器和只读本地文件；未连接生产 RDS，未修改钉钉、Nginx、DNS 或生产服务。

## 3. GO 前置条件

以下条件必须全部有可核对证据，任何一项缺失均保持 NO-GO：

- 独立企业内部应用已创建，`corp_id/client_id/agent_id` 与最小权限已由人核对；不得复用 CEHub 应用或回调命名空间。
- OAuth redirect 精确为 `https://pdos.beepump.net/dingtalk/callback`。
- AES event callback、机器人与测试群、审批模板、interactive card template/card callback 已配置；event 和 card 使用不同的高熵 route key。
- ECS mode `0600` 的 `.env.production` 已写入 client secret、callback token、43 字符 EncodingAESKey、card HMAC secret；`PDOS_PUBLIC_BASE_URL=https://pdos.beepump.net` 且初始 `PDOS_DINGTALK_DELIVERY_ENABLED=false`。
- Owner/Admin 已写入唯一 tenant binding；至少 2 个 active 内部用户显式绑定，至少 1 个项目群已配置；禁止姓名或手机号自动匹配。
- 生产 release 已冻结为完整 Git SHA，Git bundle、HEAD、OCI revision 与 image tag 四者一致。
- 人对该完整 SHA、目标 tenant slug、`0027` migration、`delivery=false` 部署和真实应用 smoke 给出本次明确授权。

## 4. 分阶段上线与停止条件

### Stage A — delivery disabled

1. 从已验证 Git bundle 建立全新 release 目录；运行 `scripts/deploy-ecs.sh preflight` 与 `build`。
2. 保持 `PDOS_DINGTALK_DELIVERY_ENABLED=false`，执行 `0027` migration，重施加 `scripts.apply_agent_runtime_security`。
3. 启动 API/Web/dispatcher/executor/DingTalk worker。部署脚本必须同时通过 session、login、公网 AES callback edge 与 bounded-log 检查。
4. 运行只读检查：

   ```bash
   cd /app/server
   python -m scripts.check_dingtalk_readiness --tenant-slug <tenant-slug>
   ```

出现 schema/env/binding/crypto/user/channel/outbox 任一 FAIL，立即停止；不得以临时跳过或直接打开 delivery 继续。

5. 按运行手册 §4.1 捕获完整 release SHA + tenant/project + Gate 真值哈希基线。证据文件必须在 release worktree 外以 mode `0600` 保存；捕获后不得覆盖。

### Stage B — 真实 inbound / identity smoke

1. 已绑定用户 password-free login 成功一次；未绑定用户、错 corp、state replay 分别拒绝。
2. AES challenge/event 回调成功；错签名、过期时间、错 corp 和重放符合预期。

任何外部身份自动匹配、回调二次处理、secret/用户 token 出现在响应或日志，均为立即回滚条件。

### Stage C — outbound canary

Stage B 通过后仍需单独批准 `delivery=true`。批准后：

1. 先运行 `check_dingtalk_readiness --require-delivery-enabled`。
2. 只对一个测试项目群发送一条通知，确认 outbox=`succeeded` 且 remote reference 可查。
3. 发起一条测试 external approval 并完成回调；确认只更新外部镜像，PDOS Gate 真值不变。
4. 发送一张测试 card 并 `acknowledge`，重放相同回调；核对本地/远端 reference、唯一 receipt/Event/Audit footprint。
5. 按运行手册 §4.1 对不可覆盖的基线运行 Exit Evidence verify，保存 PASS/FAIL 与 `HUMAN_REQUIRED` 输出。
6. 观察 bounded logs 与 outbox；`failed/uncertain/manual` 任一非预期增长即关闭 delivery，不盲重放。

Gate 被外部审批直接改变、证据基线摘要/SHA/scope 不匹配、delivery/Event/Audit/receipt 缺失或重复，均为立即回滚条件。

## 5. 回滚与恢复

1. 首个动作是恢复 `PDOS_DINGTALK_DELIVERY_ENABLED=false` 并滚动 API/DingTalk worker，使新 intent 显式进入 `manual`。
2. 对 `pending/sending/retry_wait/uncertain/manual` 逐项对账；`uncertain` 未经远端查证不得 replay。
3. 应用回滚只切换到已经验证且 OCI revision 匹配的旧 SHA；不运行 migration downgrade，不删除 integration 表或审计记录。
4. 公网 callback edge、登录、容器健康或 bounded logs 任一复验失败，release 保持 NO-GO。

## 6. 人工 Exit Gate 记录位

- [ ] 独立应用与最小权限配置核对通过
- [ ] Stage A production preflight/deploy/readiness 通过
- [ ] password-free login 正反向 smoke 通过
- [ ] 项目群通知与 remote reference 对账通过
- [ ] external approval 仅镜像、Gate 真值不变
- [ ] card acknowledge 与 replay/伪造正反向 smoke 通过
- [ ] Exit Evidence 自动项全 PASS，baseline/verify 原件由操作者和 Data Owner 留存
- [ ] 浏览器 console 0 warning/error、390px 无横向溢出、Supplier/Customer 无入口且 API=403
- [ ] 人工确认 S5-1 Exit Gate

最后一项确认后，才更新 canonical S5-1 checkbox 和 `tasks/todo.md` 指针到 S5-2。
