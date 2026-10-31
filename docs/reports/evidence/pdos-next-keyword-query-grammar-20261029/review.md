# Query-only 功能词最小改动复审

结论：通过本次有界复审，未发现阻断问题。此结论针对当前 SHA 固定的查询词法改动及已有证据，不表示完成正式业务验收或证明一般检索质量。复审仅读取源码/已有日志，独立复算 JSON 指标并执行无包导入的内存方法检查；未调用数据库、模型、embedding 或网络。

## 改动与索引边界

当前 `tokenizer.py`、`query.py`、`test_query_grammar.py` 的 SHA256 与 [implemented-manifest.json](implemented-manifest.json) 三项完全一致，也分别与已审草稿相同。反向移除新增查询策略常量、`analyze_query` 及 query.py 的三处接入后，两生产文件的 SHA 精确恢复为历史原始值：tokenizer `029845ab0af72b1af70e9747f281f6452b847cbb09ccf5474ba706f96d49016d`，query `fa2eae06378cf27492e0245d3e5965c9974e6cdf379035c0fddb4f867cc61307`。这比无输出的 git diff 更适合本工作区的复核，相关目录并非完整可用的 git 基线。

`tokenizer.py:88` 的 `analyze_query` 调用原 `analyze(value)` 后，只按完整 token 排除 19 个固定功能词，并同步 terms/counts/length/removed。原 `analyze`、代码识别、词典 fingerprint 与 `version()` 均未改变；`indexing.py:196` 的 work key、`:215` 的标题/正文分析继续使用原路径，不引入查询策略。因此源 term/title counts、DF 和索引版本没有因本改动改变，无需重建索引。已核对 [frozen-native-inputs.json](frozen-native-inputs.json) 全部 101 项当前 SHA 一致；新旧 HTTP trace 的 tokenizer_version 相同。

## 原始查询、编号、空词与版本

`query.py:68` 仅以原 `data.query` 生成派生分析；UUID 仍在 `:70` 从原字符串提取，`codes(value)` 仍对原文本运行。没有重写 SearchInput 或工具 arguments。`assistant_adapter.py:126` 的工具输入 digest 与 `embedding_query_binding.py:58,97,100–119` 的 query 原文/digest 绑定保持原路径，查询过滤不会改变已绑定 embedding 文本。

全功能词输入过滤后无词、无 code、无 UUID 时，在 `query.py:73` 按原 INVALID_PAYLOAD/422 拒绝，不回退噪声词。该守卫位于 require_context/_narrow 之后、prepare_read 及检索 SQL 之前；新增测试 stub 了前两者，不能把它解读成请求全程零 SQL。技术单字、事实否定与复合词由新增纯测试覆盖。

新关键词结果的 `ranking_version` 增加 `+query-function-words/v1`，`query_trace.query_policy_version` 为策略名加有序 19 词表的完整 SHA256 `fe393fbf44f5869929a51e7ce280dcbcf97611b2aa4aa3531f7d0d74c39aaeaf`。trace 保留 filtered terms、removed、codes/families 与原 index/code 版本。Hybrid 仍用既有 RRF 版本并继承 keyword trace；本轮没有验证其收益，也没有发起 semantic 调用。

## 已完成结果恢复

`assistant_adapter.py:189–201` 的 restore_search 不重新分析查询或重新排名：先校验已核发引用内容，再检查当前来源/依赖版本与可读性，成功则 deepcopy(previous)。因此旧结果没有 query_policy_version 也能保留其原 trace/ranking；已完成 READ 的历史结果不能当作新策略复评。持久账本仍以原 tool arguments digest 核对调用。

除源码与既有恢复测试核对外，复审从当前源码 AST 取出未修改的 restore_search，以内存 authority stub 验证：旧 metadata 原样保留、返回深拷贝、source_changed/source_dependency_changed 返回 SOURCE_STALE、撤权返回 SOURCE_UNAVAILABLE、篡改已存条目被拒绝。该检查不替代数据库恢复联验；本轮未重跑该联验。

## 已有验证与独立复算

[implemented-pure.log](implemented-pure.log) / [implemented-pure.xml](implemented-pure.xml)：22 passed，含 6 个新用例、12 个既有关键词用例、4 个 scope 用例；[implemented-ruff.log](implemented-ruff.log)：All checks passed。复审未重复执行这组已通过检查。

[native-live/native.log](native-live/native.log) / [native-live/tests.xml](native-live/tests.xml)：真实 PostgreSQL 测试 1 passed（21.02s），其中 HTTP 检索题 28 条，另含 owner/peer 私有来源控制；仅有 record_property 与 xunit2 兼容性警告。[native-live/baseline.json](native-live/baseline.json) 的 protected_before 与 protected_after 实际相等，runs/tool_calls/embedding 计数为零。此处引用既有实际执行证据，复审没有调用数据库。

复审未导入生产 scorer，直接用原题 expected/forbidden labels，经新 [bound-sources.json](native-live/bound-sources.json) 映射成 `(source_type, source_id)`，对 [observations.json](native-live/observations.json) 原始列表位置作集合交集，独立得到下表，与 [independent-native-metrics.json](independent-native-metrics.json) 完全一致。

| 指标 | 原 native-candidate2 | 当前 native-live |
|---|---:|---:|
| macro recall@5 | 0.9791666666666666 | 0.9791666666666666 |
| micro recall@5 | 0.9642857142857143 | 0.9642857142857143 |
| macro recall@10 | 0.9791666666666666 | 1.0 |
| micro recall@10 | 0.9642857142857143 | 1.0 |
| 来源命中 @5 / @10 | 27 / 27（分母 28） | 27 / 28（分母 28） |

固定分母为 24 个正向题、28 个 expected sources；4 个权限负向题 ENG/QUA/PRD/PUR-07 全部独立复核通过，4 个编号题 ENG-03、QUA-03、PRD-03、PUR-03 的 declared code 与 exact_id/exact_code 命中均通过。40 题中其余 12 题不属本检索评测。28 个 HTTP 样本 p50 69.7229165ms、inclusive p95 93.3413477ms，仅描述这次小样本。

题/语料 SHA 与原 [baseline.json](../pdos-next-eval-v0-20261029/native-candidate2/baseline.json) 及当前文件全部一致：corpus `846de93e8a8dd496ddc432b30220146dfc868b170da63ef331be83cdadc43920`，questions `4ad1d8b337bb496d30dd8c56ac8275f8e91f363c624d316b5ba95b3907217685`。24 份文档 body SHA、标题与 visibility 在原/新 bound sources 与当前 corpus 中一致；没有通过改题、标签或语料取得指标提升。

## 保留缺口与证据时序

QUA-04 中 qua_issue_record 位于第 1，qua_lab_report 位于第 10；后者仅刚进入 @10，仍未进入 @5。真实旧 HTTP 记录只证明它不在 top10；“14→10”的 14 是先前纯模拟估计，不是旧原生结果测得的完整排名。`料太湿` 与 `含水率` 的词汇不对应仍存在，不能声称语义缺口已解决。数据为作者编写的合成 artifact 题集，尚非人审 golden-case；未评估答案质量、混合检索收益、全来源覆盖或一般检索准确率。

[proposal.md](proposal.md)、[status.json](status.json) 与 implemented-manifest 中的 waiting 文案保留了当时阶段快照；当前已由 native-live 实测补齐。新 [result.md](result.md) / [final-checkpoint.json](final-checkpoint.json) 明确最终时序，不覆盖历史 baseline，不改活动清单或总审计。
