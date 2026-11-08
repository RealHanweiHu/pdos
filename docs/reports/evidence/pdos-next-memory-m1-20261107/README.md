# M1 情景回忆证据（2026-11-07）

环境：本 worktree 自建的独立临时库 `127.0.0.1:57122/pdos_test`（容器 `pdos-next-test-20261002-daa749e1`），显式 `TEST_DATABASE_URL`，未用 `.env`；没有调用真实模型或嵌入。

| 检查 | 结果 |
|---|---|
| 迁移 s0_0855 升级、降到 s0_0854、再升级 | 通过（加入 `memory_session_archived` 之前的版本；之后的版本只在原库原位补建，未做干净往返） |
| ORM 与数据库元数据比对 | 记忆表无差异（另有 7 条既有的钉钉/向量索引差异） |
| `tests/agent/memory`（存储门禁、召回、隔离、撤权、不进记忆、时效、转述约束、防注入、会话列表搜索） | 24 通过 |
| 受影响回归（工作状态、续接、会话 ACL、会话列表、反馈、上下文合同与预算、企业检索账本等 24 个文件） | 307 中 305 通过；2 个失败（只读工具数、假会话行）已修正后复跑通过 |
| 注册表与下发（disclosure、command_usage、tool_scope、prompt_cache 等） | 58 通过 |
| `tools/tests` | 记忆门禁评分器 8 通过；上下文准入工具数更新为 35 后通过；`test_local_host_profiles` 4 个失败为既有问题（相关文件未改） |
| 合同校验 `tools/validate_contracts.py` | 通过：87 操作、92 事件、67 验收编号 |
| 前端：`work-state-carry`、`memory-usage`、BFF 记忆路由及相关测试 | 96+ 通过；`tsc --noEmit` 与改动文件 eslint 通过 |
| `test_assistant_depth_integration` 2 个失败 | 在基线提交 69be8a19 上同样失败，既有问题 |

## 大回归（`tests/agent tests/core tests/originals tests/workflows tests/integrations tests/my_work` 与生命周期目录测试）

- 结果：4450 通过、105 失败、31 错误、77 跳过（1 小时 45 分）。失败与错误共 136 个，列在 [broad-failing-ids.txt](broad-failing-ids.txt)。
- 判别：在基线提交 69be8a19 的临时 worktree 上，用同一个库复跑这 136 个，其中 130 个同样失败（[broad-failing-on-base-too.txt](broad-failing-on-base-too.txt)），属既有问题。典型原因有：测试桩不认 `prompt_identity`、夹具给 AgentRun 传 `citation_ids`、缺 `M2_TEST_CHECKPOINT_URL` 等环境变量，以及 7 条既有的钉钉/向量索引元数据差异。
- 基线能过、本分支失败的 6 个，处理如下：
  - 2 个钉钉取消用例：复跑通过，属偶发；
  - 1 个 assistant_depth：测试用的假会话只能查固定次数，已改为开始运行时不多查记忆开关；
  - 2 个零技能下发工具数（34→35）：这是 `memory.search` 所有范围都下发的预期结果，已更新断言；
  - 1 个请求摘要：未填的 `memory_off` 不计入请求摘要，旧请求的摘要不变；测试的排除清单已补上它。
  - 6 个复跑全部通过。
- 对结构敏感的 4 个（`test_migration_matches_orm` 与三个 core 用例）在本分支上的报错都与记忆表无关，已逐个核对。

未做：真实 Temporal 下的索引工作流联调、HTTP/浏览器整链、亮暗/多尺寸检查；加入 `memory_session_archived` 之后的迁移干净往返。
