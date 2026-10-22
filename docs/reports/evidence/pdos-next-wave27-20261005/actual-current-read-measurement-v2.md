# Wave27 实际 current-read 测量 · v2

本次实际 worker 观测收尾正常；worker SQL 均为 unattributed，Root.section 只标主线程 wall time。

整个观测 context **505.543s**；真实 future-window 等待 **216.315s**；四个显式 HTTP 段合计 **110.193s**。总 context 不是一次 API 延时。fixture 没有独立标签，不能把残余时间称为 fixture。

| Root 阶段 | wall 秒 |
| --- | ---: |
| actual_start_preview | 12.211 |
| actual_start_response_loss | 42.290 |
| api_precommit_fault | 42.719 |
| deferred_sql_negatives | 83.379 |
| future_window_wait | 216.315 |
| original_request_recovery | 12.973 |
| plan_promise | 81.754 |

| owner | calls | inclusive 秒 | exclusive 秒 | SQL 次数 | SQL 秒 |
| --- | ---: | ---: | ---: | ---: | ---: |
| front._recheck | 166 | 12.592 | 12.592 | 4610 | 8.271 |
| physical._basis | 176 | 8.329 | 8.329 | 3377 | 5.812 |
| physical._inspect | 33 | 57.216 | 57.216 | 20953 | 37.871 |
| resources._load | 60 | 139.912 | 133.046 | 48147 | 88.365 |
| retained.inspect | 2 | 6.019 | 0.351 | 150 | 0.205 |

SQL 全段 **104191 次 / 191.523s / 2 失败**；worker **71478 次 / 130.912s** 无法分配给 Start/恢复等 Root 标签。

SQL failure 按真实标签保留，报告不含错误类型，不额外推断原因。嵌套 inclusive 不可加；并发累计可超过 wall；SQL 间隔和不能作为 HTTP 延时或提速证明。

下一优先项只作为候选：
- 先缩窄资源完整读取的重复路径（resources._load）；本次聚合不足以决定删除哪次读取。须保持末端完整 current/fingerprint、来源、权限、资格、时钟、同事务与锁/哨兵守卫。
- 再查固定样件 owner 的重复来源/父对象读取（physical._inspect）；本次聚合不足以决定删除哪次读取。须保持末端完整 current/fingerprint、来源、权限、资格、时钟、同事务与锁/哨兵守卫。

没有沿用旧 Root-only 4.12s SQL 结果作为 API 结论，也没有证明已经提速。精确 report/tool/五个 owner Source 绑定及正常缺省零条件见同名 JSON；实际 port/database/marker/head 仍由 Root 此次 atomic 执行证据绑定。
