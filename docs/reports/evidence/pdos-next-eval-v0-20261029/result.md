# 小Pai题集 v0 与首轮离线召回基线

按用户“你帮我制作就好了”制作了[52道候选题](../../../evaluations/xiaopai-v0/question-bank.md)：工程、品质、生产、采购各10题，多轮上下文12题；配套24份中文合成资料、逐题预期来源/行为与[评分规程](../../../evaluations/xiaopai-v0/rubric.md)。这些是贴近岗位的合成场景，未登记为golden-case或员工真实问题。

40道岗位题中，24道正向检索题、4道权限负向已实际执行；8道路由和4道业务流程题单列未执行。12道上下文题具备具体多轮记录、73个事实/约束锚点、二元检查及0–2评分；两档候选F现为48000/64000（原8192/16384的固定前缀准入失败已保留，见下）。CTX-01/12的自包含原始回放材料重建后为33,682/29,836估算tokens，逐字SHA与当前预算函数核对通过，[当前输入核对](context-input-validation-v2.json)、[展开输入](context-expanded-inputs.json)、[可重放核对脚本](validate-context-inputs.py)。未将输入长度核对当作模型质量通过。

## 实际关键词基线

同一独立 `127.0.0.1:53502/pdos_test`、head `s0_0852`，每轮新的合成租户。经原生命令登记24份Artifact，再从普通权限源目录绑定source ID、revision、content_hash；相关性标签在检索前固定。用原句调用普通用户HTTP检索、limit=10，不调用模型。

[最终实际执行](native-candidate2/native.xml)、[完整基线](native-candidate2/baseline.json)、[实际来源绑定](native-candidate2/bound-sources.json)、[逐题检索记录](native-candidate2/observations.json)：

- 24正向题、28个应命中来源，top5/top10均命中27个；macro recall@5/@10均为 **97.92%**，micro均为 **96.43%**，MRR为 **97.92%**。
- 4道权限负向均未返回禁止来源；另有4个控制确认这些私有来源确已索引、本人可读而同事不可读。4道完整编号均进入原编号通道并命中对应来源。
- 28次原句HTTP检索p50 **68.99ms**、inclusive p95 **96.57ms**；这是本批24份资料的一次混合问句采样，不是模型回答时延或13类正式性能复测。
- 查询前后10张受保护表的计数和行摘要保持；新Run/ToolCall/模型预算/EmbeddingCall均为0，所有返回来源的固定版本与hash匹配原生绑定。

| 岗位 | 正向题 | 来源数 | macro recall@5/@10 | micro recall@5/@10 |
|---|---:|---:|---:|---:|
| 工程 | 6 | 8 | 100.00%/100.00% | 100.00%/100.00% |
| 采购 | 6 | 6 | 100.00%/100.00% | 100.00%/100.00% |
| 生产 | 6 | 6 | 100.00%/100.00% | 100.00%/100.00% |
| 品质 | 6 | 8 | 91.67%/91.67% | 87.50%/87.50% |

唯一正向缺项为 **QUA-04**：“料太湿”原句查到了问题登记，实验室报告未进top10。该题两份预期来源保留，查询词中没有“含水率”；未因本轮结果调题、改正向标签或改排序。这是后续比较查询表达/混合检索的具体样本。

## 本轮发现与修正

[首轮基线](native-candidate1/baseline.json)保留原结果：宏平均97.92%、私有来源泄漏0；四个全局空结果断言未满足，一道编号题仅走关键词，另外几道编号被内部子号或版本号部分掩盖。

1. **负向判分范围**：设计§7.6采用OR检索，问句通用词可召回其他有权读取的资料。原4题只应排除私有目标。仅将4题expected_empty改false并说明理由；题干、身份、forbidden目标和所有正向预期不变。[原件](labels-before-scope-correction/questions.json)、[逐字段差量](labels-scope-correction.json)、[独立核对](independent-input-review.json)保留。计分支持仅来源排除的负向，仍不进入recall分母。
2. **完整编号**：原规则未识别FA-2026-029等字母与数字分隔的完整前缀。修正并升为`enterprise-codes/v2`，沿原工作键/重建批次更新，普通词与纯日期仍排除；未改权限、排序或数据库约束。[精确patch](identifier-rule.patch)、[前后SHA](identifier-rule-delta.json)。最终检查同时核对完整解析编号与实际exact_code命中。

[32项纯检查](pure-final.xml)通过（计分20＋编号/分块/工作流12）；[6项实际回归](identifier-regression.xml)通过：旧规则投影→原重建升级、原编号优先、私有/租户、Outbox与重建、撤回与成员撤权、损坏投影。初版18项计分检查属于最终20项子集，不重复累计。[7个Python文件Ruff](ruff-final.log)通过；首轮交付文件SHA及一致性核对见[原候选清单](final-manifest.json)。数据库未新增迁移，前端未改动。

## 使用与后续

从仓库根目录运行`pdos-next/server/.venv/bin/python pdos-next/tools/xiaopai_recall_baseline.py --output-dir /tmp/xiaopai-eval-new-run`，输出目录须为新目录，使用已核对的本地测试环境。[题集入口与完整命令](../../../evaluations/xiaopai-v0/README.md)。计分只读标签和观测，不改变来源预期或审阅状态。

此基线只覆盖Artifact资料的原句检索；既有13类来源能力仍由各自原生矩阵证明。正式人工审阅、30–50道真实员工问题及试点、路由/答案/流程/上下文质量和真实混合检索收益尚未执行。真实模型、embedding及真实外发继续关闭。

## 续验增量：可执行窗口与原生隔离

完整生产初始61工具、system与输出schema固定段的15%余量后下界为35,069 tokens；原F8192/16384两档12题均由生产`fit_messages`在调用前拒绝。题集改用候选F48000/64000（W54048/70048），仅确认固定前缀加当前问题的下界准入；完整历史/工作状态/原生READ绑定与模型质量仍待执行。原件、逐题结果和不改变题干/事实/锚点的字段差量见[准入核对](context-admission/result.md)、[修正记录](context-admission/profile-correction.json)。原始展开材料的逐字SHA未变，不用原始长度冒充实际压力。

新题集两份本人私有原文经原生登记与实际隔离提取图，在读到正文后由离线故障端尝试`skill.load`、任务写入、根因批准与共享，均被工具隔离拒绝，13表计数/摘要保持；[实际PG两项](native-contracts/pg-run1.xml)通过。这是服务器隔离合同检查，不计为题目理解或答案质量通过；四道动作的原生机制证据见[精确映射](native-contracts/review.md)。
