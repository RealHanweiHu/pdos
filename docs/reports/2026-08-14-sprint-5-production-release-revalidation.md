# Sprint 5 生产 release 复验与全量 dry-run 证据

日期：2026-08-14
结论：Data Owner 已绑定最终 release 与全部只读证据；生产已部署到 migration 0030 并通过服务器端驾驶舱读路径和 10 分钟观察。CEHub apply 未执行，S5-1 真实钉钉外发继续保持延期且 `delivery=false`。

## 1. 固定身份

- PR #6 已合并，最终 release SHA：`82de9d215c5b0101aaba8cbff2d1adf6d751ceef`。
- release bundle SHA-256：`d32ae10499db8d6352749983350c8bd8f50301b4bf6bd5acad84fc2846d2aa24`。
- inventory fingerprint：`a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d`。
- source fingerprint：`d3d903b6bfa05958678b00502e565f0629d34d634242c8adb49c5a6f06d56b54`。
- 有序源项目：`WqWcl0wK`、`aBnbEdQG`、`xY8-PGbc`、`zGpNH0Xq`。
- 目标 tenant：`e340c240-d8f0-429c-aac5-69ab9b42fac5`。
- migration actor：`4bdba865-c5b1-4ca1-aa85-be467e1fad42`。

## 2. CEHub 稳定只读归档门禁

- 原 `/opt/ce-project-hub/.env` 已备份到
  `/opt/ce-project-hub/.env.backup-before-scheduler-quiesce-20260814T082419Z`；
  备份 owner/mode 为 `root:root 0600`，SHA-256 为
  `bc0ae47d266737e9e9ff0a7a57aff1da4b3b7ebd813eb4fd4a29ecd7ac1725a4`。
- 当前私有环境精确设置 `ACTIVITY_LOG_TAILER_ENABLED=false` 和
  `AUTOMATION_SCAN_INTERVAL_MIN=35790`。
- 仅以同一旧镜像
  `sha256:266a6c8cfc4ee8e695b57b31e640ecd52f5a19c55120132d972ffc187bb4c1bc`
  强制重建 app；没有构建或部署 CEHub 新镜像。
- 安全探针证明默认事务与当前事务均为只读、Project 数为 4、零行永久表写被
  SQLSTATE `25006` 拒绝且未分配 XID。
- 从 `2026-08-14T08:26:47Z` 起连续观察至少 35 分钟；第 35 次检查仍为
  running、restart=0、HTTP 200。观察窗口内 scheduled scanner、activity-log
  tailer、read-only transaction 和 `25006` 日志模式计数均为 0。

## 3. 最终 release 候选

- ECS 从已验证 bundle 建立全新 release 与 verification 目录；HEAD 精确等于最终 SHA。
- `deploy-ecs.sh build` 只构建 API/Web 并执行环境预检，没有运行 deploy。
- API image：
  `sha256:9c4a1dc084b886cbd2c38b5cb94e48e6dd90bc7544de72217ea7e57d1f06fe95`。
- Web image：
  `sha256:d0a0301a914e707e3f6a94bac7fd97b182af487b43333a8028ffeb41b7d70ba2`。
- 两个 OCI revision label 均精确等于最终 release SHA，候选运行容器数为 0。
- 最终候选以强制只读连接执行完整 Project list/API response readiness：
  `Project readiness passed for 2 Projects; no state was changed`。
  这证明导入 Project 的 nullable Development Case 修复可解决当前驾驶舱 500。

## 4. Inventory verify 与全量 dry-run

- Inventory verify：`status=ready`、`errors=[]`、4 active / 0 archived，
  actual/expected ID 顺序与获批清单完全一致。
- Dry-run：`status=ready`、`errors=[]`、`target_writes=0`。
- source counts：User 6、Project 4、Task 117、Gate Review 0、File Reference 14。
- predicted created：User 1、Project 2、Task 64、Gate Review 0、File Reference 4。
- predicted skipped：User 5、Project 2、Task 53、Gate Review 0、File Reference 10。
- 每一类均满足 `created + skipped = source`。

报告目录：
`/opt/pdos-migration-reports/82de9d215c5b0101aaba8cbff2d1adf6d751ceef/cutover`

- inventory verify 报告 SHA-256：
  `30bd71ed7253b8865d3bf3d34a1dbc4bc270043c20c7a4d221ef5aa49204c66f`。
- dry-run 报告 SHA-256：
  `e61a55eed12222562a27136b64be053a2714f5c28432f013a180dfe8ace2029b`。
- 目标库前后快照逐字节一致，SHA-256 均为
  `d02fd41fe4a70c4ac2c4bc9a3715543f63a50a25a30431cfceed7bafb3317a4e`。

## 5. 获批生产部署

- Data Owner 明确批准本报告固定的 release、inventory/source fingerprint、有序项目、
  tenant、actor 与五类 source/created/skipped 计数；发布 Owner 单独授权 deploy 到
  migration 0030，并明确禁止本次 CEHub apply。
- 部署前再次核验报告哈希、目标前后快照、候选 OCI revision 与回滚镜像；旧生产基线为
  release `a34c7eb06aaba036bef8c257c30a841c1ec6be0d`、Alembic
  `0027_dingtalk_hardening`，五容器全部 healthy，候选运行数为 0。
- `deploy-ecs.sh preflight` 再次通过环境、镜像与 2 个现有 Project 的只读 readiness；
  输出明确为 `no state was changed`。
- canonical deploy 依次完成 `0028_erp_handoff_executor`、`0029_crm_entities`、
  `0030_phase_three_agents`，随后重新应用并验证生产 Agent 数据库运行时安全边界。
- API、dispatcher、executor、DingTalk 与 Web 全部切换到 release
  `82de9d215c5b0101aaba8cbff2d1adf6d751ceef` 并健康；独立复核 Alembic 为
  `0030_phase_three_agents (head)`。
- 生产安全开关保持 `PDOS_DINGTALK_DELIVERY_ENABLED=false`，公网基址保持
  `https://pdos.beepump.net`；没有 DNS 或 Nginx 变更。
- CEHub app 仍为原 image
  `sha256:266a6c8cfc4ee8e695b57b31e640ecd52f5a19c55120132d972ffc187bb4c1bc`，
  原 container ID、启动时间与 restart=0 均未变化，tailer=false、scan interval=35790；
  未执行 CEHub apply 或幂等重放。

## 6. 部署后验证

- canonical deploy/status 两次通过 2 个 Project 的只读 readiness、local session、公网登录、
  DingTalk 未知 route fail-close 与有界日志门禁。
- 外部独立探针确认首页、登录页、`/api/session/status` 均为 HTTP 200，TLS 校验成功；
  HSTS、CSP、DENY framing、nosniff、Referrer/Permissions Policy 均存在。
- 从 `2026-08-14T18:58:40Z` 起连续 12 次、每 30 秒采样；最终
  `2026-08-14T19:09:20Z` 复核不健康容器 0、fatal pattern 0、
  `/api/projects` 500 为 0，Alembic 仍为 0030。
- 应用内浏览器已打开生产登录页；没有复用登录会话，因此 Owner/Admin 登录后的可视化
  Dashboard 最终人工确认仍单独保留，不以服务端检查冒充已登录 UI 证据。

## 7. S5-1 延期风险只读复核

以生产 Compose 的实际安全默认值
`PDOS_PUBLIC_BASE_URL=https://pdos.beepump.net` 与
`PDOS_DINGTALK_DELIVERY_ENABLED=false`，使用强制只读数据库连接复核：

- PASS：公网基址、服务端凭据、delivery 安全关闭、0026/0027 schema、
  active tenant binding、binding scope、callback crypto、1 个 active 项目群、
  unresolved outbox=0。
- FAIL：approval/group/card capability 标识仍不完整。
- FAIL：active linked users 为 0，真实应用 Gate 要求至少 2。

因此 S5-1 仍为明确延期风险，不影响 `delivery=false` 下的核心系统部署，但不能把
真实 password-free login、群通知、审批和 card smoke 记为通过。

## 8. 下一人工 Gate

1. Owner/Admin 在生产登录页建立会话，确认 Dashboard 可读取现有项目组合且不再显示
   “驾驶舱暂不可用”。
2. 另行取得 CEHub apply 授权；apply 与 replay 不得预授权。
3. 完成 apply 后的数据抽查、幂等重放、主入口声明、CEHub 只读归档与至少 30 分钟观察。
4. 最后由 Data Owner、发布 Owner、业务 Owner 共同确认 Sprint 5 Exit；S5-1
   真实钉钉 smoke 延期风险继续独立保留。

## 9. 非破坏性执行偏差

- 首次上传发现受控上传目录不存在；创建 `root:root 0700` 目录后重试成功，
  没有覆盖文件。
- 两次 CEHub 最终复核命令分别因错误依赖和旧表名失败；均为只读事务，修正为
  Drizzle `projects` 后通过。
- 目标快照工具首次从 `/reports` 启动时缺少 `/app/server` 模块路径，
  在连接数据库前退出；显式设置 `PYTHONPATH` 后通过。
- 发布授权后的前三次 SSH 尝试均在 TCP 建连阶段超时，远端未执行命令；通道恢复后从
  release 身份和只读 preflight 重新开始，未绕过任何门禁。
- 以上失败均未产生目标写入，最终前后快照逐字节一致。
