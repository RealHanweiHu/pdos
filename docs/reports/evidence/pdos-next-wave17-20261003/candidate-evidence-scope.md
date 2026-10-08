# Wave17 候选公共闭环：证据范围草稿

本稿只整理已有安全结果、原始日志和公开源码，辅助 [result.md](result.md)。它不是活动清单，也不将待验证项登记为完成。唯一活动状态仍在 [整合清单](../../../../tasks/ai-native-integrated-todo.md#pdos-next-queue)。本次整理没有读取私有凭据，没有执行数据库、HTTP、浏览器、构建或共同验证；仅新增本文件。

截至本稿采用的证据，公共新办理范围仅辅助 `quality.capa.verification.candidate.record`（T1）。候选保存原完整锚、不完整材料、`indeterminate`，`applicable`、`independently_verified`、`observation_complete` 均保持 NULL。v6 已有一次真实保存成功；原键回放、最终回读和浏览器新写时效尚待主线补齐，不能声称该候选闭环完整验收通过。

## 已有证据及各自范围

| 层级 | 可登记的事实 | 不能据此登记的结论 |
|---|---|---|
| 迁移及目录 | [closeout v3](public-migration-closeout-v3.json)绑定实际 25→26→25→26 往返和 schema 检查，四步骤 exit 0；head `next_0026`，111 张公共表生命周期目录覆盖；新五表强制 RLS、引用门栓启用，Agent 直接权限 0 | 迁移完成不等于 Rule/Observation/Review 已发布或业务资格已授予 |
| 迁移保留边界 | 同一迁移 checkpoint 中，原 106 表全行摘要保持；该 checkpoint 业务事实写入 0、模型调用 0 | 不能将此历史 checkpoint 的零写入推到后来 v6 已保存后的数据库；不能宣称后续异步投递也保持全库摘要 |
| SQL 原子组 | [SQL v2](candidate-actual-sql-checks-v2.json)列出 19 个独立病例：3 项复用 [v1](candidate-actual-sql-checks-v1.json)已通过项，16 项在 v2 实际执行；各次复制材料均回滚，记录相应 111 表回滚后摘要保持 | 不是 19 项在 v2 全部重跑，不是公开 handler 的 PG 联合验收，也不是真实资格的证明 |
| HTTP v6 | [v6 结果](candidate-actual-http-v6.json)记录 inputs 200/183.011 秒、preview 200/174.245 秒、save 200/569.399 秒，源稳定；随后原键回放超时，文件总状态为 FAIL | 保存 200 不能替代回放成功、唯一事实/回执回读或浏览器验收；超时不能判断未保存，不能解锁并另建请求 |
| common 延后验证 | [common v2](candidate-common-validation-check-result-v2.json)29 项纯检查通过（1.06 秒），静态检查 exit 0；真实 common execute、消费函数、append receipt 和 SQLAlchemy 事务/history 参与，SQL/owner/权限来源等明确为替身 | 不是实际 PG/HTTP、原件读取或资格通过，不提供性能改善的实际测量 |
| fixed Output 的 F 范围 | [F 85 项](link-fixed-output-no-ui-authority-delta-v1.json)为既有 professional/CAPA 纯核、retained 回归及 13 个 fixed-owner 病例；验证完整固定材料/来源摘要保持、无关 caller UI 权限读集不混入固定输出 | 不等于公共全树、真实当前专业或完整 HTTP 保存；不能将重叠纯检查累计为更多独立病例 |
| fixed Output 的 B 范围 | [B 14 项](front-fixed-output-check-result-v1.json)核实际 `get_request/_view` 内部读取模式：默认行为保留，只省三个未来命令的 caller UI 能力评估；原父/子事实、来源、Current、文档和 freshness 守卫保留 | 不是 PG 资格或运行时性能测量，不应和 F 85 相加称为新组合联合验收 |
| web v2 | [152 文件清单](web-candidate-source-v2.json)、[构建结果](web-build-result-v2.json)记录 lint/build exit 0，源稳定；build 日志包含 TypeScript 阶段成功 | 文件数不是用例数，构建不能替代真实浏览器、HTTP 或共同事务验收 |
| BFF | [v3 原始日志](candidate-bff-wait-v3.log)实际 55 项通过、0 失败；覆盖原请求转发、等待、未知结果不重试、读取失败和同源边界 | [v2 日志](candidate-bff-wait-v2.log)为 tests 0/pass 0，不计通过；55 项为离线路由检查，不是实际后端处理或用户审阅时效证明 |

SQL 的三项保留通过是 `legal-complete-SQL-fixture`、`missing-receipt`、`missing-audit`。v2 实跑其余 16 项：缺 Outbox、回执 binding hash、消费钟早于 proof/晚于保存、保存到期边界，三个 NULL 字段在列和 snapshot 两侧的六个反例，Agent INSERT、app UPDATE/DELETE、admin UPDATE/DELETE。SQL fixture 的合法材料验证只支持原子组形状；它不自授当前来源/专业/同 UOW 实际消费资格。

## 候选运行代际与保留的失败

[HTTP v6 源清单](candidate-actual-http-source-v6.json)绑定原 common SHA `d1ba6e06be3a7369c60bbe163560bf59057b82091cee4540817fda8840732ce5`。后续 candidate-only 延后 validate 的 common SHA 为 `8eb1c988ccc01095db0dbb4c084fae555540035894d81a4fd47627fd8ba18602`，29 项纯检查只绑定后者；不能把 v6 保存耗时标成新 common 版本的测速。

新 common 只在候选新写无去重命中时省掉一次随后丢弃的完整验证。RequestKey 命中仍先完整 validate，再判断冲突/回执返回；semantic Receipt 命中仍先完整 validate，再新增 alias/返回。新写仍有 `prepare_write_review` 的消费前完整材料核对及 writer 消费后全 owner 重核，其他操作的 validate/消费/marker 时机未改。该静态边界和纯检查不代替 v7 的真实验证。未来若候选增加 `replay_subject`，须在调用该 hook 前核延后的完整 validate。

共同确认 TTL 仍为 10 分钟。v6 save 请求本身耗时 569.399 秒，理论仅剩约 30.601 秒供请求前的用户审阅及其他延迟；没有修改生产 TTL，也尚无新写测速证明此问题已改善。

迁移 [v1](public-migration-result-v1.json)在步骤前失败；[v2](public-migration-result-v2.json)四步骤 exit 0，但旧表物理列序 postcheck 标 FAIL。v3 校正该 postcheck、绑定原步骤日志并记录差异，没有把 v2 改写为 PASS。SQL v1 的 `missing-outbox` 已受到正确 `event` 原子门禁拒绝，但工具要求错误的文字片段而标失败；v2 修工具期望后实际复验该项，不抹掉 v1。common 纯检查首次为 25 pass/4 fail，原 Link 替身 token 长度不合既有 DTO；最终 29 项只调整替身 token，历史记录保留在 [首次检查说明](candidate-common-validation-first-attempt-v1.md)。

## 待主线补齐的实际验收

| 待补位置 | 必需记录 | 本稿状态 |
|---|---|---|
| 原键恢复 v7 | 绑定新 common/runtime 源清单、原完整已保存 Command/key 原封回放、实际响应及唯一候选/Receipt/Audit/Outbox/Confirmation 回读；不得据 v6 超时自动另发新意图 | 待主线补齐，不记 PASS；已有在途日志不代替最终结果 |
| 浏览器新写与时效 | 新候选 inputs→真实预览→用户审阅→一次提交→回读；分别记录预览完成、审阅、提交处理耗时、proof 到期边界以及未知结果恢复 | 待主线补齐，不声称审阅时间已充足或新性能已达标 |
| 最终范围收口 | 实际 v7/浏览器结果与使用的后端、web 清单精确配对；指出跨代复用范围及实际验证缺口 | 待主线汇总，不借旧通过构成整树联合通过 |

## 仍保持的业务与可信根边界

当前 actual host 的 `authorized/qualified/synthetic=true` 只表明受控本地 synthetic 办理依据满足该候选范围，不能授真实生产资格。Candidate owner/visibility 继承原完成 Issue/CAPA 系列，本次具名 writer 独立绑定；private 不因产品 Grant 扩为共享。来源全闭包上限 20 不截断，原完整锚、失败 proof、原 Start/占用/usage、安全和 issuer epoch 保留；仅三条已冻评估路径允许稳定材料比较排除，不重封首次 full anchor。

公开读取仍明确缺少新测试配对选项，可保存真实 incomplete 候选；这不是补齐观察或独立验证。七个真实 owner 门禁、规则 host publication、Observation T1、具名 Review T2、有限 effect→close 后继的当前授权，以及 effective/close 的公共提交均未接通。现存 DTO、存储表、纯协议、迁移和合成检查不构成其业务开通，不改变已有 Run/测量/正式占用/消费，也不登记 G3 或人工 Exit 通过。

候选事件 `CapaVerificationCandidateRecorded` 的 common 原子 Outbox 可证明本次保存组，通用 dispatcher 对无专用工作流的事件以 ignored/ack 处理。尚未据此执行或证明异步派送、七 owner 或后续专业动作；worker 恢复会改变投递/Inbox 账，不能沿用恢复前全表摘要作恢复后结论。

## 本稿采用的证据摘要

以下 SHA256 只绑定本稿读取的材料，不是新建候选清单或重新执行检查。

| 材料 | SHA256 |
|---|---|
| `public-migration-closeout-v3.json` | `3a9dd3770bcf252572c0f2d61f784e4f2d1703644777334c50e19ff4425060d9` |
| `candidate-actual-sql-checks-v1.json` | `c32062e7c5fc774e7871bfe3193c074245b3d1c7e77054a7a0a614ad6dc8ca7d` |
| `candidate-actual-sql-checks-v2.json` | `0a8b9772bdfd0b6eedb5739daf579a611f0a2ea08baa120ff9ae4673817c4160` |
| `candidate-actual-http-v6.json` | `ed9e30750b2730d3ecb265da7819f794430d9963a800622b47407123e986c20e` |
| `candidate-actual-http-source-v6.json` | `b54535ca9ec12b5343bb7e3d4fd5622e207d7127db872ae4a34979522ab030b8` |
| `candidate-common-validation-check-result-v2.json` | `3c5d5f3765af74ef1888588a5a1f69f0812764e7bef3a014ab17ec80cbc13568` |
| `link-fixed-output-no-ui-authority-delta-v1.json` | `9f97ccdaf9c4e1d3a87c70e82390f603f7c8bc3e77602c066cdc54b8c8ac3044` |
| `front-fixed-output-check-result-v1.json` | `28391e7cee195ba2ec8ac07b80e05a4fc987be84b968a23ac914d3593a87db33` |
| `web-candidate-source-v2.json` | `879ba37ab5ab5c6baaef01aa2a44445094698fabd484c0578f5c68200e6392f7` |
| `web-build-result-v2.json` | `bfafecb2e8db6dec5b32f93b9f903bdbc83f2694b96ccab2db3d63aac4f6b50c` |
| `candidate-bff-wait-v2.log`（0 项） | `6ff71e9f86f2173dca91a8ce68c3e75d85e1024c91ad92bec8313240d52dd7ac` |
| `candidate-bff-wait-v3.log`（55 项） | `83a372cc58b8e96e61f618899a9e22ce917c968eae15c25ad10eb2d3bbc75aff` |

本稿不追加完成勾、不改唯一清单或既有 result；v7 原键恢复和浏览器新写测速仍需主线实际证据。
