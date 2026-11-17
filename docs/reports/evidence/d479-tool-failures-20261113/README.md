# D479 工具出错时的处理（2026-11-13）

分支 `pdos-next/design-v1.1`，改动在工作区，未提交、未推送。工作区里同时有别的会话未提交的改动（`graph.py` 等，D382），本次只在其上加了下面列的几处。

## 改了什么

| 问题 | 改法 | 位置 |
|---|---|---|
| 模型给出未登记的工具名，整批调用失败、运行终止 | 未登记的名称只是这一个调用的错误（`FORBIDDEN_SCOPE`，`reason_key=tool_not_registered`），退回给模型；同批的合法调用照常执行。分组、生成工具消息、记录结果三处都不再因它抛错 | `agent/kernel/graph.py` 的 `tools` 节点 |
| 读取失败后结果仍显示“完成” | 新增通用规则：主图里，某个读取工具在本次运行的最后一次调用以 `SOURCE_UNAVAILABLE` 或 `SOURCE_STALE` 结束时，模型标成“完成”的结果改为“部分完成”，并在未完成事项里写明是哪个读取。模型写的摘要不动 | 新增 `agent/kernel/read_failures.py`；`graph.py` 的 `verify` 节点在原有核对之后调用 |
| 通用写入的参数校验失败会让整轮崩溃 | `DomainCommands.command` 改用 `tool_arguments`，校验失败退回 `VALIDATION_FAILED` 并列出字段路径，不回显提交的内容（与 D245 对读取的做法相同） | `agent/kernel/domain_adapter.py` |

## 通用规则的边界

这条规则是本次定的，如需放宽或收紧请指出：

- 只算“来源不可用”和“来源已失效”两种。参数写错、越权、对象不存在这些是模型自己能看到并据此作答的，不降级。
- 同一个工具后面有一次读成功，就不算失败。
- 只在主图生效；研究、抽取、MCP 等隔离子任务不变。
- 研究、企业检索、项目当前依据原有的专门核对在前，照常执行；它们已经把结果降为部分完成时，本规则不再追加说明。
- 只改状态和未完成事项，不判断模型的文字里是否引用了失败的内容。

## 没有做

- 读取失败在账本里统一记 `SOURCE_UNAVAILABLE`（`host.read` → `kernel_release_call`）。数据库函数只接受 6 个原因码（`s0_0705`），要如实记录 `VALIDATION_FAILED`、`SOURCE_STALE`、`NOT_FOUND` 等需要新迁移放宽这张表，本次没有动。
- 没有跑真实模型。带库的测试 11-13 当天没有跑，11-14 已补跑，见下面“带库复验”。

## 验证

- 新增 `tests/agent/kernel/test_graph_tool_failures.py` 8 例。修复前：未登记工具名的用例以 `DomainError: 工具未登记` 在 `tools` 节点崩溃；读取失败的两例得到 `completed`。修复后 8 例通过。
- 无库回归：`tests/agent/kernel`、`tests/agent/memory`、`tests/workflows`（排除 `*_pg.py`）共 2401 通过、10 跳过、5 失败、267 个错误。
  - 5 个失败都在 `test_evidence_adapter_unit.py::test_model_cannot_supply_privacy_or_provenance_fields`：原来断言裸 `ValidationError`，按新行为改为断言 `VALIDATION_FAILED` 和字段路径，改后通过（该文件与新用例、`test_tool_arguments.py` 共 49 通过）。
  - 267 个错误全部是 `KeyError: 'TEST_DATABASE_URL'`，即需要数据库而本次没有提供，未运行。
- `ruff check` 改动的产品文件和新测试文件无错误；`test_evidence_adapter_unit.py` 的导入排序提示是原有的。

## 带库复验（2026-11-14）

- 环境：`tools/local_environment.py` 的 `create` 新建的独立临时库 `127.0.0.1:61698/pdos_test`（容器 `pdos-next-test-20261002-c7be5a3f`），状态文件 `.local/d479-test.json`，显式 `TEST_DATABASE_URL`，没有读 `.env`，没有动仓库原有的 `.local/runtime.json` 和别的会话的库。建库时迁移链升到 head、降到 base、再升到 head 通过（记录在 `../pdos-next-bootstrap-c7be5a3f/`）。
- 范围：`tests/agent/kernel`、`tests/agent/memory`、`tests/workflows` 全部，含 `*_pg.py`。本机有 Temporal 开发服务程序（`.local/tools/temporal`），所以插件路径的用例实际运行了（`test_xiaopai_graph_plugin_pg.py` 16 例、`test_graph_plugin_pilot.py` 7 例、`test_category_adoption_graph_plugin_pg.py` 和 `test_mcp_graph_plugin_pg.py` 各 1 例）。
- 结果：3119 通过、35 跳过、0 失败、0 错误，用时 1 小时 10 分。候选是 11-13 的工作区（含别的会话未提交的改动），复验后没有再改产品代码。
- 跳过的 35 例里核对了 26 例的原因：真实模型运行需显式开启的 13 例（`PDOS_GRAPH_PLUGIN_REAL_TRIAL` 1 例、`PDOS_MEMORY_TIMELINE_REAL` 12 例），需要已核对的本地进程档的 9 例，要求绑定到 53502 那个库的 4 例（`test_eval_v0_handle_candidate_pg.py`）。其余 9 例没有逐个核对原因。
- 临时库留着，收尾时用状态文件 `.local/d479-test.json` 销毁。
