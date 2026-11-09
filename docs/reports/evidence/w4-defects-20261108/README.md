# W4 缺陷与测试债清理（2026-11-08）

分支 `claude/elated-shirley-4a1ed9`，基于 `pdos-next/design-v1.1` 的 `d6abcbf2`（迁移 head `s0_0861`）。只做本地提交，未推送。测试都在 `tools/local_environment.py create` 新建的隔离 `pdos_test` 上运行，`TEST_DATABASE_URL` 显式指向它，没用 `.env`，没有调用真实模型。

## 结论

| 项 | 判断 | 处理 | 证明 |
|---|---|---|---|
| D258 定义者函数属主 | 产品缺陷 | `s0_0862`：转给 `pdos_next_owner`，升级末尾拒绝其他属主 | `test_review_fixes::test_actual_owner_and_definers_are_non_superuser` |
| D259 知识条目依据原件 | 产品缺陷 | 投影缓存补上依据原件（`indexing._scan_targets`） | `test_knowledge_retrieval_authority_pg`、`test_knowledge_dependencies_pg` 两个用例；语句数用例仍为 4 |
| D260 降到 base 失败 | 迁移缺陷 + 测试环境 | ① `s0_0800` 降级重放 `s0_0784` 原始输入；② `s0_0727` 指纹排除扩展成员（用户 11-08 定）；③ 测试库 `max_locks_per_transaction=256` | [d260-roundtrip.txt](d260-roundtrip.txt)：`create` 的 head→base→head 与 seed 通过 |
| D261 ORM 漂移 7 项 | 迁移缺口 + 模型未登记 | `s0_0863` 补钉钉摘要租户索引；6 个 HNSW 索引在模型登记 | [migration-roundtrip.txt](migration-roundtrip.txt)：比对 0 项 |
| D262 `test_material_proofs_pg` 19 个 | 测试过时（P76 第 4 项） | 夹具记录已加载技能对应的披露摘要 | 19 个通过 |
| D284（新）摘要表属主 | 产品缺陷 | `s0_0863` 转给 `pdos_next_owner`，升级末尾检查表属主 | 同 D258 用例新增的表属主断言 |
| D285（新）证据根查无报 P0002 | 产品缺陷（错误类别） | `s0_0864`：查不到来源报 23514 | `test_category_source_consumers` |
| `citation_ids` 27 个 ERROR | 测试过时 | 构造运行行时去掉 `citation_ids` | 27 个通过（无库） |
| `test_extracted_claim_pg` 8 个 | 测试过时（资格绑定提示词） | 派发夹具 `active_prompt=True` | 8 个通过；派发/比对/解析 3 个文件不变 |
| CTX-04 F48000/F64000 | 测试过时（P76 第 4a 项） | 脚本化模型桩按项目运行断言披露 | 2 个通过 |
| `test_context_x3_full_disclosure` 2、`test_development_budget_pg` 1 | D27 已修 | — | 复跑通过 |
| `test_business_audience_summary` | 测试过时（G0 已分享定义受众） | 改扣同事从未获得的工程配置 | 通过 |
| D42 `test_source_views` | 测试过时（P91） | 给个人读取打桩，断言 200/422/405 | 通过 |
| D33 共用夹具 2 个 + `test_current_policy` 3 个 | 测试过时（项目受众 = 当前成员） | 经负责人团队命令移出/加回成员；`team_fixture.add_member` | 通过；`team_fixture` 全部调用方 15 个通过 |
| `test_build_execution`、`test_builds` 放行批准各 1 个 | 测试过时（10-10 时无处理器） | 与另外四个操作同样期望 422 格式错误 | 5 个、26 个通过 |
| `test_public_capture_minimal` 1 个 | 测试过时（`rules.py` 认规格经工程配置到 BOM 的路径） | 测试按同一规则计算 | 通过 |
| `test_definition_parent_lineage_pg` 1 个 | 测试过时（钉死 head `s0_0756`） | 与执行前的版本比较 | 通过 |
| D56 往返日志 | 证据丢失风险 | 改名 `.txt` 并改链接 | 已入库 |
| 检索 p95（`test_recovery_pg`） | 环境 | 未改，阈值不动（P13 暂缓） | 3.9 秒时库 77 MB、整机负载 27–32、另有 4 个会话的测试库在跑；PG 全量里通过 |
| D286 `test_graph` 共享资产栅栏 | 既有（`d6abcbf2` 同样失败） | 未修，已登记 | 多出一个产品的依赖时钟 |
| D287 部分观察评审链路 | 既有（`d6abcbf2` 同样失败） | 未修，已登记 | 记录部分观察时 `MISSING_REQUIRED_EVIDENCE` |
| D288 外部交接投影 | 需显式开关 | 未改，已登记 | 带 `PDOS_EXTERNAL_HANDOFF_LINK=1` 通过 |

新迁移 `s0_0862`–`s0_0864` 是占位号，接在 `s0_0861` 之后；**集成时按真实 head 重排**。

## 验证

见 [results.txt](results.txt)：无库全量与 PG 全量的计数、与 `d6abcbf2` 的对比，以及剩余失败的逐条归因。基点数字来自同一机器上 `git archive d6abcbf2` 的副本和它自己 `create` 的隔离库。
