# Wave18 Root 取证工具只读审阅

本审阅只读取公开工具与调用源码；没有读取 `.local` 文件内容、凭据或环境变量，没有运行工具、DB、HTTP、pytest、worker 或构建，没有修改工具或业务源码。它是接口与执行边界审阅，不是实际取证通过结论。Root 正在修订工具；下表绑定本次读取的字节，后续版本不能直接沿用该结论。

## 绑定源码

| 文件 | SHA256 |
| --- | --- |
| `pdos-next/tools/wave18_fact_http.py` | `1858f96aa30247c17d33ecea34bce7920a1b5a4529bef5c066e731a8841d999d` |
| `pdos-next/tools/wave18_fact_readback.py` | `0456422d88959bce2fb3ae8b4ccbecf029c3b0a3fdf1a545ea0b3c0e54ccf14b` |
| `pdos-next/server/pdos_next/capa_fact_api.py` | `a8818d6cdf5fefd6ce3246fd9798145a7ea5d8288f0cec83b4dc6d1162ed3b6f` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/fact_atom_storage.py` | `6b6d05de7e0e4f2ffee541b6be66c34265feeeec098417367834281d8e31e16e` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/participants_owner.py` | `a0bb90e954c68c87184cbf5b0526ea023242928f2ae8c6dddd6ea7bc7ee5c282` |
| `pdos-next/server/pdos_next/domain/capa_effectiveness/fact_sources_owner.py` | `b431151e49b72e8cce36f36486a670ecce6a2e9fc333e1bd52ba3ddc75db8126` |
| `pdos-next/server/pdos_next/database.py` | `a64c91d9f9a465be48b2585198ca7db802d37de0a38b2fed1064e445535c0858` |
| `pdos-next/server/pdos_next/service.py` | `e4712878901eef8e2933482fc31db2f948767921722def6004b43c3eb135f9e9` |
| `pdos-next/tools/wave17_candidate_closeout.py` | `8864959cb231b167daf10a356669be59db97865192b4e706d909fe350cecad01` |

## 已对齐接口

- HTTP 路径、`pdos-capa-fact-workflow-v1`、`binding.caller_id/current_issue`、`rules/records/sources/history/operations` 与实际 [capa_fact_api.py](../../../../pdos-next/server/pdos_next/capa_fact_api.py) 相符。Inputs 接收完整 `Command`，只补完整 `source_read_set`；共同 preview 返回 `command/review`，review 为实际 13 键材料。保存/原请求恢复读取共同 Receipt 的 `id/subject_id/subject_type/subject_revision`，没有把 SQL 外键 `receipt_id` 误当 HTTP 字段。
- 已看到 Root 修正回读为 `retained(...)["status"] == "PASS"`，以及 RLS 会话键 `pdos.tenant_id`。这两项不再列作剩余缺陷。
- `read_fact_atom` 返回 `StoredAtomRead.atom`，`assemble_fact` 产生带完整 FactRef 的真实事实；Rule 无共同确认，Observation 带原 proof。`read_participants` 返回真实 `ParticipantRead.participants/missing`，不是授权、独立性或七 owner 通过证明。
- HTTP 完整命令、确认 token、响应全文留在私有 0600 文件；公开输出仅状态、时长、摘要、安全 code 与对象/回执标识。没有发现打印 token、密码、带凭据 URL 或原始报告全文的代码路径。`target()` 核显式 marker、角色端点与独立 `pdos_test`。

## 确定阻塞与边界

### 1. App 的 PG READ ONLY 与真实来源行锁冲突

[wave18_fact_readback.py](../../../../pdos-next/tools/wave18_fact_readback.py) 的 app 事务设 `REPEATABLE READ READ ONLY`，随后调用 `read_participants`。该调用必经 `read_source_closure` → `evidence.source_basis/check_source` → `service.source_for`；`source_for` 无条件对 Product 与 Artifact 执行 `SELECT FOR UPDATE`，原件还保留当前门锁。PostgreSQL READ ONLY 不允许这些行锁，因此不能完成这项真实 owner 回读。`fact_sources_owner` 的模块说明也明确业务只读不等于 PG READ ONLY。

最小工具恢复：catalog/retained 保持 PG READ ONLY；app owner 部分使用显式普通事务、禁止业务 DML/DDL/flush 的 driver gate，允许既有控制行锁，并在正常与异常路径均 rollback。不能通过去掉 source/原件门锁、改生产 reader 或伪造参与者结果来使工具通过。只有 Atom/Current 的纯存储关联读取可以留在 PG READ ONLY。

### 2. Participants 的真实原件端口尚未安装到实际 bind

回读工具由 `engine_for(app_url)` 新建引擎，没有安装实际 OriginalStore/security runtime；`Session(bind=c)` 又使 `s.get_bind()` 是 Connection。`read_source_closure` 从实际 bind 取 `_pdos_results_store`，而它的完整失败来源包含真实上传测量报告。解除 READ ONLY 冲突之后，当前代码仍会因 store 缺失或原件安全 runtime 缺失而拒绝，不能据此声称完整参与者来源已核。

工具若要实际运行该项目，需要明确安装真实 store/security 端口，并确保现有 owner 能在该 Session 的实际 bind 读取它们；不得用假 store、客户端原文或 Artifact.content 代替真实测量原件。另一安全选择是把该项标为未执行/缺真实端口，仅交付 Atom/Current/原子组的回读范围，不能留 `participants` 通过标签。

### 3. HTTP 未固定直连代理边界

`urlopen(Request(...))` 默认可采用环境代理；代码固定目标 `127.0.0.1:8898` 并不保证 Bearer 请求绕过环境代理。这是条件风险，本审阅没有检查环境、更没有断言发生凭据外传。最小修订是显式使用无代理 opener，例如 `build_opener(ProxyHandler({}))`，仅本机请求，不输出代理配置。

### 4. source_stable 没有完整比较文件集合

HTTP 工具末端只重新哈希启动时已存在的文件。新增 runtime `.py/.toml/.ini` 不会被发现；删除文件会在 `finally` 抛异常，可能丢掉最终报告。应按同一排除规则末端重建完整集合，分别记录 added/removed/changed；任何一项非空都不能标记 stable。source manifest 也应排他创建，避免初始化失败没有结果文件时同 tag 再运行覆盖先前 manifest。

## 证据范围须保持窄

- Admin `has_table_privilege` 当前只证明表级 INSERT/UPDATE/DELETE，不能单独证明列级 UPDATE/INSERT 也为零。若最终报告要写全表/列 Agent 零直接写，可复用 `wave17_candidate_closeout.catalog` 的 `has_column_privilege` 检查，或明确引用既有对应候选证据。
- `retained` 比较的是其明确列出的旧表，返回值已写出 `not_compared`；不要推广为此刻 106/111 表全部行无变化。`full_anchor_unchanged` 的当前断言证明 Rule/Observation Current 与对应事实保存的 full anchor 相等；本身不是重新授七 owner 或核实物理采样。
- `named_review_rows == 0` 是当前整个隔离库的计数验收，不是按演练 Issue 过滤。如果后续独立合法 Review 写入同库，须调整验收范围或如实报失败，不能把已有 Review 删除来满足计数。
- 异常场景公开报告保留安全类型/code，私有响应与原请求保留。初始化和登录检查目前在 HTTP 主 `try` 之外，失败时可能只有源 manifest 没有结果文件；应以新证据明确失败阶段，避免“没有 report”被当成未发过请求。

## 当前结论

实际 payload/方法/返回字段没有发现新的确定不匹配。四项工具边界已直接发送 Root；其中 app READ ONLY 与原件端口缺失会阻止合法参与者回读，HTTP 代理及文件集合检查影响保密和 sourceStable 的取证可信度。工具后续修订及真正 DB/HTTP 结果仍由 Root 验证；本审阅没有增加测试、执行工具或改变公共候选。
