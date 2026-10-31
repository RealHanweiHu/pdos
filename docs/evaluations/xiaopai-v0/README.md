# 小Pai评测题集 v0

已制作 **52题**：工程/品质/生产/采购各10题，多轮上下文12题；配套24份合成资料。时间锚点为2026-10-29。

直接阅读[题目总表](question-bank.md)、[逐题事实查阅表](question-review.md)及[评分规程](rubric.md)。机器输入为[岗位题](questions.json)、[资料](corpus.json)和[上下文题](context-questions.json)。

最新关键词候选已实际执行原28道HTTP检索题。24道正向题的宏平均recall@5为 **97.92%**、@10为 **100%**，来源加权值分别为 **96.43%/100%**；4道权限负向均未返回禁止来源，4道完整编号均命中编号通道。QUA-04实验室报告为第10名，前5缺口仍保留，题目、预期与24份资料均未改。query-only功能词过滤通过22项纯检查，新一轮p50/p95为69.72/93.34ms（每题一次HTTP样本、不含回答生成）；[完整结果与独立复算](../../reports/evidence/pdos-next-keyword-query-grammar-20261029/result.md)保留旧基线。8道路由、4道转行动及12道上下文回答质量另待执行。

[完整基线、来源绑定与验证证据](../../reports/evidence/pdos-next-eval-v0-20261029/result.md)包含首轮结果、判分范围修正和编号规则v2修复。上下文两组原始长输入约33.7k/29.8k估算tokens，含可复现构造与逐字哈希。完整生产固定前缀准入下界35,069，已将不可用的F8192/16384修正为候选F48000/64000，原件与检查保留；已完成12题×两档24格原生控制回放：18格完整绑定、5格部分绑定、1格预算不足，34项控制/纯检查通过；原六项等17项原生补验及174项纯检查通过。部分绑定与容量停止均保留，回答质量未评分。见[本地回放与修复](../../reports/evidence/pdos-next-context-native-v0-20261029/result.md)。

后续补齐实际 WorkTask/PlanTask 与项目历史后，定向4格控制回放通过：CTX-04两档均从部分绑定补为完整绑定；CTX-11低档仍正确停止于预算，高档保留候选且零新增任务。它是新候选的定向补验，不改写此前24格结果；详见[当前任务与项目历史续验](../../reports/evidence/pdos-next-project-tasks-context-20261029/result.md)。

2026-10-30另完成CTX-09/CTX-12两档共4项定向原生控制：真实9项目录的独立cursor读取6项后失败；自然JSON分片与业务项不一致，CTX-09仍保留partial。CTX-12两档均实际读取8×4695字符，低档在admission 48379>48000时停止，高档完成读取；未生成模型质量分。[夹具、原生结果和历史失败](../../reports/evidence/pdos-next-context-fixture-completion-20261029/result.md)保持独立范围，不改写历史24格。

CTX-09原题的精确3→6/9不是产品分页合同：冻结自然目录为9325字符、估算2451tokens，小于4000单条上限，因此一次完整返回。现标注`needs_case_revision`，旧partial不改；已提供[原生绑定修订候选](../../reports/evidence/pdos-next-ctx09-binding-audit-20261030/ctx09-revision-draft.md)和[可复算核对](../../reports/evidence/pdos-next-ctx09-binding-audit-20261030/result.md)，区分业务cursor与按体积切片的result.read，未将候选自动审阅通过。

同一32k确定性向量的来源级权限物化对照已完成，真实ANN四配置仍无稳定收益，默认继续关键词；[检索机制与性能记录](../../reports/evidence/pdos-next-ann-quality-performance-20261029/result.md)不作为真实embedding质量。

在仓库根目录使用既有已核对本地pdos_test运行新一轮：

```sh
pdos-next/server/.venv/bin/python pdos-next/tools/xiaopai_recall_baseline.py --output-dir /tmp/xiaopai-eval-new-run
```

输出目录须不存在；资料经原生命令登记到新的合成租户，查询沿普通权限接口。此工具不调用模型。独立复算计分可使用`pdos-next/tools/xiaopai_recall_metrics.py`，输入岗位题JSON及该轮的`bound-sources.json`、`observations.json`。

本批仍为候选题，未登记为人工审阅的可信题集；真实模型、embedding和外部渠道保持关闭。
