# 服务商协议管理员登记闭环

按冻结 v1.1 §07.5、附录 A `provider.agreement.register`（T2）及 AT-57，补齐已有领域登记服务的实际入口。当前闭环可用；完整 M3/S1 出口未完成。

- 品类「设置 → AI 运行与费用」读取租户共用的服务商最新协议、有效/到期/停用状态、条款、登记人与回执；普通成员只读。当前管理员按真实签约材料预览后本人批准，可续版、停用。页面明确变更影响当前租户所有品类。
- 服务端实际鉴权并锁定当前管理员和品类写入权限；协议、具名 T2 回执、审计与事件在同一事务落库。按租户/服务商短事务锁串行首版与续版，原请求先恢复回执，已到期原件不因日期变化失去幂等恢复。
- 未取得写入结果时保留本人已批准的完整原请求，按人员/品类隔离。重新打开只调用只读恢复接口；原正文由服务器计算摘要核对。当前管理员资格撤回后仍能读取自己已完成的原回执，不能登记新协议。
- 修正提案四视图空分组文案：如实说明当前尚无可展示/绘制数据及应补充的口径，不再暗示服务端接口缺失。

## 验证与实际结果

候选以 [源码摘要](candidate.json) 固定，承接 `57650db`，无迁移。数据库仅使用已核对的独立 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`，head `s0_0762`。

- [16 项实库](checks/management-api-first.log)：管理员/成员、真正 T2 原子记录、停用后出站拒绝、只读恢复、管理员撤权后的读取/写入边界、原协议到期后的精确恢复、版本冲突、两类并发首版、最新版本分页与范围校验。SQLAlchemy 的既有 DISTINCT ON 写法出现 6 条弃用提示，检查全部通过。
- [48 项路由及契约](checks/bff-contracts-final.log)与[27 项组件](checks/components-final.log)，共 75 个不同前端病例；其中新协议契约 3 项、BFF 新增 3 项，包含原请求原样转发、同源与分页、只读失败/写入未知的区分。连同实库共 **91 个不同病例**，增量复核不累加计数。
- [类型](checks/typecheck-final.log)、[Ruff](checks/ruff-final.log)、[本轮文件 lint](checks/lint-owned-final.log)与[最终生产构建](checks/build-final-scope.log)通过。全前端 [lint](checks/lint-final.log) 0 错误；未修改的忽略生成文件 `verification/contracts.js` 保留 2 处既有 unused-var 警告。
- 实际浏览器正常登记第 1 版、本人停用第 2 版；另一合成服务商提交成功后仅替换一次响应为 503，手机尺寸重开恢复[同一回执](recovered.ax.txt)。[HTTP 记录](browser-http.jsonl)显示该服务商仅 1 次登记 POST、1 次恢复 POST，重开没有第二次业务写入；[实库结果](browser-business-result.json)每版各只有 1 个协议、回执、Audit、Outbox。
- 最终页面按 [1280px 亮色](desktop-final-light.jpg)、[320px 暗色](mobile-final-dark.jpg)查看协议结果与[手机表单](mobile-form-final-dark.jpg)，修复复选框和全局输入样式冲突。真实模型调用 0 次、真实协议登记 0 次，未新增攻防、资格授予或外部访问。

最终说明性文案补充「租户所有品类共用」与回执服务商标识后，以 `build-final-scope.log` 重新构建、定向 lint 并查看页面；业务流程未再登记或重放。原成功响应丢失的截图/AX 保留为变更前业务流程证据。

## 剩余与收尾

实际使用步骤已补入[租户模型运行手册](../../../../runbooks/pdos-next-tenant-model-runtime.md)。真实服务商协议、KMS/价格材料、实际模型质量/资格、真实 Worker 模型联验、正式性能/恢复与完整 M3/S1 验收仍待完成，合成通过不代替这些出口。

本轮自建预览关闭、临时登录失效、管理员状态恢复并保留合成业务记录；[收尾核对](browser-cleanup.json)。独立测试库、共用运行时与 Temporal 保留。没有 push、生产或云资源操作。
