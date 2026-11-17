# 定向复现记录 · 2026-11-16

基点 `f7425553`，使用当时工作树，迁移 head `s0_0892`。测试前记录 `git diff --binary HEAD -- server web/src packages contracts` SHA-256 `bf56d8d2f4a7fdbf08832f0e2935da0f1b8a398a2145a771e4fca7ce86a6d961`；收尾复核一致，另有 20 个当时未跟踪的源码/测试文件参与。显式 `TEST_DATABASE_URL` 指向新建并核对 Docker 身份、端口与数据库标记的 `127.0.0.1:51055/pdos_test`。需要的 Temporal 实例和检查点仅供本次测试使用。模型为本机脚本替身，不读取 `.env`，不连接预览库执行测试。

主批：`153 passed, 10 failed in 509.16s`。文件范围为 `tests/agent/kernel/` 下的 `test_xiaopai_graph_plugin_pg.py`、`test_graph_tool_failures.py`、`test_graph_final_turn.py`、`test_minimax_wire.py`、`test_proposal_runs_pg.py`、`test_proposal_context_pg.py`、`test_personal_run_sources_pg.py`、`test_personal_context_pins_pg.py`、`test_project_current_context_pg.py`、`test_project_work_task_context_pg.py`，以及 `tests/categories/preproject/test_g0_handoff_pg.py`、`tests/projects/work_pg/test_g0_continuation.py`、`tests/projects/npi/test_pump_project_pg.py`、`tests/projects/npi/test_framework.py`。

## 当前候选的确定性故障

- `test_project_current_context_pg.py` 中 4 个失败：当前项目及未知阶段、两档显式资料选择以及项目版本更新。
- `test_project_work_task_context_pg.py` 中 6 个失败：当前任务、任务版本、来源撤回、撤权、相邻项目隔离、读取边界。失败发生在上下文准备，未到这些被断言的后置行为，不能把这些行为都说成分别损坏。
- 单独用正确的 `postgresql+psycopg://` 检查点 URL 重跑 `test_project_current_context_temporal_pg.py`。真实 HTTP 接受运行后，`XiaopaiGraphWork` 在 `xiaopai.prepare_context` 报 `DetachedInstanceError`，返回 `failed / INTERNAL_ERROR`。抛出之前没有进入模型节点。

共同异常：`Bootstrap.project_context` 在退出 `with self.store.transaction(scope)` 后尝试 `run.versions.get("npi_g0")`。`AgentRun` 属性已过期且已离开会话，先读取该属性就报错。该分支是相对基点的新增代码；普通已有项目问答也会执行判断。定位：[bootstrap.py](../../../../server/pdos_next/agent/kernel/bootstrap.py#L317)。此证据来自开发候选，没有把它归到 `57859` 的旧预览。

## 新品类的正反对照

- `test_category_adoption_graph_plugin_pg.py::test_adoption_signal_resumes_the_waiting_graph_once` 通过。脚本模型准备 T1 候选后工作流等待，本人确认才提交品类和回执；同一 Outbox 消息投递两次只恢复一次，且不给 AI 建品类后的授权。未覆盖真实模型能否起草这个候选。
- 技能选择和工具范围补跑：组内 18 个先通过（含上述新品类用例）；关闭技能的拒绝断言首次在两套测试并行时碰到另一个租户增加的全库行数，主批结束后单独重跑通过。另一个失败首次是检查点驱动配置错误；修正隔离测试配置后复现上面的项目上下文缺陷。这两次首轮的测试环境问题不计为产品断点。
- 独立无库探针在相同个人范围有／无 `category_framing` 下校验工具披露，并以实际 `DomainReads` 对四个披露读取做拒绝复现。没有改工具权限或冻结提示。
