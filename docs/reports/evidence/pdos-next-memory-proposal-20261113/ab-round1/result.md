# 记忆提议 Prompt A/B（真实模型，按规则判定）

每题每组只跑 1 次；回答写得好不好、有没有编造没有评分。

| | A：提示词 1.0.0，原 memory.search 说明，提议闸门关闭 | B：提示词 1.1.0，新 memory.search 说明，提议闸门对 1.1.0 打开 |
| --- | --- | --- |
| **既有评测题（记忆时间线，当前实现）** | | |
| 题数 | 未跑 | 9 |
| 结束状态 | 未跑 | {"partial": 2, "completed": 5, "failed": 2} |
| 回答里写出全部关键事实的题 | 未跑 | 3/5 |
| 检索到全部关键事实的题 | 未跑 | 3/5 |
| 该说“查不到”时说了 | 未跑 | 1/2 |
| 按本人约定的语言起草 | 未跑 | 1/1 |
| 回答被换成“未通过核对” | 未跑 | 0 |
| 以“运行预算已用完”结束 | 未跑 | 0 |
| 向用户追问的问题数 | 未跑 | 0 |
| 多出来的记忆提议（存下的候选） | 未跑 | 0 |
| 平均 token | 未跑 | 97828.9 |
| 合计 token | 未跑 | 880460 |
| 门禁违反 | 未跑 | 0 |
| **提议探针** | | |
| 探针数 | 未跑 | 14 |
| 该提议的：提了 / 总数 | 未跑 | 6/6 |
| 漏提的探针 | 未跑 | 无 |
| 不该提议的：误提 / 总数 | 未跑 | 0/7 |
| 模型提了、被服务器拒收的 | 未跑 | trigger_not_owner_words |
| “只是讨论”探针 | 未跑 | {"N8": "clean"} |
| 向用户提的问题数（全部探针） | 未跑 | 19 |
| 其中不该提议的探针 | 未跑 | 11 |
| 回答里说“已记住”之类的探针 | 未跑 | P3 |
| 没有正常完成的探针 | 未跑 | P2、P6 |
| 工具调用次数 | 未跑 | 123 |
| 合计 token | 未跑 | 1164537 |

## 逐个探针

| 探针 | 期望 | A | B | B 存下的候选 |
| --- | --- | --- | --- | --- |
| N1 | none | 未跑 | clean；问 1；35129 token | — |
| N2 | none | 未跑 | clean；问 3；37028 token | — |
| N3 | none | 未跑 | clean；问 0；15578 token | — |
| N4 | none | 未跑 | clean；问 2；55511 token | — |
| N5 | none | 未跑 | clean；问 2；153878 token | — |
| N6 | none | 未跑 | clean；问 2；82264 token | — |
| N7 | none | 未跑 | clean；问 1；57195 token | — |
| N8 | void | 未跑 | clean；问 1；92551 token | explicit/convention/global「周报一律用表格形式呈现。」 |
| P1 | propose | 未跑 | hit；问 0；32187 token | explicit/convention/global「给客户的报告一律用英文（面向客户的报告一律使用英文；内部讨论与内部留存文档不受此限）。」 |
| P2 | propose | 未跑 | hit；问 3；134793 token | explicit/convention/global「周报一律用表格形式输出：板块、事项、状态、本周进展、下一步、负责人、依据各成一列，后续周报不再用段落叙述。」 |
| P3 | propose | 未跑 | hit；问 1；52759 token | explicit/convention/global「出报价对比时以含税价优先：先列含税单价与含税总额，再列未税价及其他口径，并注明币种、日期、地区、渠道、是否含运费；无含税数据时标注未知，不做推断。」 |
| P4 | propose | 未跑 | hit；问 1；67085 token | explicit/alias/category「“老王那个泵”指 12V 便携充气泵那个型号（当前品类：汽车充气泵）。」 |
| P5 | propose | 未跑 | hit；问 0；33543 token | explicit/convention/global「回复一律先给结论，再给过程。」 |
| P6 | propose_proactive | 未跑 | hit；问 2；315036 token | proactive/convention/global「样件编号按「项目-批次-序号」三段编排，不含日期；出处为你口头确认两次，公司资料中未查到。」 |

## 逐题（既有评测题）

| 题 | A：状态 / 答出 / token | B：状态 / 答出 / token |
| --- | --- | --- |
| TL-01 q1 | 未跑 | partial / True / 140525 |
| TL-01 q2 | 未跑 | completed / True / 130753 |
| TL-01 q3 | 未跑 | failed / False / 155141 |
| TL-02 q1 | 未跑 | completed / True / 70397 |
| TL-02 q2 | 未跑 | completed / False / 36561 |
| TL-04 q1 | 未跑 | completed / False / 70503 |
| TL-06 q1 | 未跑 | failed / False / 134816 |
| TL-07 q1 | 未跑 | completed / False / 51575 |
| TL-08 q1 | 未跑 | partial / False / 90189 |
