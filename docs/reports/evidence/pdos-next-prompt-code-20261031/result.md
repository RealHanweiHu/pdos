# 小Pai Prompt 一等代码闭环 · 2026-10-31

## 可用能力

- 主提示词从内联字符串抽为 `prompt_packages/versions/1.0.0.md`，与原 `SYSTEM_BASE` 逐字一致；`registry.json` 管理 `draft/active/published`、digest 和历史。生产激活版本仍为 **1.0.0**，历史为空。
- 新 Run 保存 `prompt_identities={key,version,content_digest,system_digest}`；旧 Run 的精确重放不回填或改写历史版本，原 digest 冲突守卫保留。
- 设置页只读展示主提示词与技能正文、源码位置及 digest；滚动区域可键盘聚焦，正文按文本转义，无在线覆盖按钮。
- `xiaopai_prompt.py` 提供 `list/show/new/register/diff/evaluate/activate/rollback`。版本与路径在写入前校验，注册表操作使用进程锁和原子替换；非法版本、孤儿文件、内容篡改、陈旧输入和并发激活均有负例。
- A/B 固定同一题集、工具、输出 schema 和生产准入逻辑；激活核对基线/候选内容及组合 digest、完整源码路径集合与 SHA-256。回滚只能恢复历史已发布版本。
- 案例审阅和资格绑定 `prompt_digest`；每个 `review_case_refs` 条目保存 `batch:index:prompt:<system_digest>`。T0 不读取本人私有资格决定，不绕 RLS；缺少绑定或跨 Prompt 使用资格失败关闭。
- 旧审阅/批准/撤销请求按当前或历史规范化 digest 恢复原回执；新命令删除字段不会冒充旧命令，未找到旧回执时不在线盲重试。

操作见[Prompt 代码工作流](../../../runbooks/pdos-next-prompt-code.md)。

## 必要证据

| 范围 | 结果 | 证据 |
|---|---|---|
| Prompt、注册表、执行绑定与图纯回归 | **76 passed** | 最终 `test_prompt_admin/test_prompts/test_execution_binding/test_graph` 输出；生命周期含路径逃逸、篡改、孤儿文件、并发与陈旧清单 |
| 受影响 PostgreSQL / T0 / RLS | **57 passed, 2 deselected** | [日志](backend-affected-pass.log)、[JUnit](backend-affected-pass.xml)，独立 `pdos_test`；2 条 deselect 为下述 HEAD 基线失败 |
| 最终 12 题 A/B | **control_status=passed，0 新增准入失败** | [报告](ab-release/report.json)、[摘要](ab-release/result.md)、[diff](ab-release/diff.patch)；固定 50 个输入源文件 |
| 合成副本激活与回滚 | 1.0.1-draft 激活后恢复 1.0.0 | [副本注册表](fixture-package/registry.json)；含实际激活/回滚历史，生产指针未改 |
| 离线工具 | **5 passed** | `test_xiaopai_prompt.py` 与上下文准入测试；无 provider/数据库调用 |
| 前端 helper / SSR | **7 helper + 10 SSR passed** | 旧恢复两类命令、Prompt 展示/转义/键盘区域及既有模型设置组件 |
| 前端静态与构建 | TypeScript、受影响 ESLint、生产构建通过 | `next typegen && tsc --noEmit`；ESLint 0 errors；`next build --webpack` exit 0 |
| 合同 | 87 operations / 92 events / 63 acceptance IDs 通过 | `payloads.schema.json` 已包含 `prompt_digest`；`validate_contracts.py` 通过 |
| 复审 | 三份 **APPROVE** | code-reviewer、python-reviewer、react-reviewer 最终均无剩余问题 |
| 交付源指纹 | 34 个源文件 | [source-manifest.json](source-manifest.json)；排除无关根 README 和证据/状态文件 |

A/B 的 `quality_status=not_scored`：当前只证明离线控制无新增准入失败，**不证明真实回答、引用、真实权限端到端或真人任务质量通过**。真实模型与 provider 调用为 0。

## 已核对的 HEAD 基线失败（不计本任务回归，也不宣称整仓全绿）

在独立、未修改的 HEAD `0602ec6b` 工作树、同一隔离数据库上复现以下 10 条失败：

1. `test_new_claim_can_be_adopted_read_and_replayed_in_original_run[False]`
2. `test_new_claim_can_be_adopted_read_and_replayed_in_original_run[True]`
3. `test_t0_claim_and_link_whole_run_revert_is_one_named_confirmation_and_replay`
4. `test_whole_run_revert_blocks_changed_or_frozen_target_without_partial_undo[human_edit]`
5. `test_whole_run_revert_blocks_changed_or_frozen_target_without_partial_undo[submitted]`
6. `test_whole_run_revert_blocks_changed_or_frozen_target_without_partial_undo[signed]`
7. `test_whole_run_revert_tail_failure_rolls_back_claim_link_counter_and_proof`
8. `test_mixed_claim_item_link_run_reverts_once_with_actual_receipts`
9. `test_mixed_revert_finish_failure_rolls_back_and_original_confirmation_retries`
10. `test_mixed_run_fixed_definition_dependency_blocks_all_effects`

前两条来自 `project_context` 写入 `work_state` 后旧断言未覆盖；其余撤回类用例为既有模型披露夹具不一致。详见[基线说明](baseline-checks.md)和[基线撤回日志](baseline-reversal.log)。最终 57 条只排除前两条 parametrized 用例，后八条不纳入本任务验收范围；未修改其期望或放宽生产守卫。

## 过程与剩余边界

- 首轮受影响套件为 55 passed / 12 failed，逐项修复后得到上述 57 passed。早期全量 `tests/agent_kernel` 运行因候选变更被主动停止，[中断日志](process-backend-agent-kernel-interrupted.log)不计通过。
- 未做真实模型质量评估、真人试点、生产激活、生产部署、真实外发、数据库迁移或 git push。无新增真实资格。
- 本轮页面验证为 SSR、类型、ESLint 和生产构建，未另做浏览器截图/多尺寸验收。
- 隔离 PostgreSQL 容器身份与 marker 已核对；Docker 重启后的宿主端口更新为 53993，数据库始终为独立 `pdos_test`，未回退 `.env`。
- 根 `README.md` 有与本任务无关的分支发布说明改动，未纳入实现、证据源指纹或本闭环声明。
