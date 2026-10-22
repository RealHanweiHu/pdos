# B8 最终性能证据审查（草稿）

只读审阅，未运行测试、数据库或计时。审阅时短路径 8 组各 30 次均 HTTP 200，`source_unchanged=true`；所审阅的四个工具源码与短路径 manifest 一致。B4 刚完成 30 个业务用例：pytest 退出 0、JUnit 零失败/错误/跳过，源码与短路径一致，420 个 call 阶段 HTTP 请求全部 200。B5/B6 和最终汇总仍待完成，**不能登记 32 路径性能整体通过**。

依据为 [汇总工具](/Users/huhanwei/Desktop/ai-native-R&D-platform/pdos-next/tools/s0_b8_performance_summary.py)、[B4](/Users/huhanwei/Desktop/ai-native-R&D-platform/pdos-next/tools/checkpoints/b4_performance.py)、[B5](/Users/huhanwei/Desktop/ai-native-R&D-platform/pdos-next/tools/checkpoints/b5_performance.py)、[B6](/Users/huhanwei/Desktop/ai-native-R&D-platform/pdos-next/tools/checkpoints/b6_performance.py)。32 条路径分组、门槛与实施计划 P3/P10 一致：

| 范围 | 路径数 | p95 门槛 |
|---|---:|---|
| 短路径 | 8 | 草稿等价意图恢复/真正新建、同键重放、workspace、空 Build readiness、21 来源配置读取：6 条 ≤1s；T1 预览/确认：2 条 ≤2s |
| B4 | 12 | 开测前/运行后读取、3 种 inputs、Start 重放：6 条 ≤1s；plan/promise/start 预览及 plan/promise 提交：5 条 ≤2s；首次 Start 提交：1 条 ≤3s |
| B5 | 6 | 品质读取、遏制 inputs、候选读取/inputs：4 条 ≤1s；遏制预览/确认：2 条 ≤2s |
| B6 | 6 | 制造资源读取、impact inputs、impact 重放：3 条 ≤1s；capture、首次 impact、覆盖发布：3 条 ≤3s |

每条必须恰好 30 个 `success=true` 样本；p95 取排序后的第 29 个。汇总拒绝缺组/缺样本、失败或跳过用例、NaN/负数/布尔 SQL 计数和源码漂移。B4 必须 30 个独立 fixture 与成功 JUnit；B5/B6 各须 1 个完整成功用例、`outcome=passed`、同一源码摘要，不能凭部分 JSON 行数过关。阈值超出时汇总退出 1，并保留未达标结果。

首次提交与重放的区分有实际断言：B4 每组新 Run，首次 Start 后读取 `running`，第二次同命令必须返回原回执；B5 30 个不同 action 和不同回执，Issue 版本逐次增加；B6 30 个新 impact subject 与 30 个独立 publication subject，impact 原键重放必须返回原 ID，发布须返回预期 operation/family/revision 和唯一回执。B4 前后读取要求真实资源 Fact 当前且来源 current；B5 质量/来源/失败测量可用、具名授权/资格与候选 `allowed=true/current/evaluated_current` 均须成立；B6 资源必须 `known/current` 且有实际 fact/relations/source reads，impact inputs 必须 allowed，首次 impact 必须 revision 2。制造资源 `known` 不宣称正式验收或放行，候选可含效果缺项但不宣称有效性结论。

测量为标准本地合成材料、认证 ASGI 请求、零真实模型，不含网络或页面渲染。短路径及 B5/B6 HTTP 的 SQL 分开记录应用/认证 Engine，再相加，包含同 Engine 工作线程；B4 由全 Engine 被动记录按实际 request ID 归集。SQL 是成功的客户端语句计数，不展开数据库函数/触发器内部语句；记录形状/摘要而非参数，未设统一 SQL 上限。B4 的 60 次辅助 Artifact 注册虽在 call 阶段，但不混进 12 个必测组；fixture 准备、B5 根因/完成/资格准备、B6 新提案/发布材料准备均排除。覆盖发布测的是同步宿主领域命令及真实事务 commit，计实际业务 Engine 根线程 SQL，`auth_sql_count=0`，**不是含 HTTP 鉴权的发布端到端延迟**。

B0 只有 6 个可按同名语义和计数口径列前后值的短路径：`draft_save`、`t1_preview`、`t1_confirmation`、`same_key_replay`、`workspace_read`、`readiness_read`。其中 `draft_save` 是等价意图换键恢复，不能当真正新建；当前 fixture 记录更多，workspace 延迟不据此宣称固定数据量的提速比例；readiness 仍为空 Build，不能外推真实开测。`draft_create` 和 21 来源读取没有 B0 同组基线。旧 42.29s Start、197.79s 影响分析是单例；失败发布 1061s/585493 SQL 是旧候选全 Engine 聚合且发布最终失败，均不是 p95，也不与当前单请求 SQL 作等范围比较或当成功发布基线。

最终仍需核对：

- B5/B6 完整终态、JUnit、全部样本业务守卫及最终源码未漂移；保留失败和遗漏，不从部分样本推断通过。
- 32 组最终汇总、各组 p95 与门槛、SQL 范围，以及 `all_required_groups_complete`/`all_thresholds_passed` 和管线最终退出码。
- 最终报告注明短路径直接对比、重计算历史背景、可信宿主发布口径及合成/本地限制；不将本地结果推广为真实资格或生产容量承诺。

审阅时间（UTC）：2026-10-09T15:38:10.609430+00:00
