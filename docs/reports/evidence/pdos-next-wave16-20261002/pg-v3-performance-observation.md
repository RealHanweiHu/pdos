# Wave16 PG v3 长用例只读性能观察

观察时间：2026-10-03 09:25:37 UTC。这是运行中的证据快照与静态调用盘点，不是新的性能测试或本波完整验收。未连接数据库、HTTP，未运行 pytest，未读登录凭据、运行环境配置或私有 seed；未修改任何冻结后端、测试或工具。仅读取主线指定的 `.local/wave16-root-case-stack.txt`、公开选集/结果和相关源码。

## 已确认的现象

`pg-v3-selection.json` 指向 `backend-candidate-source-v3.json`，声明 480 份源码、20 个精确用例、并发 6。候选文件 SHA256 为 `0955ec34c4b336026b67370f40b3c5a80f741e70aac220dd40143fede37e6eb5`。这里核对的是选集和候选文件身份；没有另跑 480 份源码验收。

| 当前已完成组 | 用例 | runner 总秒数 | pytest 日志 | 结果 |
|---|---|---:|---|---|
| pg-v3-05 | 实际消费 marker 无 SQL 间隙、不能跨事务 | 1726.91 | 1 passed in 1724.49s（28:44） | exit 0，source_stable=true |
| pg-v3-00 | 实际具名 T2 根因 UUID、共同原子回执 | 1866.70 | 1 passed in 1864.24s（31:04） | exit 0，source_stable=true |

两组结果均引用上述相同候选 SHA。09:22:47 UTC 已创建 `pg-v3-06.log`，09:25:07 UTC 已创建 `pg-v3-07.log`，与空出 worker 后启动后续组一致。其余首批日志在本快照中仍为空，不能由此认定没有进展：runner 用 `pytest -q -rA --tb=short`，每组只有一个节点，日志通常在节点完成后才输出 PASS/trace；`*-result.json` 也只在子进程退出后生成。

因此已有证据证明“单节点总耗时约半小时，且队列在推进”。不支持“六组全部死锁”或“用例没有执行”。旧 `priority-*` 的 -15 中断记录属于另一候选，不用作当前通过或耗时结论。

## 原生堆栈能证明什么

指定栈是 macOS `/usr/bin/sample` 的原生采样，不是 Python 函数栈。PID 49022 在 2026-10-03 01:53:59.999 -0700 启动，02:19:08.272 -0700 被采样，距启动 25 分 8.273 秒。

该采样中：

- 主线程 785 次停在 `PyThread_acquire_lock → pthread_cond_wait → __psynch_cvwait`。
- portal/event 线程 785 次停在 `select_kqueue_control → kevent`。
- 工作线程共有 785 次采样，其中 `psycopg wait_c → poll` 两支合计 720 次，约 91.7%。

这些等待形态与同步 TestClient 主线程等待异步 portal/数据库工作线程相容。可以确认**短采样期间主要在等待 PostgreSQL 响应，而非持续进行 Python CPU 运算**。

这份栈没有 SQL、PG `wait_event`、锁归属、Python 函数名或 fixture 阶段，不能把响应等待进一步分解为行锁、服务端执行、连接/网络往返；也不能将 91.7% 外推为完整 25 分钟的比例。不能据此归因到某个 retained 函数、原件磁盘 I/O、环境代理、模型调用或 deadlock。栈亦未给出 PID 与 pg-v3 序号的映射，所以没有将 PID 49022 擅自绑定为 pg-v3-00 或 -05。

## 源码可确认的放大机制

### 每个节点独立重建整条可信前置链

`pdos-next/tools/wave16_check.py:99` 每个节点启动独立 pytest 子进程；`:130` 并发 6；没有跨子进程 fixture 复用。首六节点都依赖函数级 `followup_work`，包括 Root 的 SAVEPOINT、过期恢复节点。静态依赖为：

`followup_work → quality_work → results_work → launch_work/accepted_work → ready_work → 已知 BOM/配置与业务祖先`。

这不是只有一个 Issue 的轻量 setup，至少包含：

| 前置层 | 实际准备动作 | 入口 |
|---|---|---|
| 工程/制造与实物 | 固定配置、真实 Build 开工签核、实际配置/批次/样件、readiness、实际方法和交接/接收 | `tests/verification_handoff/fixtures.py` 与 `tests/build_start/test_transactions.py` |
| 正式验证执行 | 固定完整 RunPlan、未来 Promise、真实时点 Start、资源/样件消费 | `tests/verification_launch/fixtures.py:153`, `:435` |
| 固定失败 | 真实原件上传/扫描/解析、capture、final import，原值 11.0000 确定 fail；结果专业事实独立导入 | `tests/verification_results/fixtures.py:83`, `tests/quality_execution/fixtures.py:55` |
| Issue/CAPA | 新专业事实/政策、create、triage、containment、两项 CAPA draft、实际完成原件、独立分类来源/profile | `tests/quality_followup_transactions/fixtures.py:216` |

20 个子进程各自走这条链，因而重复了真实领域办理、来源核对和资格核对；并发 6 不会消除这些数据库往返。是否产生服务器争用还需 PG 等待证据，不能仅凭并发数量推断。

`pg-v3-05` 的主体只做 `root_command()`/共同 preview、消费 marker 的局部事务回滚和另一事务拒绝；没有成功根因 append，也没有完整措施完成/回链长循环（`test_transactions.py:113`）。它仍耗时 28:44，说明总时间不能全部归给该节点最终原子写入；**setup、inputs/preview 及其递归核对是必须单独测量的范围**。现日志没有 setup/body 拆分，不能说其中具体多少分钟属于夹具。

### 真实窗口等待存在，但不能单独解释半小时

默认 `launch_work` 在形成资源事实时设置真实 `window.start=at+5min`。`advance_clock` 仅等到该已固定开始时点再加 250ms，每次 sleep 最多 1 秒；Plan/Promise 耗时会消耗这段提前量。它不会在前置链已经耗时五分钟后再无条件等待五分钟，更不是默认等待 25–30 分钟。生产未来窗口、SQL 实际时钟与完整 Promise/Start 规则必须保留。

### 每个命令阶段有多次深层读取，属于真实安全核对

共同服务在 preview 中分别调用 `validate` 和 `reviewed_view`；execute 又独立做 validate、共同消费时重算实质 preview、apply（`pdos_next/service.py:419`, `:485`, `:522`, `:633`）。各阶段不得把上个阶段的肯定证明当当前许可。

本波 `quality_followup.service._load:306` 先核每个固定失败的真实报告与 retained，再核政策、完整来源、完成事件/分类 assessment，最后 `_refresh:432` 用窄 refresh 独立核 earlier failures、专业/政策/来源/runtime。当前 GET `_read_row:732` 同样保留原失败全文核对与末端刷新。它们会沿旧 Run/资源/方法/样件来源递归；这是查询往返的明确调用路径，但**本次没有 Python profile/SQL 计数，不能给它们分配实际耗时百分比**。

后续 Link 的静态重复更明显：`capa_verification.commands._load:124` 先 `load_exact_followup_basis`，随后 `resolve_followup_outputs`；后者又重核 basis，`_refresh:199` 再调用同一 resolver，`_new_write:231` 再核 Current 与 resolver。`load_exact_followup_basis:113` 每次逐失败调用完整结果桥。它是未来可收敛的具体边界，但首批六节点没有 Link 主体，不能用 Link 重复次数解释当前首批耗时。

## 下一候选可实施的最小方案

1. **先拆时间，避免盲改。** 在 Root 下一次有改动的检查点，仅对一个精确节点记录：上游 fixture 各层、实际未来时点等待、inputs、共同 preview、execute、测试主体/teardown。同步记录各区间 SQL 条数、数据库调用累计秒数，不写 SQL 参数、原件正文或 token。`--durations` 可给 setup/call 初分，fixture/阶段 monotonic 计时才能拆完整前置链。采集 Python 具名栈或只选一个 profile 后，再决定递归核对的优先级；本轮不中断、不附加测试。
2. **把 PG 响应等待分类。** 由 Root 在目标已核对后抓短时 PG `wait_event`/锁等待者快照，配合相同阶段的 SQL 次数。只看到 poll 时不调整锁、权限或隔离级别。以后评估 1/2/6 并发的单位链耗时和总体吞吐，才决定最佳并发；不为测吞吐重复当前无变化候选。
3. **同一 phase 内复用严格 typed 的已核原件结果。** 优先收敛 Link resolver 重复的全报告读/解析：第一次真实 owner/失败核对返回服务器 typed proof，后续同 phase 仅复用 immutable 内容与绑定，所有 owner I/O 完成后仍用独立窄 refresh 核完整 Current/ACL/source/security/issuer/runtime/政策/专业。绑定必须含同 Session/事务、consumer scope/actor、精确失败 Run/Projection/rules/basis、原件 SHA/security epoch、callback identity 和期限；不能从 client DTO 或历史肯定 bool 建 proof。
4. **减少无作用的展示深读。** 能在服务端固定依据中读取的 labels/固定 DTO 不另调用生成整页 capabilities 的 reader；同一阶段测试断言复用一次 listing 快照。不省新阶段当前来源/权限重核，不把历史能力伪成肯定或未知=false。公开 GET 只有存在 owner/link I/O 才进行对应 after-all-owner 刷新；空候选不增加 paired-owner 桥。
5. **测试前置的复用以隔离为限。** 未来可把同一个独立 tenant/function 场景的相关断言合并，在仍真实构造一次祖先后分别做 SAVEPOINT/rollback；全链正例继续保留。源撤回、policy/security/profile ABA、不同主体与 scope 的负例仍用独立可变事实，不改成 module/session 级共享活数据库。跨节点可复用无身份的 immutable JSON/算法模板，不能复用原专业 proof、已消费 token、同一资源/样件身份或复制成功 Receipt 代替真实办理。

任何优化都须保留：每阶段当前本人/来源 ACL，Current 精确 CAS，历史原失败与真实原件字节，后一个 I/O 撤销前一个证明的末端刷新，专业/政策/issuer/security/profile ABA 与 expiry，T2 真实 UUID/同事务消费 marker，以及 Receipt/Audit/Outbox/指针全部原子。不能用同 phase 性能缓存跨 validate/preview/apply/replay，更不能以普通 grant 或合成 fixture 为生产资格。

## 证据身份

| 文件 | SHA256 |
|---|---|
| `pdos-next/.local/wave16-root-case-stack.txt` | `32c8a0b41b5ee362f175a83a7b61eeadc1ab431064c9011f28037467b4ecacf7` |
| `pg-v3-selection.json` | `b1aced4dfb7cfb61ba85e911eb924bcd8fe830f1074ae7982eb9bc867fd40857` |
| `pg-v3-00-result.json` | `0053427a0beacb418b6ddc73840f1b60bd4f6f02b69c46aeda8539b6664f2b4a` |
| `pg-v3-00.log` | `06744b58ab58b4b96f40d0349166c4cb67ecca0464afb18ce0dc863086f55132` |
| `pg-v3-05-result.json` | `edc35e5bfe2041cb81bdc8f5d76bfe7a49ba22a5a47b6833515736f2b86d07f5` |
| `pg-v3-05.log` | `a8c99d76dba1c15ecc88a29a3653e55bdb31c41c6ea2c6c620fda87b894acb45` |
| `pdos-next/tools/wave16_check.py` | `1f30b486d34177a38e34cfa8a004e42b730b8bf9fa07f74b75b0a4d885eef05d` |
| `tests/quality_followup_transactions/fixtures.py` | `cae4abd15db6dcfd164e14ca6f858648405521145f620c2a47c6f16d028dd3a9` |
| `tests/quality_followup_transactions/test_transactions.py` | `58bfa1250c427af0d7b6842dd33dd38b52a3b2cbed37ea364f13a1284f17ca80` |
| `tests/quality_execution/fixtures.py` | `1738572bc97e692d5cf8235377a184d1221d970e99b5594bf683794f95336ec9` |
| `tests/verification_results/fixtures.py` | `62d5d0e61839b49ac833d7bb8fcb5cc509bccaec4697c065e16087019f8a3df7` |
| `tests/verification_launch/fixtures.py` | `10e5c57889064fd47be6044f80197eecb6c07f46079153e6e6dcb63eef81ff5f` |
| `domain/quality_followup/service.py` | `4d04678c24d5670b2e6e46953661dd638b5518a3adf364b82cffe725bc28ac62` |
| `domain/capa_verification/commands.py` | `05c8c74af37cd26edd73ed320311f20d86c9b6515ebc9bac2b9b37a6e28a150a` |
| `domain/capa_verification/service.py` | `91c72ff1d49a794561af28c9a5dfcdef52d717588b46aa9390a00abd816798af` |
| `pdos_next/quality_followup_views.py` | `2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3` |

上述 `tests/`、`domain/` 路径均位于 `pdos-next/server/` 相应包下。结果目录仍在继续生成；本报告不宣称 20 项已结束，也没有把建议优化声明为已实施或已测得收益。
