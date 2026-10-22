# 产品经理独立联验环境分配 · 2026-09-30

**当前状态：产品经理本轮独占已释放，容器停止、候选数据与原卷保留。** PM于客户端时间2026-09-30 19:39（America/Los_Angeles）完成收尾；协调随后只读核对同一容器/卷、端口及备份摘要。当前库保留0415候选，不是下表首次分配时的空库；后续分配须明确新窗口及保留/清理范围。

以下保留首次分配证据：用户在PM会话的 `01a0f4c6-476f-7fb3-a23e-c07b2cadaa8c` 回合明确回复“我授权”，主会话已发送本次协调请求。协调只完成环境准备，没有代替PM执行迁移、repo测试、业务HTTP/浏览器或模型调用。

| 项目 | 分配结果 |
|---|---|
| 使用者 | PM主会话 `01a0ebea-d4c5-76b3-8857-0d82465a25d5` |
| 分配者 | 协调会话 `01a0f2ad-5467-7e93-9158-35f59d252d64` |
| 本机目标 | `127.0.0.1:57441/pdos_test`；容器内端口5432 |
| 新容器 | `pdos-pm-joint-20260930-pg` |
| 容器ID | `d78973a1c3ef0665c06694417b5098e6503fd928cc119fd48eba3333c9654815` |
| 新卷 | `pdos-pm-joint-20260930-data` |
| 本地现有镜像 | `pgvector/pgvector:0.8.6-pg16-bookworm`；镜像ID见核验记录；没有下载镜像 |
| 私有连接文件 | `/Users/huhanwei/Documents/ai-native-R&D-platform/output/pm-joint-allocation-20260930/test.env`，0600，仅一行 `TEST_DATABASE_URL` |
| 分配时库状态 | 已接受本机连接；PG16/vector0.8.6，`max_locks_per_transaction=1024`；当时为新空库，尚无业务schema或alembic_version |
| 分配时真实最小角色 | pdos_agent、pdos_worker、pdos_app；均NOLOGIN/NOSUPERUSER/NOCREATEDB/NOCREATEROLE/NOINHERIT/NOBYPASSRLS，无角色成员关系 |
| 分配时源码迁移核对 | 唯一head `0413_conversation_matrix_runs`、414个revision；执行前由PM再次核对，不把源码head写成数据库已升级 |

**已结束的使用窗口**：首次分配起至上述PM检查点收尾释放。期间只由PM主会话串行操作；协调及其他线不得复用该库。每例共用夹具会执行迁移并清理全租户，不能并发运行两套测试或同时保留浏览器数据。

**允许范围**：PM操作前重新核对具体容器/卷、实际数据库、端口及真实角色。读取上述私有连接文件到进程环境，显式设置 `TEST_DATABASE_URL`，并将 `DATABASE_URL`设为同值；不打印凭据、不回退或复制业务`.env`。允许当前候选升级/降级/往返/schema检查，以及仅在新分配的这个 `pdos_test` 内清理或重建测试租户、表/schema等合成数据；允许针对该库的本地合法登录API与浏览器验证。相关测试不需要额外PDOS隔离标记，实际用例数量按PM收集结果记录。

**收尾责任**：由PM主会话统一保存候选、必要备份、原始日志及恢复条件，再停止自己的临时服务和这个确切容器，保留卷/容器/连接文件，记录使用窗口释放；此分配不包含删除卷或清理其他环境。57432/57433/57434/57439/57440没有操作，不允许用于本次repo测试。0377恢复及部分记录损失历史保持。

预建真实pdos_agent仅满足迁移/角色核验前置；PM迁移后仍须核对有效业务写权限，不能以角色存在或新空库授予模型资格。生产、push、真实业务外发、真实模型调用授权/逐能力资格及N/P/Q人工出口保持原边界。

具体实际身份及客户端时区时间见[分配核验JSON](../../../../output/pm-joint-allocation-20260930/allocation.json)，[核验日志](../../../../output/pm-joint-allocation-20260930/verification.log)和[最小角色初始化日志](../../../../output/pm-joint-allocation-20260930/bootstrap.log)保留。记录不含连接密码或token。

**收尾核对**：[协调释放记录](../../../../output/pm-joint-allocation-20260930/release.json)及[只读核验日志](../../../../output/pm-joint-allocation-20260930/release-verification.log)确认原容器/卷保留，57441及PM专属API63493/页面63494均未监听。PM的[4,543,055字节合成备份](../../../../output/pm-joint-20260930-0413/backup-result.json)与1份对象清单摘要匹配；[PG16归档目录检查](../../../../output/pm-joint-20260930-0413/backup-list-result.json)通过，`actual_restore_exercise=false`。[PM收尾回执](../../../../output/pm-joint-20260930-0413/environment-closeout.json)为`released_stopped_retained`。协调未连接数据库、恢复归档或重跑PM检查；0415基础候选与随后PDF增量的覆盖仍分别由PM登记，不能写成增量后全量重跑。真实材料/计量/调用授权、模型资格及人工Exit未随资源释放通过。
