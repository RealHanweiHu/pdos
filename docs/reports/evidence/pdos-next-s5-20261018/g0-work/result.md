# G0 原生事项 → 真实任务 · 本地功能检查点

基线 `02492016a2d1a77712d44009b9757d3d7213a083`，单调迁移 `s0_0794 → s0_0795`。本轮 20 份归属源码/测试/合同在独立 HEAD 拼装副本冻结，完整摘要见 [candidate.json](candidate.json)；其他聊天在途 UI、Agent 内核、公共 API、清单其他行未纳入交付。不是整仓回归或阶段验收。

## 可用能力

- 从项目里已经可读的原 `ProjectOpenItem` 直接接续任务草稿，精确绑定事项、原决定、同租户/品类/型号/项目及原 question/spec 身份，不伪造 Artifact、计划任务或开放私有提案/客户原件。
- 同一原事项只有一个执行任务；所有续版保留原关联与来源水位。草稿、T1 分派、本人承接、实际开始、提交成果、指定接收人验收继续分开。原 G0 安排期限没有变成个人承诺。
- 任务动作只有在实际 G0 原生来源核对通过时才允许空 Artifact 读取；新增承诺/周报与 `present` 成果仍保留原来源要求。原件 ACL、安全、撤回及共同事务守卫未放宽。
- 页面展示原安排、固定决定和实际 Task Current；已有任务选中同一任务，不再创建第二待办或维护原事项 completed。风险关联调查任务后，成果验收仍不关闭风险或证明规格满足。
- 旧 0794 Task 正文没有新空关联字段也可继续办理；有原生 G0 任务历史时拒绝丢失关联的降级。

## 验证及覆盖

| 检查 | 结果与范围 |
|---|---|
| 后端纯检查 | 最终修复副本 208 项通过，覆盖工作、履行、动态、注意项与新增来源/存储/服务边界，见 [pure-repaired.json](pure-repaired.json) |
| 前端 | 23 库 + 13 组件检查通过；类型、归属 lint、生产构建通过，见 web-*.json。构建与最终副本的五份前端 SHA 完全一致，后续仅后端源行锁修复 |
| G0 实际 PG/HTTP 链 | 新私有提案→独立具名 G0→另一位办理人仅读项目结果→Task 草稿→分派→本人承接→开始→真实成果→指定接收人验收，形成一个任务/六版；本人注意项随承接消失；私有提案仍 404。错误决定/重复建单拒绝、原请求同回执、finalize 尾部失败完整回滚均覆盖，见 [pg-g0-repaired.json](pg-g0-repaired.json) |
| 旧 0794 Task 实际续版 | 精确保留的本聊天合成任务原正文确实没有新字段，经 T1 保持原分派续版为 v3，原回执重放一致，见 [legacy-task.json](legacy-task.json)。不和新 G0 链重复计数 |
| 迁移 | 已核对的 `127.0.0.1:64245/pdos_test`、marker `f9048729-3f2a-4494-af75-56e1db7d743d`；up/down/up、普通属主/Force RLS/Agent 零直接写入通过；有历史拒绝降级、Task ORM diff=0，见 [migration.json](migration.json)、[storage-final.json](storage-final.json) |
| 实际页面 | 本人从原事项预填并保存另一条 Task 草稿；最终读回一版、无执行人/接收人、原始 G0 关联相同，已有关联不再提供创建；风险仍独立。最终刷新零业务 POST，1440 亮色/320 暗色无横向溢出，见 [browser_final.json](browser_final.json) 与截图 |
| 最终共同组 | 浏览器 Task 只有一份 create、无 Confirmation，Audit/Outbox/RequestKey 各一份；原 risk=open/六任务版，原 task=assigned/一任务版。原 legacy status 没有被更新表示完成，见 [cleanup-and-final-facts.json](cleanup-and-final-facts.json) |

## 修复和证据限制

首轮实际联验暴露来源锁：普通办理人能 SELECT 原生事项，但 `SELECT FOR UPDATE` 额外应用旧表依赖私有提案 owner/reviewer 的 UPDATE 策略而返回不可读。修复为保持项目锁、原事项普通 SELECT；原字段已由迁移保护不可变，首版唯一索引仍防重，没有扩大 UPDATE 或提案权限。首次 [pg-g0.json](pg-g0.json) 失败保留，修复后冻结新副本才重验。

首次浏览器脚本在实际保存回传前过早刷新，后台 `route.fulfill` 报 already handled；脚本最终走到原任务重放/选中和暗色，但工具返回失败，因此**不宣称指定 503 注入完整通过，也不把该脚本计作一次通过**。随后独立脚本通过最终真实 Task/回执读取、刷新零 POST、关联复用与尺寸核对；原请求同回执恢复由两条实际 PG 链及组件检查覆盖。失败原始工具输出保留在 browser-cli.log。

其余检查入口问题均未冒充产品通过：首次未冻结纯检查有旧测试 NameError；首次集中 pure 的目录名错误（未运行）；Node 原生 TS 入口不解析 extensionless import，改用项目实际 CommonJS transpile loader 后 36 项通过；首次构建公共字体 DNS 不可用，同一前端候选在网络可用环境构建通过。捕获迁移 SQL 保留原长行，58 条 E501 仅对此文件豁免，其他归属文件 lint 和全部 14 Python 文件 format 通过。相关失败输出与说明保留。

## 收尾与余项

专属浏览器、58571/58572 API/Web 已关闭；35 分钟页面凭据及另一个 5 分钟旧版联验凭据已撤销。共用独立库、Temporal 和既有备份保留，新增 0795 备份摘要见最终事实回执。本轮真实模型与业务外发 0，无 push/部署、无性能采样或重复攻防。

通用 ExternalWait、风险独立裁决、其他专业分诊及知识/爬坡反馈继续施工。S1/S2–S5 正式验收、真实资格/外发、S3 一天观察与既有23514/409缺口不据本闭环关闭；唯一活动状态仍为整合清单 M9。
