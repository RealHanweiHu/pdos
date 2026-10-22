# S4 受控发布政策与独立具名决定（2026-10-17）

受控政策原文→固定包明确续版→工程/制造分别具名 T2→政策撤回后保留原包及决定的无例外闭环已通过真实 HTTP/隔离 PostgreSQL 合成联验。S4 未验收；本例用途仅为项目内部文档准备，不授予生产、真实外发、客户承认或物理资源资格。

后续页面实操发现空批次/产线会筛掉政策检查：本报告 actual-decisions-02 只断言汇总 READY，不能证明检查逐项执行。该覆盖缺口已由[空范围修复与两专业页面联验](../release-decision-browser/result.md)纠正；旧原始日志保持。以下为本轮原有实现及证据范围。

政策由可信宿主读取已登记完整原行，核对重复键、原文摘要、项目/定义/双配置/用途/范围和本人当前专业职责资格，追加不可变 Fact/Current 及同事务共同回执。没有公共自授入口，也不产生第二次确认。规则保留 v1.1 的字段，仅支持具名有限谓词；不支持、证据不足、范围不覆盖或缺专业规则均保留 UNKNOWN，不增加全 Issue 关闭、良率门槛或 T2 TTL。当前正向覆盖明确文档存在及制造发布存在性，不将 Run 状态当作测试 pass；历史 Run/Pilot 等尚无本次直接当前证明的谓词仍未知。

放行材料复用同次实际收集的对象，将政策原件读集并入原有分区核对；已登记政策读取不再读原行 bytes 或重新签发历史权限。后续复核比较实际 Current、Fact 摘要、直接原件安全/ACL 和保存的专业签署水位。原文或来源的私有范围不能借固定包扩大共享。有效期原文可空，有值时核实际服务器时间；登记未来政策不等于现在可用。缺政策继续 UNKNOWN，独立例外 owner 尚未接通。

- 最终候选 [candidate.json](candidate.json)：`9faizwbc`，22 个归属文件；共享部分仅提取本轮差异，排除其他 M2/M3/UI 待提交上下文。
- [实际联验02](actual-decisions-02.json)／[日志](actual-decisions-02.log)：**1 passed，67.69 秒**，同候选来源未变，实际 head 为 0782。先保存未知政策的 v1，登记受控政策后明确续版 v2，原内容不改写；工程先由本人签署，制造由另一具名人签署，各自保留共同 T2、原回执及幂等重放。一次制造共同尾失败整笔回滚，含未消费证明/账本计数，原请求随后完成。追加政策撤回后，原包及两专业决定保留并显示 `needs_recheck`；重放旧政策回执不回退 Current。
- [实际记录摘要](actual-records.json)：2 个政策版本（当前撤回）、2 个固定包、两位不同签署人的 2 份已消费空期限 T2，各自仅 1 Audit/Outbox。`external_received=false`、`external_effective=false`、`customer_acceptance=null`。
- [独立拼装03](delivery-pure-03.json)／[日志](delivery-pure-03.log)：HEAD `d98f998` 加 22 个精确归属输入，**131 passed**；移除其他待提交上下文，无数据库连接。先前 130/131 项候选不累加计数。[最终静态04](static-final-04.json)通过；专业授权文件原有两处换行差异保持，最终只交付操作映射一行。初轮静态包含冻结 SQL 长行及既有格式差异，失败保留，不作通过。
- 0781 完成[升级](migration-up-01.json)→[降级](migration-down-01.json)→[再升级](migration-reup-01.json)，当时新政策表无历史，已有 0780 固定包历史保留。[metadata02](metadata-02.json)无归属 ORM 差异，2 表普通 owner、强制 RLS、Agent 无直接读写与无删除权限。metadata 初次启动因路径引号失败，[单独留证](metadata-launch-01.json)，未产生校验结论。既有循环 FK 排序与 `flush(objects)` 弃用警告保留。
- [实际联验01](actual-decisions-01.json)在具名预览被旧 `ck_confirmations_decision_deadline` 拒绝，未计为通过。新增 0782 只补工程/制造两个已注册 T2 的空期限覆盖，升级 SQL 保留原样；首次回退因 PostgreSQL 对显式数组规范化而拒绝，未改库。补录实际规范化回退前件并以原等价 `IN` 形式恢复，完成[回退02](correction-down-02.json)→[再升级02](correction-reup-02.json)；原升级及失败证据均保留。[实际约束核对](deadline-actual.json)覆盖全部当前 T2，T1 条件保持。有批准凭据后[回退保护](history-preserve-result.json)按预期拒绝，head 0782 与历史保留。
- [前端复用边界](frontend-reuse.json)：发布组件、请求流和既有断言等 6 个文件与 `d98f998` 逐字相同；既有固定包浏览器保存/续版/恢复及构建证据保留。本轮新增正向路径验证到共同 HTTP/PG，未重做正向具名批准浏览器操作，不以代码合同核对冒充浏览器通过。

目标始终是已核对 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`。0780 前置备份 `pre-release-policy-20261017-s0_0780.dump` 保留（67,748,784 bytes，SHA256 `03d36f4af89b82e1c3c41ba8e44c763cc6e5c1f54a9f7f210c23418ef6ccf811`）。本轮未新开持久预览进程；实际 fixture/TestClient 与合成签发入口已收尾，数据库与备份保留，其他预览未处理。

下一步：必要独立例外、正向具名批准的实际页面操作，以及受控交付 manifest/编号版本映射、人工接收和生效证据路径。真实业务政策/权威接入、S3 一天观察及独立评效、S1 真实模型与完整阶段验收仍保留；性能验收暂缓。模型/KMS 调用、真实外发、push、部署及生产操作均为零。
