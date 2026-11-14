# 记忆提议 Prompt A/B（真实模型，按规则判定）

每题每组只跑 1 次；回答写得好不好、有没有编造没有评分。

| | A：提示词 1.0.0，原 memory.search 说明，提议闸门关闭 | B：提示词 1.1.0，新 memory.search 说明，提议闸门对 1.1.0 打开 |
| --- | --- | --- |
| **既有评测题（记忆时间线，当前实现）** | | |
| 题数 | 9 | 9 |
| 结束状态 | {"partial": 5, "completed": 4} | {"partial": 4, "completed": 5} |
| 回答里写出全部关键事实的题 | 4/5 | 5/5 |
| 检索到全部关键事实的题 | 4/5 | 5/5 |
| 该说“查不到”时说了 | 2/2 | 2/2 |
| 按本人约定的语言起草 | 1/1 | 1/1 |
| 回答被换成“未通过核对” | 0 | 0 |
| 以“运行预算已用完”结束 | 0 | 0 |
| 向用户追问的问题数 | 3 | 0 |
| 多出来的记忆提议（存下的候选） | 0 | 0 |
| 平均 token | 116064.2 | 145815.6 |
| 合计 token | 1044578 | 1312340 |
| 门禁违反 | 0 | 0 |
| **提议探针** | | |
| 探针数 | 14 | 14 |
| 该提议的：提了 / 总数 | 0/6 | 4/6 |
| 漏提的探针 | P1、P2、P3、P4、P5、P6 | P3、P6 |
| 不该提议的：误提 / 总数 | 0/7 | 0/7 |
| 模型提了、被服务器拒收的 | 无 | not_verbatim_user_fragment、not_verbatim_user_fragment、trigger_not_corrections、trigger_not_owner_words |
| “只是讨论”探针 | {"N8": "clean"} | {"N8": "clean"} |
| 向用户提的问题数（全部探针） | 17 | 21 |
| 其中不该提议的探针 | 10 | 13 |
| 回答里说“已记住”之类的探针 | N8、P1、P3、P5 | 无 |
| 没有正常完成的探针 | N4、N5、N6、P2、P4、P6 | N4、N5、P2、P6 |
| 工具调用次数 | 183 | 132 |
| 合计 token | 1563154 | 1179162 |

## 逐个探针

| 探针 | 期望 | A | B | B 存下的候选 |
| --- | --- | --- | --- | --- |
| N1 | none | clean；问 1；53740 token | clean；问 1；17167 token | — |
| N2 | none | clean；问 3；35298 token | clean；问 2；36625 token | — |
| N3 | none | clean；问 0；15010 token | clean；问 0；31265 token | — |
| N4 | none | clean；问 0；87048 token | clean；问 3；81972 token | — |
| N5 | none | clean；问 0；253493 token | clean；问 3；198727 token | — |
| N6 | none | clean；问 3；114375 token | clean；问 3；58691 token | — |
| N7 | none | clean；问 3；35449 token | clean；问 1；36697 token | — |
| N8 | void | clean；问 2；123016 token | clean；问 0；32701 token | explicit/convention/global「周报用表格形式呈现。」 |
| P1 | propose | miss；问 0；15095 token | hit；问 0；16081 token | explicit/convention/global「给客户的报告一律用英文」 |
| P2 | propose | miss；问 0；242132 token | hit；问 3；211892 token | explicit/convention/global「周报一律用表格形式输出，不用段落式叙述」 |
| P3 | propose | miss；问 1；16950 token | miss；问 0；32717 token | — |
| P4 | propose | miss；问 0；250104 token | hit；问 0；50488 token | explicit/alias/global「“老王那个泵”指的是 12V 便携充气泵那个型号。」 |
| P5 | propose | miss；问 0；15316 token | hit；问 0；50496 token | explicit/convention/global「回复一律先给结论，再给过程」 |
| P6 | propose_proactive | miss；问 4；306128 token | miss；问 5；323643 token | — |

## 逐题（既有评测题）

| 题 | A：状态 / 答出 / token | B：状态 / 答出 / token |
| --- | --- | --- |
| TL-01 q1 | partial / True / 69955 | partial / True / 151587 |
| TL-01 q2 | completed / True / 157457 | completed / True / 204039 |
| TL-01 q3 | partial / True / 242903 | partial / True / 244503 |
| TL-02 q1 | completed / True / 50245 | completed / True / 53300 |
| TL-02 q2 | completed / False / 33089 | completed / False / 80947 |
| TL-04 q1 | partial / False / 69582 | partial / False / 183971 |
| TL-06 q1 | partial / False / 152080 | partial / False / 128375 |
| TL-07 q1 | completed / False / 68624 | completed / False / 56391 |
| TL-08 q1 | partial / False / 200643 | completed / True / 209227 |
