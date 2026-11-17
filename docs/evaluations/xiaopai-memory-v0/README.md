# 小Pai 记忆评测：时间线候选 v0

依据：[记忆系统评估与目标架构](../../design/2026-11-12-xiaopai-memory-system-assessment-and-target-architecture.md) §8，[P121](../../design/2026-10-08-pdos-next-design-confirmation.md#p121)，实施蓝图 B0。

**16 条时间线、33 个探针，另有 17 道由真实模型回答的问题，全部是候选，未经人工确认，不是可信题集。** 内容全部合成，只有两个人物：甲（`owner`）和乙（`peer`），同一品类的两名成员。按整条时间线划分调参集（`dev`）和验收集（`holdout`）：

| 集 | 时间线 | 说明 |
|---|---|---|
| 调参集 | TL-01–TL-08 | 2026-11-13 写的 8 条。原划为验收集的 TL-02、TL-04、TL-07 已被首次基线和 P122 后重跑看过两次，2026-11-14 起改为调参集（文件里有 `split_note`） |
| 调参集 | TL-09–TL-13 | 2026-11-14 新增，补 T03、T04、T05、T13、T24 |
| 验收集 | TL-14–TL-16 | 2026-11-14 新增。调参时不要看它们的结果；TL-14 在冒烟时被看过一次 |

机器输入是 [timelines.json](timelines.json)。

## 现在能测什么，不能测什么

目标架构稿 §8.2 列了 T01–T28。当前的无模型回放只能覆盖其中一部分：

| 状态 | 用例 | 说明 |
|---|---|---|
| 无模型回放已覆盖（部分） | T01、T02 | 只测“能不能找到那次运行”，不测回答对不对。T02 只有本人自己的会话，没有正式决定和团队备忘 |
| 同上 | T12、T14 | 只测两名成员之间的隔离；撤权后的派生物没有覆盖 |
| 同上 | T15 | 只测“改了条目，下一次运行用新的”；没有测生效延迟 |
| 同上 | T16 | 只测常驻注入和条目检索两处；候选、向量、简报没有覆盖 |
| 同上 | T17、T18 | 资料里的指令不产生候选；索引滞后时不返回空结果 |
| 另外覆盖 | AT-71 的不进记忆部分；评估稿缺口 C1 | 不进记忆的会话不被召回；对话里的长期交代能否成为候选 |
| 需要真实模型（2026-11-14 已有题） | T03、T04、T05、T13、T23、T24 | 考的是回答内容。T03、T05、T24 的领域事实用 `category.parameter.publish` 发布；T04 没有建质量问题单，只考记忆里的观察会不会被说成根因；T05 的“修订候选”是一次回答里的草稿，不是领域里的修订候选记录。无模型探针只核对领域读取和“不是业务事实”的标注 |
| 需要目标架构的能力，现在无法执行 | T06–T11、T21、T22、T25–T28 | 依赖范围条目、历史时点查询、冻结分流、简报、经验沉淀、条目核对、升降建议 |
| 没有放进时间线 | T19、T20 | 并发写入和故障恢复更适合专门的测试；现有记忆测试已有期望版本号和请求编号的用例 |

## 四个组

| 组 | 含义 |
|---|---|
| `no_memory` | 基线 0：所有会话开着“不进记忆” |
| `history_only` | 基线 1 的模拟：评测脚本直接按关键词搜本人以往运行的原话加回答摘要，取前 5 条。**这是脚本里的模拟，不是产品功能**，也不经过行级权限（脚本里按本人过滤） |
| `real` | 基线 2：当前实现 |
| `real_proposals_open` | 当前实现，只在测试进程里打开“对话提议”的提示词版本闸门，用来看闸门打开之后服务器的确定性准入会怎么判 |

目标架构稿 §8.3 的“理想记忆”组只在真实模型运行里有（`ideal`，见下）。

## 真实模型的问题

时间线里的 `questions` 只在真实模型运行里用（`probes` 只在无模型回放里用）。做法：

- 历史照无模型回放那样用脚本固定，所以两组面对的是同一段过去；
- 每道题由真实模型在一个新会话里回答，走注册的小Pai 工作流；
- 跑四组：`no_memory`（基线 0）、`history_only`（基线 1）、`real`（基线 2）和 `ideal`（上限）。真实模型下的 `history_only` 不是无模型回放里的脚本模拟：它只在评测测试的进程里把 `memory.search` 的处理函数换成“搜本人原话加回答摘要”，并去掉个人条目和情景目录；工具名、参数、提示词不变，产品的工具注册表不动；
- `ideal` 也只在评测进程里注册，是模拟，不是产品功能：冻结目录换成题目标注的以往运行（`ideal_runs`，默认 `expect_usage_runs`），每行带当时的回答和未完成事项；`memory.search` 对任何检索词都只返回这些运行。个人条目、`conversation.history`、提示词、工具定义与 `real` 相同；
- 题目可以用 `groups` 限定只在哪些组跑，用 `fault: memory_unavailable` 让本题的 `memory.search` 失败、信封不带条目和目录（T24）；
- 每题每组可重复 N 次（`PDOS_MEMORY_TIMELINE_REAL_REPEATS`）；
- 模型追问时，脚本只回一句固定的话（“只根据你能查到的以往记录回答，查不到就直接说明”），并记下追问。

判定仍然按规则：

| 标注 | 怎么判 |
|---|---|
| `facts` | 每组是一个关键事实的几种写法，去掉空白后逐字查找。“回答里写出”只看模型自己写的摘要和结果正文；“检索到”还算上运行结果里记录的工具返回。全部在回答里写出才算这题答出 |
| `expect_usage_runs`、`expect_usage_notes` | 服务器记录的使用清单里有没有这些运行或条目 |
| `forbidden_usage_runs`、`forbidden_usage_notes` | 使用清单里出现即违反门禁（越权、删除残留、不进记忆仍读取） |
| `forbidden_answer` | 回答里逐字出现时只做标记，留给人看，不算门禁（模型自己猜的也可能撞上） |
| `expect_unknown` | 回答里有没有“查不到”一类的说法 |
| `expect_language` | 回答里中文字符的占比 |
| `fact_source` | 关键事实来自以往运行（`episode`，默认）、个人条目（`note`）还是领域（`domain`），分开统计 |
| `expect_status` | 回答里有没有“未定”“未核实”一类的词（T03、T04） |
| `forbidden_claims` | 正则；命中记为“疑似把记忆说成事实”，否定句也可能命中，需人工看 |
| `expect_degradation_notice` | 记忆故障时回答里有没有说明没读到记忆（T24） |
| `expect_no_new_notes` | 运行之后没有新条目、没有收下的候选（T13） |
| `expect_usage_note_revisions` | 使用清单里的条目版本不低于此值，低于即门禁 `correction_stale` |

回答有没有编造、表述好不好，没有评分。问题都由甲提出，因为测试夹具只给甲分配了模型预算。

## 文件格式

每条时间线有 `events`（按顺序执行）和 `probes`（事件之后逐个执行）。

事件：

| `op` | 作用 | 主要字段 |
|---|---|---|
| `parameter` | 某人经命令接口发布一个品类参数（领域事实） | `key`、`name`、`unit`、`acceptance_criterion` 等 |
| `run` | 某人发起一次运行并收尾 | `actor`、`goal`、`summary`、`unfinished`；可选 `memory_off`、`page_material`（作为页面资料附在原话后面）、`memory_candidates`（脚本代替模型给出的提议）、`index: false`（不建索引，模拟滞后） |
| `note` | 本人手写一条记忆 | `actor`、`kind`、`text` |
| `revise` | 本人修改一条记忆 | `note`、`text` |
| `forget` | 本人删除一条记忆 | `note` |

探针：

| `probe` | 做什么 | 记录什么 |
|---|---|---|
| `search` | 发起一次新运行，调用 `memory.search` | 返回了哪些运行、属于谁、哪些条目、是否索引滞后 |
| `resident` | 发起一次新运行，读它冻结的运行信封 | 常驻带入了哪些条目和文字，最近情景目录里有哪些运行 |
| `candidates` | 查指定运行产生了几条记忆候选 | 候选数、服务器给的拒收原因 |
| `domain` | 发起一次新运行，经注册的 `category.parameters.list` 读参数 | 有没有这个参数、验收标准 |

探针上的标注：`expect_runs`、`forbidden_runs`、`expect_notes`、`forbidden_notes`、`expect_texts`、`forbidden_texts`、`expect_catalog`，以及 `kind`（决定适用哪条门禁）和 `covers`（对应的用例编号）。`kind` 为 `capability` 的探针只记录目标能力的现状，不算门禁。

## 怎么跑

需要一个已核对的独立临时库（`tools/local_environment.py` 建的 `pdos_test`），不读 `.env`。输出目录必须不存在。

```bash
cd tools && ../server/.venv/bin/python xiaopai_memory_timeline_baseline.py run --output <输出目录> --state <环境状态文件>
```

只重新评分已有的输出：

```bash
cd tools && ../server/.venv/bin/python xiaopai_memory_timeline_baseline.py score <输出目录>
```

真实模型运行是选择性开启的，会调用真实模型并产生费用。设置 `PDOS_MEMORY_TIMELINE_REAL` 为本机模型运行时元数据文件的绝对路径（密钥留在本机安全存储里，测试不读取），`PDOS_MEMORY_TIMELINE_OUTPUT_DIR` 为已存在的输出目录，然后在隔离库的环境变量下运行 `tests/agent/memory/test_eval_memory_timeline_real_pg.py`；可用 `PDOS_MEMORY_TIMELINE_REAL_GROUPS`、`PDOS_MEMORY_TIMELINE_REAL_ONLY` 选组和选题。不设置第一个变量时这个文件整体跳过。评分：

```bash
cd tools && ../server/.venv/bin/python xiaopai_memory_timeline_baseline.py score-real <输出目录>
```

无模型回放不调用模型和嵌入服务，回答正确性、任务完成率、重复澄清次数、真实时延都不评分。

首次结果见 [B0 证据 11-13](../../reports/evidence/pdos-next-memory-b0-20261113/README.md)；四组、每格 3 次的结果见 [B0 证据 11-14](../../reports/evidence/pdos-next-memory-b0-20261114/README.md)。
