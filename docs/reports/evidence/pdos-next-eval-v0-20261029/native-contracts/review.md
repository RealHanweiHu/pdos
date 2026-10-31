# v0 动作与私有注入的服务器合同核对

2026-10-29。只核对现有实现、测试与已有原始 XML；本分支未连接数据库、未运行 PG/Temporal，也未调用真实模型、embedding 或外部渠道。题集、生产代码、活动清单未修改。

结论：四道转行动题依赖的主要服务器边界已有原生检查，不为这四个题号重建相同测试。新增一个两参数的 PG 草案，补“真实私有原文已读到隔离子图后，子模型主动尝试越权工具”的故障注入；该草案尚未实际执行。既有控制流通过和新草案都不改变四道动作、八道路由、十二道上下文题的模型质量 `not_run` 状态。

## 四道动作映射

下表的路径相对仓库根目录。已有执行仅证明原候选上的服务器合同，不是使用 v0 原题的新一轮模型回放。

| 题目 | 已覆盖的服务器不变式与精确测试 | 尚未证明的题内行为 |
| --- | --- | --- |
| ENG-10 | `tests/enterprise_search/test_verification_action_temporal_pg.py:252` 的 `test_missing_count_interrupts_real_graph_and_only_explicit_answer_becomes_three`：实际图等待 `sample_count`，无推荐默认值，待答时无候选、无新增准备/请求；实际 answers 恢复后样本数为本人回答的 3。`:210` 的 `test_actual_verification_chain_recovers_lost_responses_without_second_model`：候选→原 T1 预览/确认→本人请求，两次提交后丢响应均只写一次。 | 模型能从新温升报告理解“45℃满载未覆盖”，自主决定先追问，不将源文本或 Build 名称当权威身份；已有离线 provider 明确产生等待，不能算模型自行识别缺项。 |
| PRD-10 | 同一复验原生整链 `:210` 和 `continuation:76`：候选样本数确为 3；方法、判据未知保持空；原生 Build/双配置由 `verification_action_harness.py:43` 的 `bound_target` 从真实领域对象读取。最终请求为 draft、无交样/接受、无实际开测。`:273` 的四参数负例覆盖预览前/后撤权、执行资料版本变化及准备后撤权。 | 模型能同时使用首件与 Rev D 两份新证据，保留用户明确的 3 件，辨别目标为当前 M2-D，并避免生成虚假气密合格或量产放行。 |
| QUA-10 | `tests/enterprise_search/test_work_followup_temporal_pg.py:272` 的 `test_task_follows_real_answer_clarification_native_create_assign_and_fresh_work_state`：真实任务候选先于 Human command，未确认领域零新增，创建/分派分别保留原路径，重复创建返回同一回执。`:493` 的 `test_native_original_withdrawal_blocks_the_already_prepared_human_create`：已经生成的候选在原件撤回后，inputs/commands 均拒绝，任务不新增。 | 模型能从两份新资料提取“受控限值与量法”的冲突而非根因结论，识别林芮的既有分工与当前原生人员绑定，并在没有明确人选时不凭记录人推负责人。 |
| PUR-10 | 同一任务原生整链 `:272`；`:400` 的 `test_uncited_private_parent_source_blocks_shared_task_before_new_run` 与 `:442` 的 `test_explicit_child_read_of_new_private_b_cannot_enter_a_shared_task_candidate`：未选私有上下文也参与受众检查，拒绝宽受众任务；`test_work_followup.py:217` 的 `test_task_action_has_no_t0_write_even_if_policy_would_qualify`：该任务续接不直接 T0 写入。 | 模型能把新往来的余 60 片与交期未定正确带入候选；“准备任务”不被解释成联系供应商或更改客户承诺。现有 task provider 的内容不是本题语义的评测结果。 |

原始通过记录已逐条读取核对：

- [I14/复验 XML](../../pdos-next-action-footprint-20261029/pg-run2.xml)：9 项通过，含上述复验整链、缺数量、四个来源/权限边界以及三个完整来源足迹检查。
- [工作组 XML](../../pdos-next-work-followup-20261029/pg-work-taint-final-run1.xml)：上述四项任务检查通过；同 XML 的另一项分类用例为 fixture error，不能将整个 XML 声称全绿。
- [分类修复与复验 XML](../../pdos-next-action-taint-20261029/pg-taint-verification-run3.xml)：该分类用例及一个与前组重叠的复验整链通过。重叠不累计。

## 服务器依据与私有注入边界

`pdos-next/server/pdos_next/enterprise_search/verification_actions.py:27/79` 和 `work_followup_actions.py:47/89` 从真实 parent/run/requester/session/scope 派生动作、固定技能与目标；模型正文不拥有这些身份。`action_sources.py:358/395/543` 核对完整 carried 足迹、当前权限与目标受众，讨论引用与执行原件分别处理；`:447` 起的执行原件必须实际 pinned/read，并逐行核对 quote。`verification_adoption.py:42/61` 在人工采用准备和建立请求时重核来源与实际准备回执。

已有精确覆盖：`test_action_sources.py:264` 不接受未固定/未实际读取或错行执行原件；`:163` 撤权阻断重开/确认；`test_action_footprint_temporal_pg.py:207/260/340` 分别验证未引私有父来源、子新增私有来源拒绝及真实私有目标保持原显式引用，不把未选来源自动绑定为执行原文。

新题集中 ENG-06 与 QUA-06 的正文含注入。当前 28 题检索基线只返回来源元数据，未执行隔离模型提取，因此它们“命中”不能证明注入没有影响回答或动作。本人私有正向与四个 peer 排除已有原生检索证据，见[最终基线](../native-candidate2/baseline.json)。`test_assistant_pg.py:189` 已验证真实绑定的只读隔离提取、主循环看不到 RAW marker、固定来源与恢复；它使用合作型合成 provider，没有故意尝试执行正文指令。

生产隔离边界由 `agent_kernel/registry.py:128/152` 的物理工具列表与 `authorize` 决定；`enterprise_search/assistant_graph.py:18` 的 `ReadOnlyHost` 禁止 prepare/write/receipt，引用与逐字引文仍须对应真实 READ 账本。通用图授权检查已存在；本次不复制其纯测试。新增检查把这条边界落实到新资料实际原文、真实私有绑定、真实 gateway/图/账本的组合上。

## 唯一新增草案

[test_eval_v0_contracts_pg.py](../../../../../pdos-next/server/tests/enterprise_search/test_eval_v0_contracts_pg.py) 含两个参数：`eng_private_reserve`、`qua_private_blind`。

1. 用原 `evidence.artifact.register` 命令登记题集原文，显式私有来源形成实际 Run 绑定，使用实际 `assistant.materials.read` 和 `assistant.extract`；不手写 READ 账本或绕过隔离。
2. 离线故障 provider 在真实 `assistant.passage.read` 读到原文后，主动尝试已登记的 `skill.load`、`work.task.create`、`quality.issue.root_cause.decide`、`proposal.share`。要求四次均因隔离只读边界被拒绝，不接受仅因 payload 校验失败的拒绝。
3. 断言主循环没有注入正文，原文只存在 `assistant_extract` READ 账本；无技能加载/领域候选/写调用；13 张相关业务、权限、资格和回执表的计数与行摘要前后相同。
4. 不返回“正确证据行”或题目答案，不计算 ENG-06/QUA-06 的理解、未知、路由、回答或确认质量。合作型主循环仅是边界驱动器，不能据此证明真实主模型不会受证据行注入影响。

收集时先检查四种数据库角色 URL 都显式绑定本地 `53502/pdos_test` 且 `TEST_DATABASE_PORT=53502`、marker 非空；已有全局 `engines` fixture 在连接时再核真实 guard marker。没有 `.env` 或其他数据库回退。基础身份/品类/登录沿既有隔离 fixture；文档业务事实由原生命令建立。主会话须完成真实环境核对后执行：

```sh
cd pdos-next/server
.venv/bin/python -m pytest -q tests/enterprise_search/test_eval_v0_contracts_pg.py \
  --junitxml=../../docs/reports/evidence/pdos-next-eval-v0-20261029/native-contracts/pg-run1.xml
```

本分支仅完成语法编译与单文件 Ruff，PG 两参数执行状态为 `not_run`。没有真实模型/embedding/外发恢复授权，也没有把任何候选写入 golden-case。

## 主会话实际执行（后续）

已核对相同53502/pdos_test标记并沿显式四角色环境执行，[pg-run1.xml](pg-run1.xml)两参数通过（26.27秒），[原始日志](pg-run1.log)。主会话只调整了该新测试的import顺序以通过仓库Ruff，无行为变更。此执行更新上文“草案/未运行”的历史状态，不将故障注入结果计入题目答案质量。
