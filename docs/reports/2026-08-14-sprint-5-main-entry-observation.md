# Sprint 5 正式主入口、四项目查询与 CEHub 只读归档证据

日期：2026-08-14（America/Los_Angeles；生产观察为 UTC 2026-08-15）

结论：**正式主入口声明后的 30 分钟只读观察、四项目真实登录/查询、PDOS 目标只读对账与 CEHub 只读归档复核全部通过。** 当前已具备 Sprint 5 / Cutover Exit 的技术证据，仍等待 Data Owner、发布 Owner、业务 Owner 共同确认；S5-1 真实钉钉 smoke 继续作为已接受延期残余风险。

## 1. 人工声明与边界

业务 Owner 在当前受审计会话中明确宣布 `pdos.beepump.net` 为 PDOS 正式主入口，并授权从确认时刻执行不少于 30 分钟的只读观察、四项目登录/查询验收及 CEHub 只读归档复核。同时明确禁止：

- 修改 DNS / Nginx；
- 恢复 CEHub 写入；
- 开启钉钉外发。

执行继续绑定最终 release `82de9d215c5b0101aaba8cbff2d1adf6d751ceef`、tenant `e340c240-d8f0-429c-aac5-69ab9b42fac5` 与批准 actor `4bdba865-c5b1-4ca1-aa85-be467e1fad42`。本次未执行部署、migration、CEHub apply/replay、DNS/Nginx 变更或外发。

## 2. 正式主入口观察窗

正式窗口为 `2026-08-15T02:43:51Z`～`2026-08-15T03:14:35Z`，共 61 个 30 秒间隔样本，实际持续 1844 秒。结果为 `passed`：

- PDOS 不健康容器、重启总数、错误 image 数均为 0；
- root、login、session-status 共 183 次 HTTP 检查全部为 200，TLS verify result 全部为 0；
- fatal pattern 与 Project 500 的窗口最大计数均为 0；
- CEHub 始终 running、restart=0，归档错误窗口最大计数为 0；
- 61 个样本中 `PDOS_DINGTALK_DELIVERY_ENABLED` 始终为 `false`。

每个样本同时检查五个 PDOS 容器、固定 release image、容器重启、公共 root/login/session-status HTTP 与 TLS、fatal/project 500 日志、CEHub 容器与归档错误，以及 `PDOS_DINGTALK_DELIVERY_ENABLED`。首次错误启动因脚本文件以只读 mode 安装、没有 executable bit 而在生成样本前被 `nohup` 拒绝；失败日志单独保留，正式窗口随后以 `bash` 启动同一 SHA-256 脚本并从新的时间点完整起算，失败时长未拼接进 Gate。

## 3. 四项目真实登录与查询

观察窗内在现有生产浏览器用本地 Owner/Admin 凭据重新登录，页面身份显示 tenant `beepump`、role `admin`；浏览器没有读取 cookie、local storage、保存密码或会话存储。

- Dashboard 为 `4 个可见项目`，精确显示 C4s、S18-01、D14-04、D15-05；
- 四个 Project Workspace 均可打开并显示正确 code/name；C4s 为 OBT、当前 `INTAKE`、4 Gate，S18-01/D14-04/D15-05 为 NPD、当前 `CONCEPT`、各 7 Gate；
- C4s 与 S18-01 的 Gate 面板完成可见读取；D15-05 Gate 面板亦完成抽查；
- 两个生产浏览器标签的 console warning/error 均为 0。

页面的“项目文档”面板仅展示 PDOS 私有上传对象，并不展示迁移产生的 `external_file_references`；因此 14 条旧 CEHub 文件引用不以 UI 空面板判失败，而由下述独立目标只读事务按 Project 对账。

## 4. PDOS 目标只读对账

结束点在 API 最终 release 镜像内、`REPEATABLE READ` + `SET TRANSACTION READ ONLY` 的独立事务中复核，报告为 `status=ready`、`errors=[]`：

- 4 Project / 117 Task / 25 Gate / 14 External File Reference / 141 Migration Mapping / 4 Migration Run；
- C4s 为 active / intake，21 Task、4 Gate、8 File Reference；
- D14-04、D15-05、S18-01 均为 active / concept，各 32 Task、7 Gate、2 File Reference；
- 正式窗口内批准 actor 恰有 1 个 `USER_SIGNED_IN` Event 和 1 条 `user.sign_in` Audit，时间一致为 `2026-08-15T02:51:41.474884Z`；这是本次人工登录的预期审计写，不是迁移或业务数据漂移。

`deploy-ecs.sh status` 同时在强制只读路径验证 4 Project readiness，并明确输出 `no state was changed`；五个容器继续运行最终 release 且 healthy。

## 5. CEHub 只读归档复核

窗口起点与结束点均从 CEHub 原应用真实连接验证：role `ce_hub`、database `cehub`，`default_transaction_read_only=on`、`transaction_read_only=on`，4 Project 可读；对永久表的 `WHERE false` 零行写探针均被 SQLSTATE `25006` 拒绝。

结束点运行面为：container ID `380b9284a8d1c126c0f9caff26d2a9e75178780b050d6744050bfd261f0403b5`、state=running、restart=0、读取 API HTTP 200；从正式窗口起点扫描 `scheduled scan failed`、`activity log tailer failed`、`read-only transaction`、`25006` 均为 0。

CEHub 仍运行原 `ce-project-hub-app:current` image；没有重建、恢复原环境值或恢复数据库写权限。旧系统的保留期限和最终停机仍需由 CEHub Owner / Data Owner 按组织数据保留政策另行确定，本 Gate 只确认当前只读审计归档可用。

## 6. 禁止项复核

- `PDOS_DINGTALK_DELIVERY_ENABLED=false` 在正式窗口每个样本均为真，未发生钉钉外发；
- CEHub `ACTIVITY_LOG_TAILER_ENABLED=false`、`AUTOMATION_SCAN_INTERVAL_MIN=35790`，数据库默认只读保持开启；
- 没有执行 DNS/Nginx 命令，没有恢复 CEHub 写权限，没有部署、migration 或 CEHub apply。

## 7. 私有证据

生产证据目录：
`/opt/pdos-migration-reports/82de9d215c5b0101aaba8cbff2d1adf6d751ceef/cutover/`

关键 SHA-256：

- 观察脚本：`798582fe2ad9342a1dc3c5f255854ecbd29b23cf6555c59664280ba8d6b1e1a3`；
- 61 样本 TSV：`e6ff7add7a94358b5e9c31d91ffcceec34bab78e5527256a212bab5a8844be20`；
- 观察 summary：`48078fb587efab1b311d08290b06fe3e3b63833a4012864dfd633f28e05c722b`；
- 目标只读复核脚本 / JSON：`b7adfa29ee6c6e32697e8c6acb21c24cbd2c2be7fb151b3218ebc326a2b65e34` / `18e89ab6486d40823db0638141f344b8d018919e9c1ecd2368218713e4365c3e`；
- CEHub 归档探针脚本 / JSON：`c1ddd2adb9545f3aeba847f96605491be4089bf2e70f2335a010f08b6b2eda59` / `c4dc9b20483e46fc805864f2ff4b1634ce64f0a79659237382a1a21d9a2a2683`。

生产观察脚本为 `root:root 0400`，其余正式报告为对应执行 UID 或 root、mode `0600`。上述 10 个文件已只读下载到本地隔离目录 `/private/tmp/pdos-release-82de9d.iTEP40/artifacts/main-entry-observation-20260815/`，本地 mode 全为 `0600`，SHA-256 与 ECS 逐项一致。

脱敏结论保存在本报告；数据库连接串、凭据、外部身份和文件名未写入仓库。

## 8. 非破坏性执行偏差

- 观察脚本首次以 mode `0400` 直接交给 `nohup`，因缺 executable bit 在生成任何样本前被拒绝；失败日志单独保留。随后以 `bash` 解释同一 SHA-256 脚本，从新的时间点完整起算 1844 秒，没有拼接失败时长。
- 目标复核脚本前两次从 `/reports` 绝对路径启动时，Python 在 import 阶段找不到镜像内 `app` 模块；两次均在创建数据库 engine 和报告前退出。第三次显式设置镜像真实 `PYTHONPATH=/app/server` 后以同一脚本哈希通过；没有覆盖报告或产生数据库写。
- 本地证据下载分批完成；最终 10 个文件均以 ECS 哈希逐项复核，不影响远端原始证据。

## 9. 下一人工 Gate

主入口声明、30 分钟观察、四项目真实查询与 CEHub 当前只读归档技术门禁通过后，仍需 Data Owner、发布 Owner、业务 Owner 共同确认 Sprint 5 / Cutover Exit。S5-1 真实钉钉 password-free login / notification / approval / card smoke 继续作为已接受延期残余风险，规范 checkbox 保持未勾选，生产保持 `delivery=false`。
