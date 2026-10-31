# RAG §8.3 四类结构化任务结果

本子任务在共享候选中补齐阻塞清单、案例表、评审清单、承诺表；已有固定版本差异表保持原比较实现。主会话统一执行测试、PostgreSQL、前端及闭环验证，本文件不把未执行的测试列为通过。

## 可用能力

- 模型选择登记的 `task_result.format` 与固定列，每个单元格选择本轮已提取的 citation + 逐字 quote，或 citation + `field_path`。结构化选择必须位于已读取且与当前复核来源完全一致的 `facts` / `content` 中，元数据与来源标识不是业务事实。
- 非责任人、非明确登记日期的单元格可提交有界分析 `text`，服务器分别输出 `content_kind`、显示文本与 `basis_text`。分析不会伪装成原文引用或登记事实；引用身份、逐字依据和字段匹配由服务器校验，分析的语义忠实度仍需要人工问题集评价。
- 责任人仅选择 `owner_id` / `responsible_id` / `executor_id` 登记字段，记录者 `actor_id` 与引文中的名字不构成责任分配；责任人与明确登记日期字段均不能被模型分析覆盖。缺责任人显示“未指定”。其他缺项显示“未记录”或“待确认”，空表也会给出未知行。
- 单元格引用自动并入已核对来源集合；未签发、未提取、原文不符、结构化值变化的单元格降为待确认并给出 partial。来源最终撤回或失效沿用原回答的正文清除与 partial 规则，不保留依赖表格。普通对话仍通过服务器 `ordinary_answer` 清除模型伪造的 assistant 结构。
- 前端按固定列渲染横向可滚动的表格，分析与原文依据分开，逐格来源链接可展开来源区，历史与适用性待重核提示可见。来源区先保留每个 citation 的一张卡片，避免额外片段挤掉后续表格的来源。
- 导出的 `task_result.markdown` 保留分析、原文依据、未知与固定引用 ID。主会话已把它接入现有本人私有工作成果保存接口；未新增共享写入、候选批准或外发权限。

## 文件归属

- `pdos-next/server/pdos_next/enterprise_search/assistant_schemas.py`
- `pdos-next/server/pdos_next/enterprise_search/assistant_answer.py`
- `pdos-next/server/pdos_next/enterprise_search/task_result.py`
- `pdos-next/server/tests/enterprise_search/test_task_result.py`
- `pdos-next/server/tests/enterprise_search/test_task_result_pg.py`
- `pdos-next/web/src/components/pai/answer-task-result.tsx`
- `pdos-next/web/src/components/pai/answer-task-result.test.mjs`
- `pdos-next/web/src/components/pai/answer-sources.tsx`

稳定主提示由上下文代理在其 `graph.py` 归属中接线；工作成果保存由主会话在 `work_products.py` 归属中接线。本子任务未修改这两个文件、公共 API、权限查询或唯一活动清单。

## 验证与待执行检查

已执行本子任务五个 Python 文件的 Ruff：通过；已执行所改既有文件的 `git diff --check`：通过。随后按主会话追加授权运行后端纯测试 28 项与前端渲染测试 8 项：全部通过。后端采用 `.venv/bin/python -m pytest`；首次 `.venv/bin/pytest` 入口因旧绝对路径 shebang 失败，改用现有解释器运行，没有修改运行环境。没有执行 DB、模型、embedding、网络外发、构建或 Git 提交/推送。

新增纯测试覆盖四种登记结构、逐字定位、登记字段、分析/引用分离、未知/空项、责任人/日期不覆盖、伪造/失效/被篡改依据、私有 Markdown 与普通对话伪造清除。新增 PostgreSQL 用例使用现有合成 provider 与真实运行/读账本/领域命令，覆盖四种格式的读取→HTTP恢复→本人私有表格保存、虚构引用、最终撤回与真实等待记录的责任人/状态/日期字段；无真实模型调用。新增前端渲染用例覆盖四格式、未知、分析/依据分离、转义、不可核对输入与历史待重核。

已执行：

```text
server: .venv/bin/python -m pytest tests/enterprise_search/test_task_result.py -q  # 28 passed
web: node --test src/components/pai/answer-task-result.test.mjs
```

主会话待统一执行 `tests/enterprise_search/test_task_result_pg.py` 与现有受影响检查。PostgreSQL 只允许主会话核对过的显式 `TEST_DATABASE_URL`（现有 53502/pdos_test、marker `f117bb5b-b3d7-4286-aaec-c54d9255e96b`、head `s0_0830`），不回退 `.env`，无迁移。本子任务没有运行数据库，因此尚不声明 PostgreSQL 或完整业务闭环验证通过。

## 边界

逐格身份、引用和字面依据可核不等于所有分析语义已被证明。人工问题集与真实岗位资料质量评价仍是独立缺口，本次没有写入 golden-case，也未授予模型新资格、写权限或正式验收状态。
