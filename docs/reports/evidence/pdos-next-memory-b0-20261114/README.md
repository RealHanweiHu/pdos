# 记忆评测 B0 补齐（2026-11-14）

依据：目标架构 §8.2–§8.3，清单 D474。代码在分支 `claude/memory-b0-eval-8dee3b`，只改评测文件，没有改产品代码、提示词、工具定义或迁移。

**状态：评测底座补齐了，四组 × 3 次的真实模型基线没有跑。这次会话的用量到了上限，只跑了 2 次冒烟。下面没有一个真实模型数字是基线。**

## 环境

- 独立临时库：`tools/local_environment.py` 新建的 `127.0.0.1:52491/pdos_test`（标记 `b174dbc9`，状态文件在本工作区 `.local/runtime.json`），迁移 head → base → head 通过，显式 `TEST_DATABASE_URL`，没有读 `.env`，没有用 57105。
- Temporal：本工作区 `.local/tools/temporal` 是指向主检出可执行文件的符号链接（只读使用）。
- 真实模型：MiniMax-M3，用主检出的运行时元数据（文件里只有密钥引用）；改绑到每次测试新建的合成租户。

## 新增了什么

- **上限组 `ideal`**（评测进程里的模拟，不是产品功能）：冻结目录换成题目标注的以往运行（`ideal_runs`，默认用 `expect_usage_runs`），每行带当时的回答和未完成事项；`memory.search` 对任何检索词都只返回这些运行，卡片同形、照常过逐条复核和使用清单。个人条目、`conversation.history`、提示词和工具定义与当前实现一样。
- **重复运行**：`PDOS_MEMORY_TIMELINE_REAL_REPEATS=3`，用 `-k rep0` 等选某一次；可以起 3 个进程并行。
- **T24 故障**：题目写 `fault: memory_unavailable` 时，`memory.search` 返回领域错误，信封里不带条目和目录。
- **预算保护**：`PDOS_MEMORY_TIMELINE_REAL_TOKEN_CAP` 按输出目录里已有观测的合计停止发起新题；`PDOS_MEMORY_TIMELINE_REAL_RUN_ALERT` 在单次超额时写 `STOP`，之后的题全部跳过。
- **新时间线**：TL-09 T03（领域里额定压力未定，记忆里有“按 120 PSI 考虑”）、TL-10 T04（观察“似乎是供应商换料”，代用：没有建质量问题单）、TL-11 T05（领域值 ≥35，记忆里有起草的 ≥40，代用：草稿在回答里，不是领域修订候选）、TL-12 T13（30 轮普通对话）、TL-13 T24；以上是调参集。TL-14–TL-16 是新验收集（结论里的说法、两人同一件事、改过一次的约定）。原来 8 条改为调参集。领域事实用真实的 `category.parameter.publish` 命令发布。
- **评分工具 v1**：按运行和按题汇总；同题重复不一致的格；组间“明显好”（一组每次写出、另一组一次没写出）和“分不开”；上限与当前实现的差距拆成“没检索到”和“检索到了没写出来”；关键事实分以往运行、条目、领域三种来源；T03–T05 的“保持领域状态”和“疑似把记忆说成事实”（正则，需人工看）；T13 的新条目和候选；T24 的降级说明。单元测试 25 通过（另有门禁评分器 8 通过），`ruff` 通过。

## 无模型回放门禁（[replay/result.md](replay/result.md)）

16 条时间线 × 4 组加格式检查，65 通过。七项零容忍门禁 0 次违反。召回 recall@5：不进记忆 0/15，基线 1（脚本模拟）15/15，当前实现 15/15（含按结论里的说法问 4/4，D482 之后）。领域读取 12/12 与标注一致；真实 `memory.search` 返回的记忆都带“不是业务事实”标注（6/6）。

一条未满足的预期（不是门禁）：只在测试进程里打开提议闸门时，TL-12 的 4 条“普通对话”提议有 2 条被收为候选，原因是准入词表含“我一般”“我习惯”。登记为 D540。

## 冒烟（[smoke/](smoke/)，不计入基线）

| 题 | 组 | 结果 | token |
|---|---|---|---|
| TL-14 q1（验收集） | 上限 | 写出“无刷”和“起订量”，用了目录里的 r1 | 68,200 |
| TL-13 q1（T24） | 当前实现 + 故障 | 答出 ≤62 dB(A) 和 1 m 空载；说了“个人记忆库本次返回 SOURCE_UNAVAILABLE”；用满 12 次模型调用，状态 partial | 267,230 |

冒烟后发现 T24 的降级说明词表漏了“个人记忆库”这种说法，已补进 TL-13（冒烟那次按旧词表判会算“没说明”）。TL-14 已被冒烟看过一次结果。

## 没做的，怎么恢复

四组 × 全部题 × 3 次：约 177 次运行，按以往每次 10–18 万 token 估约 2,200 万，上限 2,500 万。命令（在 `server/`，带隔离库环境变量）：

```bash
PDOS_MEMORY_TIMELINE_REAL=<主检出>/.local/comprehensive-minimax-20261023.json PDOS_MEMORY_TIMELINE_OUTPUT_DIR=<证据目录>/real PDOS_MEMORY_TIMELINE_REAL_GROUPS=no_memory,history_only,real,ideal PDOS_MEMORY_TIMELINE_REAL_REPEATS=3 PDOS_MEMORY_TIMELINE_REAL_TOKEN_CAP=24000000 PDOS_MEMORY_TIMELINE_REAL_RUN_ALERT=400000 python -m pytest -s tests/agent/memory/test_eval_memory_timeline_real_pg.py -k rep0
```

`rep1`、`rep2` 各起一个进程；跑完用 `tools/xiaopai_memory_timeline_baseline.py score-real <目录>` 评分。注意 T24 冒烟一次就用了 26.7 万 token，单次告警设 40 万。日志落盘前要去掉连接串（`withenv` 式脱敏）并做一次密钥扫描。

## 环境清理

临时库留着供后续运行；收尾用 `tools/local_environment.py destroy`（读本工作区 `.local/runtime.json`）。
