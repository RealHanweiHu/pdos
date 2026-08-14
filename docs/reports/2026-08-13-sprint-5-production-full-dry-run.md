# Sprint 5 生产全量写冻结、inventory verify 与 dry-run 证据

日期：2026-08-13（America/Los_Angeles；生产执行时间为 UTC 2026-08-14）

结论：**本次 CEHub 写冻结、全量 inventory verify 与全量 dry-run 通过，目标库零变化；但后续只读 `status` 发现 release `2cce...` 的 CEHub 导入 Project API 阻断，该 release 已失效且不得部署/apply。必须以修复后的新 release 重跑本门禁，详见 `docs/reports/2026-08-13-sprint-5-project-api-release-blocker.md`。**

## 1. 人工授权与固定输入

Data Owner 明确批准并授权本阶段执行：

- release / Git / OCI revision：`2ccefa1d2fe6567be4af8370b67aed9164aadd1d`；
- inventory fingerprint：`a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d`；
- 有序全量项目：`WqWcl0wK,aBnbEdQG,xY8-PGbc,zGpNH0Xq`；
- tenant：`e340c240-d8f0-429c-aac5-69ab9b42fac5`；
- actor：`4bdba865-c5b1-4ca1-aa85-be467e1fad42`；
- 允许 CEHub 写冻结、inventory verify 与全量 dry-run；明确禁止部署和 apply。

候选 API image 为 `sha256:b69df7c1038709991e5f968280cd940dc466fa770322acab687c8a0797375df0`，OCI revision 与批准 release 精确一致，运行用户为非 root `pdos`。生产私有 `.env.production` 保持 `root:root 0600`。

## 2. CEHub 写冻结与稳定只读运行

冻结前从旧应用真实连接确认：角色 `ce_hub`、数据库 `cehub`，数据库角色设置和角色设置均为空，`default_transaction_read_only=off`，遗留 assigned-XID 会话为 0。

UTC `2026-08-14T03:01:00Z` 停止旧 `app`，清理旧连接后执行数据库范围设置：

`ALTER ROLE ce_hub IN DATABASE cehub SET default_transaction_read_only=on`

随后启动同一旧 image `sha256:266a6c8cfc4ee8e695b57b31e640ecd52f5a19c55120132d972ffc187bb4c1bc`，不构建、不拉取、不切换代码。真实新连接验证：

- `default_transaction_read_only=on`、`transaction_read_only=on`；
- 4 个 Project 可读；
- 对永久表的零行 `UPDATE public.projects SET id=id WHERE false` 被 SQLSTATE `25006` 拒绝；
- assigned-XID 会话为 0；
- 首份冻结报告 SHA-256：`38eac2b06e937cb6038d7bc7bc0ba93b6ad9720eaaba0e91911a01d94404fb8a`。

旧应用的 activity-log tailer 每 5 秒写 heartbeat。冻结后 15 分钟安全分类统计发现 180 次 `activity log tailer failed`，均同时为 `read-only transaction` / `25006`，没有 scheduled scan 失败。为保持只读审计入口稳定，在旧私有 `.env` 仅增加 `ACTIVITY_LOG_TAILER_ENABLED=false`，原文件备份为 `/opt/ce-project-hub/.env.backup-before-readonly-freeze-20260814T030100Z`；两者均为 `root:root 0600`。随后以同一旧 image 强制重建 `app`：

- 页面与 `/api/setup/status` 读取为 HTTP 200；
- 新连接仍为默认/当前事务只读，零行写探针仍为 `25006`；
- 连续 15 秒日志中 tailer / read-only / `25006` 计数均为 0；
- 容器 running、restart count 0；
- 稳定运行报告 SHA-256：`e771a545227ee63f72f35cdbb974e2d129236d5f5d01f686f32f9e3050c2c94a`。

恢复 CEHub 写权限与 tailer 不属于自动回退；必须另获 Data Owner 授权，并按备份原值恢复、换代连接池和复验。

## 3. Inventory verify

批准 fingerprint 与有序四项目通过候选镜像只读复核：

- mode：`verify`；status：`ready`；`errors=[]`；
- project count：4；有序 ID 与批准值逐项精确相等；
- inventory fingerprint 保持 `a450122f0f3bac6a7eceec600463e641f3d33b6768bf1400c81c805b878f484d`；
- 报告 SHA-256：`30bd71ed7253b8865d3bf3d34a1dbc4bc270043c20c7a4d221ef5aa49204c66f`。

## 4. 全量 dry-run

使用同一 release 与同一有序 source ID 运行 `--dry-run`，没有注入任何 apply fingerprint 或确认变量：

- mode：`dry-run`；status：`ready`；`errors=[]`；`target_writes=0`；
- source fingerprint：`d3d903b6bfa05958678b00502e565f0629d34d634242c8adb49c5a6f06d56b54`；
- source counts：6 User、4 Project、117 Task、0 Gate Review、14 File Reference；
- 预测 created：1 User、2 Project、64 Task、0 Gate Review、4 File Reference；
- 已有 mapping 预测 skipped：5 User、2 Project、53 Task、0 Gate Review、10 File Reference；
- 每类 `created + skipped == source`；报告 SHA-256：`e61a55eed12222562a27136b64be053a2714f5c28432f013a180dfe8ace2029b`。

首次后置断言把实际 mode `dry-run` 误写为 `dry_run`，并错误假设 dry-run 的预测 `created_counts` 必须为 0，因此在报告已经成功落盘后退出。只读解析确认报告本身成功后，按真实合同修正为 `created + skipped == source`；没有重跑、覆盖或改变报告，未发生目标写入。

## 5. 目标库零变化与线上健康

dry-run 前后均在候选容器中用 `REPEATABLE READ` + `SET TRANSACTION READ ONLY` 独立冻结目标 tenant 的 11 张迁移相关表。逐表 count 与完整内容 SHA-256 全部相等，前后报告甚至字节级 SHA-256 相同：

`e54ff15cd5450c5ed84270b39856831a2be1f08aee9243c0a1fc1086d40b2ab7`

后置计数保持：6 User、2 Workflow、11 Stage、2 Project、4 Project Member、11 Gate、53 Task、0 Gate History、10 External File Reference、2 Migration Run、70 Migration Mapping。

生产运行面复核：

- PDOS 五服务仍运行 release `a34c7eb06aaba036bef8c257c30a841c1ec6be0d`，原 container ID 未变且全部 healthy；
- 候选 `2cce...` 运行容器数为 0；
- Alembic 仍为 `0027_dingtalk_hardening (head)`；
- `https://pdos.beepump.net/login` HTTP 200；
- `PDOS_DINGTALK_DELIVERY_ENABLED=false` 延期例外未改变；
- 没有执行 `deploy`、Alembic migration、`apply`、DingTalk 外发或目标数据写入。

ECS 原始报告均为 UID/GID 10001、mode `0600`，位于 `/opt/pdos-migration-reports/2ccefa1d2fe6567be4af8370b67aed9164aadd1d/cutover/`。六份报告已下载到仓库忽略的本地私有 evidence 目录，下载后 SHA-256 与 ECS 一致。

## 6. 下一人工 Gate

本次 source fingerprint 仍作为不可变历史证据：

`d3d903b6bfa05958678b00502e565f0629d34d634242c8adb49c5a6f06d56b54`

不得再批准或部署 release `2cce...`。修复合并形成新 release 后，必须在 CEHub 继续只读的条件下重新执行 inventory verify、全量 dry-run 和目标前后快照；Data Owner 绑定新 release 与新报告后，才可分别授权部署和 apply。CEHub 在此期间保持稳定只读。
