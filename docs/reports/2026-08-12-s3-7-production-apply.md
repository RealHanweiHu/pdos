# S3-7 生产试点 apply 与幂等重放证据

日期：2026-08-12
范围：CEHub `C4s`（`zGpNH0Xq`）与 `S18-01`（`aBnbEdQG`）→ PDOS `beepump` 租户
状态：**apply、独立数据抽查与幂等重放全部通过**

## 1. 人工批准与固定输入

数据 Owner 已确认 dry-run 抽查通过，并明确批准以下不可变输入：

- release / Git / OCI revision：`e1d0b2aaaff1ef9cf0b49e27f59464554aac80e3`；
- source fingerprint：`d37ac192c4c318b540f6beb74d3340ee8bbfd04f7776f4f0f1112b1760abe71d`；
- 有序选择器：`C4s,S18-01`；
- 目标租户：`e340c240-d8f0-429c-aac5-69ab9b42fac5`。

apply 前重新执行源快照冻结，fingerprint 与获批值一致；目标库 11 表计数/内容哈希与数据 Owner 审阅时的零写基线一致。立即前置报告 `target-immediately-before-apply.json` SHA-256 为 `fed2ae3a6f1213d49ccf36f69e4e09886ec7e15fc1e6d5f465346777c0c195db`，正式 dry-run 报告 SHA-256 为 `30d7948b0a6cf9414c565bb83d15095365efce5a3545d97f1795be57610fecc5`。

首次输入缺少 fingerprint 的不完整二次确认串被迁移器在连接数据库前拒绝；未创建报告、未发生目标写入。随后使用与人工批准完全一致的四项绑定值执行。

## 2. 首次 apply

- 状态：`completed`；errors 为空。
- 创建：5 User、2 Project、53 Task、0 Gate Review、10 File Reference。
- 跳过：五类均为 0。
- `target_writes=169`，包含业务对象、Workflow/Stage/Gate、成员关系、70 条稳定 mapping 与 1 条迁移运行审计。
- 报告：ECS 私有目录 `cehub-v1-apply.json`，mode `0600`，SHA-256 `b96ca1438f5aa59ce69f651ee341c6fa59c7cfbb810a4cef3f99facb8b390330`。

## 3. apply 后独立目标库抽查

未复用迁移器聚合结果，以新的只读 Repeatable Read 事务直接查询目标库：

- 租户总量：6 User（含原有 1 个管理员）、2 Workflow、11 Stage、2 Project、4 Project Member、11 Gate、53 Task、0 Gate History、10 External File Reference、1 Migration Run、70 Migration Mapping。
- mapping 分布：5 User、2 Project、53 Task、0 Gate Review、10 File Reference；70 个 target ID 全部存在，`source_hash` 均为 64 位十六进制值，并绑定同一成功运行、同一 fingerprint 与项目范围。
- 5 个导入用户全部默认禁用且无密码哈希；角色分布为 2 Admin、3 Engineer。
- C4s 为 active/intake，拥有 4 Stage、4 Gate、21 Task、8 File Reference；S18-01 为 active/concept，拥有 7 Stage、7 Gate、32 Task、2 File Reference。
- 抽查任务状态/日期与文件名、媒体类型、大小、密级、阶段/任务引用均与源数据 Owner 抽查一致；源 Gate History 为 0，目标仍为 0。

完整快照 `target-after-apply.json` mode `0600`，SHA-256 `b466974812c39b4ee17d24123acf7bc64cb015e1f7b6a9f523b2b20e991171d1`；业务抽查报告 `target-owner-review-after-apply.json` mode `0600`，SHA-256 `041231fd8befb407536f498af3fc396e682bb3b39e17fcaa5df516b598eeac20`。

## 4. 原参数幂等重放

使用同一 release、fingerprint、目标租户和有序选择器再次执行 `--apply`：

- 状态：`completed`；errors 为空；fingerprint 与解析后源项目 ID 完全一致。
- 创建：五类全部为 0。
- 跳过：5 User、2 Project、53 Task、0 Gate Review、10 File Reference，与源计数逐项相等。
- `target_writes=1`，仅新增第二条成功 Migration Run 审计。
- 报告：`cehub-v1-replay.json` mode `0600`，SHA-256 `5a988e216f80584c6c832f00fdb285cf7a19162cfcf56dd3c4bbc93b63012dba`。

重放后再次冻结目标库完整快照：

- 除 `migration_runs` 外，User / Workflow / Stage / Project / Project Member / Gate / Task / Gate History / External File Reference / Migration Mapping 十张表的 count 与内容 SHA-256 均与首次 apply 后完全相同。
- `migration_runs` 由 1 增为 2；两条记录均为 `completed`、同一 fingerprint、同一有序项目范围。首次运行记录全量 created，第二次记录全量 skipped。
- `migration_mappings` 仍为 70 条，内容 SHA-256 仍为 `b776127d8db5373b3d442c63c6b1853f8f4400ab8f757c478ec746cfa31ca481`，全部继续归属首次 apply 运行。
- 重放后快照 `target-after-replay.json` mode `0600`，SHA-256 `65ab85e4b5e5be8cfa22216c8b7a3961853520b5e36ea981cbaf4d69df6a9cf5`。

## 5. 线上健康与结论

本步骤只运行固定候选镜像中的一次性迁移 CLI，没有部署或替换线上应用镜像。apply 与重放后 API、Dispatcher、Executor、Web 容器 ID 均未变化，restart count 全为 0，health 全为 `healthy`；公网 `https://pdos.beepump.net/login` 返回 HTTP 200。

S3-7 的真实试点验收成立：获批源快照被完整导入，目标数据抽查一致，原参数重放没有新增或修改任何业务对象/mapping，审计运行记录完整。未触发回滚条件。
