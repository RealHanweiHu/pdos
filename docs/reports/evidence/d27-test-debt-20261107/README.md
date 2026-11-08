# D27 清理既有测试失败（2026-11-07）

候选：分支 `claude/w4-d27-test-debt-6147cc`，基于 `d730291d`。只改测试和夹具，不改产品代码。

## 结论

| 范围 | 修复前（d730291d） | 修复后 |
|---|---|---|
| 无库全量 | 169 失败，10490 通过 | 0 失败，10654 通过 |
| PG 清单 115 个 | 103 失败，4 错误，8 通过 | 分三轮复跑后剩 4 个（下表） |
| PG 最终复跑 184 个（含 S1 候选摘要、整次撤回、受共享夹具影响的整文件） | — | 180 通过，4 失败（即下面已归因的 4 个） |

剩下 4 个都已归因：D258（迁移把 SECURITY DEFINER 函数留在迁移账号名下）1 个、D259（以客户原件为依据的知识在企业检索里被剔除）2 个、检索 p95 超过 1 秒的环境性能 1 个。没有改产品代码，没有放宽阈值或删用例。

清单把 8 条撤回 `VERSION_CONFLICT` 归给 P68，实测不是：它们失败在建 T0 写入的来源校验，夹具改好后全部通过。P68 仍未实施。

## 怎么跑的

- 无库全量：`server/` 下用主工作区解释器 `python -m pytest`，去掉全部数据库环境变量。需要数据库的用例按原样以 ERROR 退出（1882 个，前后一致），只统计 FAILED。
- PG：只用 `tools/local_environment.py` 核对过标记的独立 `pdos_test`（127.0.0.1:53993，标记 f117bb5b）和同标记的检查点库（`tools/workflow_environment.py`，127.0.0.1:61323），不回退 `.env`，不打印连接串。运行器是本目录的 `isolated_pytest.py`（`python isolated_pytest.py <server 目录> <pytest 参数>`），除测试库外补了 `M2_TEST_CHECKPOINT_URL`、`PDOS_CHECKPOINT_DATABASE_URL`、`PDOS_STATE_DB_PORT/MARKER`；`test_public_temporal_domain` 要求仓库根下有 `.local/tools/temporal`，worktree 和 HEAD 副本里各放了一个指向主工作区本地程序的符号链接（已 gitignore）。
- “修复前”在 `git archive d730291d` 得到的干净副本上跑，与“修复后”同一个库、同一组用例。每次跑前核对过只有本会话连这个库。
- 本机负载在 13 到 37 之间（Docker 虚拟机、iCloud 同步，最后半小时另有 4 个会话在各自的库上跑 PG），计时类用例的结果受此影响。
- PG 清单：三份证据清单（D242 48 个、D245 37 个、P76 第 4 项 39 个）和 11-07 D254/D255 回归的 22 个去重后 89 个，加 11-04 摘要类 14 个、10-31 报告里的 8 条撤回所在的两个文件、`test_project_current_context_pg.py` 整个文件，共 115 个用例。

## 文件

- `nodb-before-failures.txt` / `nodb-before-summary.txt`：修复前无库全量的 169 个失败。
- `nodb-after-failures.txt` / `nodb-after-summary.txt`：修复后无库全量。
- `pg-ids.txt`、`pg-files.txt`：PG 用例清单。
- `pg-before-classified.txt`：修复前 PG 每条失败的错误、拒绝原因和出错位置。
- `pg-extra-ids.txt`、`pg-before-extra-*`：HEAD 上补跑的 S1 候选摘要、整次撤回和补齐环境后的摘要/Temporal 用例。
- `pg-final-files.txt`、`pg-after-summary.txt`、`pg-after-failures.txt`：最终整批复跑（184 个用例）的清单与结果。
- `pg-after-round*-classified.txt`：修复后三轮复跑剩下的失败。

## 无库：169 个失败怎么修的

| 类别 | 个数 | 原因 | 改法 |
|---|---|---|---|
| 产品对象缺列 | 112 | `capa_link_phases`（90）和 `test_launch_plan_preview`（22）用脱库的 `Product`，后来新增的 `parent_product_id`、`target_price*` 六列没赋值，预览对全部列做摘要时触发懒加载，打到 `SimpleNamespace` 假引擎（unhashable） | 夹具补齐六列 |
| 覆盖读取类型 | 12 | `test_change_capture_deadline` 的覆盖替身是 `SimpleNamespace`，10-17 起 `covered_graph` 要求 `CoverageRead` | 替身改为构造 `CoverageRead`，令牌等字段放占位值 |
| 计算证明 | 21 | `test_computed_claim`（15）、`test_deterministic_proofs`（6）的假运行缺 `project_id`；`_completed_read` 直接读它，`AttributeError` 被宽泛捕获成 `deterministic_proof_required` | 假运行补 `project_id=None` |
| 缺数据库未标记 | 5 | 在函数体里取数据库或检查点环境变量 | 照现有写法加 `skipif`（TEST_DATABASE_URL / M2_TEST_CHECKPOINT_URL） |
| ScriptedProvider | 2 | 图把 `prompt_identity` 传给模型步骤；修好签名后又暴露 P76 后工具面从 27k 降到 9k，9 个容量结果到不了清理阈值 | 签名加参数；长运行用例用 12 个合成只读工具把工具面补回旧大小（64k 下仍满足“固定部分超过 F/2”和“6 个结果不触发、9 个触发清理”） |
| 其他替身 | 12 | 各缺一个后来新增的字段或查询分支：项目版本与资源需求（4）、品类锁与已签定义来源（3）、`AgentRun.versions`（2）、父运行技能延续 `scalars`（2）、研究子任务的 `result.read`（1） | 补字段或分支 |
| 断言改为现行行为 | 5 | S2 分批接收（P13，10-17）：执行中可继续接收、保留初步结果时钟、不再查“已固定 Run”（3）；品类列表 10-31 加了三个聚合字段（1）；规范 schema 冻结守卫未登记 10-31 的 `model_configuration/dto.py`（1，钉到该版精确摘要，再改仍会失败） | 改断言并注明依据 |


## PG：清单里的用例怎么修的

修复前 115 个里 103 失败、4 错误，合计 107（`pg-before-classified.txt` 有每条的错误、拒绝原因和出错位置）。

| 类别 | 个数 | 原因 | 改法 |
|---|---|---|---|
| 读取绑定被拒 | 27 | 夹具用 `digest(registry.definitions())`（全部工具）作模型调用的工具定义摘要；读取证明要求它等于该调用已加载技能和运行范围对应的披露（`read_route_or_registry_changed`） | 改为 `disclosure_digest(registry, scope=...)`，与 P76 时其他夹具的写法一致 |
| 断言改收到 `VERSION_CONFLICT` | 6 | 同上，夹具在到达被测的拒绝点之前先因摘要不符被拒 | 同上，断言不改 |
| T0 来源“工具或技能允许操作已变化” | 18 | `claim_fixture`、`claim_ledger` 换了加载的技能但没重算摘要；撤回测试追加加载技能也没记入披露链（证据命令 9、撤回 8、对账 1） | 按已加载技能重算；追加技能时照网关做法写披露链；`claim_ledger` 的范围触发方式改为与运行一致（10-17 起存储层核对） |
| 缺检查点库/Temporal 程序 | 11 | 以前的运行器没给 `PDOS_CHECKPOINT_DATABASE_URL`、`.local/tools/temporal`（错误 4、失败 7） | 运行器补齐；补齐后 4 条通过，其余 7 条摘要用例暴露下一行的 D243 问题，一并修 |
| D243 活动取消保护 | 3 | 11-04 起 `KernelActivities.advance()` 进入 `activity.shield_thread_cancel_exception()`，直接调用时不在活动上下文里，报 `RuntimeError` 后记 `INTERNAL_ERROR`（`test_activity` 3，另含上一行的摘要 7） | 照 D243 已改的两处，替换 `shield_thread_cancel_exception` 与 `is_cancelled` |
| 计算证明 | 21 | 见无库部分（这些在 D242 清单里，其实不需要数据库） | 同上 |
| 其他替身 | 7 | `ScriptedProvider` 2、`scalars` 2、`versions` 2、研究子任务 `result.read` 1（同无库部分） | 同上 |
| 回放基准 | 2 | 10-31 起 `project_context` 把 `work_state` 冻结进运行版本；旧断言把 attach 前后的版本摘要当作回放不变的基准 | attach 后取基准，并断言 attach 只改了 `work_state*` 键、引用不变 |
| 零散 | 8 | 门函数文本改比现行 head（s0_0854）；平台关联目标须是 G0 变体（P23）；开发预算夹具按 P67 的 16k 输出预算和 64k 窗口；会话历史无权限时为 403（10-22）；EXPLAIN 需渲染展开参数；品类采用剧本宿主置空 `model_step`（10-31 起图优先走网关）；知识检索两条语句数为 3 条批量读取加每事务一次 `SET LOCAL jit=off` | 各自改夹具，原有断言意图不变 |
| 产品缺陷 | 3 | 见下 | 未修，记 D258、D259 |
| 环境性能 | 1 | 见下 | 未改阈值 |

**8 条撤回与 P68**：清单原来把它们归给 P68（撤回不查版本）。实测失败点在建 T0 写入时的来源校验（`execution.py:verify_source`），撤回路径本身不查提示词或技能版本；夹具改好后 8 条全部真实执行通过。P68 在 W8 仍未实施，与这 8 条无关。

**S1 的 6 个候选摘要夹具**（`test_domain_candidates_pg.py`）：HEAD 上已通过（`pg-before-extra-classified.txt`）。

**`test_project_current_context_pg`**：整文件按顺序在 HEAD 和修复后都全过，没有复现顺序依赖。

## 剩余失败与归因

| 用例 | 归因 |
|---|---|
| `test_review_fixes.py::test_actual_owner_and_definers_are_non_superuser` | D258：`s0_0776` 新建的 SECURITY DEFINER 函数 `change_receipt_key_bound` 属主是迁移账号（测试库里是超级用户），没有转给 `pdos_next_owner`。测试的属主规则已按 10-31 的两个已审维护角色更新，零超级用户属主不放松 |
| `test_knowledge_retrieval_authority_pg.py::test_knowledge_original_scan_proof_precedes_http_metadata`、`test_knowledge_dependencies_pg.py::test_updated_knowledge_dependency_still_uses_actual_original_scan_proofs` | D259：知识条目的索引投影 `original_ids` 不含依据里的客户原件（为 `[]`），检索不把它纳入扫描核对，条目被判为不安全剔除。实测同一原件直接调 `safe_originals` 是安全的 |
| `test_recovery_pg.py::test_registered_family_search_and_authority_batch_stay_constant_sql_and_under_one_second` | 环境性能：检索 p95 1.47–1.53 秒（阈值 1 秒），两种核对模式 0.72/0.82 秒，SQL 语句数恒定。整机负载 13–18、测试库 1.1 GB（含历史克隆的数千租户）。未改阈值，性能验收按 P13 暂缓 |
