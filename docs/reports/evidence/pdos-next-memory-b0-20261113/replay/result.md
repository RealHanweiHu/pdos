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
| 基线 0：全部会话不进记忆 | 0/9 | 0/7 | 0/2 | 0/6 | 0/3 |
| 基线 1（模拟）：只搜本人以往运行的原话和回答摘要 | 9/9 | 7/7 | 2/2 | 6/6 | 3/3 |
| 基线 2：当前实现 | 6/9 | 4/7 | 2/2 | 6/6 | 0/3 |
| 当前实现，测试进程内打开对话提议的版本闸门 | 6/9 | 4/7 | 2/2 | 6/6 | 0/3 |

`history_only` 是评测脚本里的模拟检索，不是产品路径；每组只有个位数的题，比例不代表稳定的召回率。

## 目标能力的现状（不是门禁）

| 组 | 时间线 | 探针 | 目标 | 观察到 | 是否达到 | 服务器给的拒收原因 |
| --- | --- | --- | --- | --- | --- | --- |
| no_memory | TL-01 | p4 | `{"catalog_has_unfinished": true}` | `{"catalog_has_unfinished": false}` | 否 | — |
| no_memory | TL-03 | p2 | `{"admitted": 1}` | `{"admitted": 0}` | 否 | memory_candidate_prompt_not_released |
| no_memory | TL-08 | p3 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |
| real | TL-01 | p4 | `{"catalog_has_unfinished": true}` | `{"catalog_has_unfinished": false}` | 否 | — |
| real | TL-03 | p2 | `{"admitted": 1}` | `{"admitted": 0}` | 否 | memory_candidate_prompt_not_released |
| real | TL-08 | p3 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |
| real_proposals_open | TL-01 | p4 | `{"catalog_has_unfinished": true}` | `{"catalog_has_unfinished": false}` | 否 | — |
| real_proposals_open | TL-03 | p2 | `{"admitted": 1}` | `{"admitted": 0}` | 否 | trigger_not_explicit_remember |
| real_proposals_open | TL-08 | p3 | `{"target_in_catalog": true}` | `{"target_in_catalog": false}` | 否 | — |

未满足的非门禁预期：0 条；缺失的回放：0 个；pytest 退出码：0。
覆盖的测试用例编号：AT-71、C1、T01、T02、T12、T14、T15、T16、T17、T18。时间线全部是候选，未经人工确认。
