# 记忆时间线候选：无模型回放

用脚本驱动本地隔离库上的真实入口（运行启动、收尾、条目接口、memory.search、运行信封），只按规则判定服务器返回了什么。没有调用模型或嵌入服务；回答正确性、任务完成率、重复澄清次数和真实时延都没有评分。

## 零容忍门禁

| 门禁 | 违反次数 |
| --- | ---: |
| cross_access | 0 |
| injection_write | 0 |
| unconfirmed_write | 0 |
| deletion_residue | 0 |
| fake_zero | 0 |
| memory_off_access | 0 |
| correction_stale | 0 |

## 情景召回（recall@5，按规则判定）

| 组 | 全部 | 调参集 | 验收集 | 用原话的说法问 | 用结论里的说法问 |
| --- | --- | --- | --- | --- | --- |
| 基线 0：全部会话不进记忆 | 0/15 | 0/12 | 0/3 | 0/11 | 0/4 |
| 基线 1（模拟）：只搜本人以往运行的原话和回答摘要 | 15/15 | 12/12 | 3/3 | 11/11 | 4/4 |
| 基线 2：当前实现 | 15/15 | 12/12 | 3/3 | 11/11 | 4/4 |
| 当前实现，测试进程内打开对话提议的版本闸门 | 15/15 | 12/12 | 3/3 | 11/11 | 4/4 |

`history_only` 是评测脚本里的模拟检索，不是产品路径；每组只有个位数的题，比例不代表稳定的召回率。

## 目标能力的现状（不是门禁）

| 组 | 时间线 | 探针 | 目标 | 观察到 | 是否达到 | 服务器给的拒收原因 |
| --- | --- | --- | --- | --- | --- | --- |
| no_memory | TL-01 | p4 | `{"catalog_has_unfinished": true}` | `{"catalog_has_unfinished": false}` | 否 | — |
| no_memory | TL-03 | p2 | `{"admitted": 1}` | `{"admitted": 0}` | 否 | memory_candidate_prompt_not_released |
| no_memory | TL-08 | p3 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |
| no_memory | TL-14 | p2 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |
| real | TL-01 | p4 | `{"catalog_has_unfinished": true}` | `{"catalog_has_unfinished": false}` | 否 | — |
| real | TL-03 | p2 | `{"admitted": 1}` | `{"admitted": 0}` | 否 | memory_candidate_prompt_not_released |
| real | TL-08 | p3 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |
| real | TL-14 | p2 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |
| real_proposals_open | TL-01 | p4 | `{"catalog_has_unfinished": true}` | `{"catalog_has_unfinished": false}` | 否 | — |
| real_proposals_open | TL-03 | p2 | `{"admitted": 1}` | `{"admitted": 0}` | 否 | trigger_not_explicit_remember |
| real_proposals_open | TL-08 | p3 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |
| real_proposals_open | TL-14 | p2 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |

## 领域事实与“不是业务事实”的标注（不是门禁）

领域读取（经注册的 category.parameters.list 读回脚本发布的参数）：12/12 次与标注一致；记忆返回带“不是业务事实”标注：6/6 次（只看真实的 memory.search，脚本模拟的基线 1 不计）。

- 未满足：real_proposals_open / TL-12 / p1

未满足的非门禁预期：1 条；缺失的回放：0 个；pytest 退出码：0。
覆盖的测试用例编号：AT-71、C1、T01、T02、T03、T04、T05、T12、T13、T14、T15、T16、T17、T18、T24。时间线全部是候选，未经人工确认。
