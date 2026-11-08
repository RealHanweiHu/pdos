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

未完成：`tests/agent tests/core tests/originals tests/workflows tests/integrations tests/my_work` 的大回归在会话结束时仍在运行，结果未记录；未做真实 Temporal 联调、HTTP/浏览器整链和亮暗/多尺寸检查。
