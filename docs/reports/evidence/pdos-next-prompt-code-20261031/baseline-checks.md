# HEAD 基线对照

基线提交：`0602ec6b`。使用独立临时工作树和同一已核验 `pdos_test`，未修改基线源码。

执行：

```sh
pytest -q tests/agent_kernel/test_proposal_context_admission_pg.py::test_new_claim_can_be_adopted_read_and_replayed_in_original_run
pytest -q tests/preproject/test_evidence_revert_pg.py tests/products/test_definition_item_revert_mixed_pg.py
```

结果：

- 回放两条 parametrized 用例在 HEAD 均失败；差异为 `project_context` 产生的 `work_state` 与 `work_state_digest`，并非 `prompt_identities`。
- 撤回/混合定义共八条用例在 HEAD 均失败于 `VERSION_CONFLICT: 实际登记工具或技能允许操作已变化`；[原始日志](baseline-reversal.log)保留。
- 因而结果清单列出的十条失败属于已存在基线问题。最终任务回归只排除已核实的范围，不把这些条目写成通过，也不修改它们的期望来制造全绿。

临时基线工作树已在核对后移除；主工作树、生产 Prompt 指针和真实业务库未受影响。
