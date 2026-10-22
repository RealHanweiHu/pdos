# 已确认计量发布与本地预算切换状态

2026-10-06（洛杉矶日期）。当前状态：用户回复“同意”后，合法Owner已沿受控服务追加三个旧调用的保守占账记录，完成draining → budgeted revision 2；私有配置已应用，3000/8000已重启。原记录的未知实际用量没有改写。同网站来源登记冲突已修复，实际搜索、原文读取、引用回复及GUI回读已完成；最终一页限流，模型来源归因与回答长度仍需改进。验证中一次取消请求的新增未知用量继续按原预算保留7,494占用，没有套用旧调用恢复。见[本地启用结果](enablement-result.md)及[真实运行核对](real-public-research-proof.json)。

下方是此前发布与采用过程的历史记录；其中“未启用”“待确认”“尚未修改”只描述相应检查点，不代表当前状态。

**用户再次要求启用后的续查**：原 API 进程的实际 stdout 日志没有 token 用量字段，也没有上述请求标识，无法从日志补出真实回执。只读密码校验已确认当前租户 Owner 是仓库本地演示种子账号，原登录凭据匹配；可沿合法登录与受控服务办理，无需改角色或借用身份。见 [管理员条件](local-admin-readiness.json)。系统 DNS 仍返回 `198.18.*` 保留地址，见 [当前网络条件](current-network-readiness.json)；[应用内公开 DNS 恢复预检](public-dns-recovery-preflight.json)已得到200与真实公开地址，后续可按原地址守卫接入，当前配置未变、真实研究整链尚未执行。

已整理 [三个旧调用的保守占账方案](bounded-legacy-adoption-proposal.md)，等待用户决定是否采用这一新的未知用量恢复规则。此前计量包发布与本地启用批准继续有效；本次确认仅针对现有“须实际用量回执”规则的调整。尚未修改规则、迁移、账本或部署配置，不能宣称已启用。

## 已完成

用户在具体候选及本地启用范围之后回复“我确认”。发布范围维持MiniMax-M3当前确切端点、纯文本、17,000含余量输入、4,000输出上限和7天有效期；[人工确认记录](meter-publication-approval.json)关联当前Codex会话及本机账号`huhanwei`，不将预览的项目经理账号假称为Owner/Admin。

候选的三个空白人工字段已按该确认填写到独立正式文件，原候选及四次实际回执保留。正式文件：

- [publication.json](/Users/huhanwei/pdos-preview-config/input-metering/minimax-m3-20261006-candidate/publication.json)
- 根SHA-256：`9df66b9433dd5d14faae811a760b21c57f54ec08756374c444a93e59b6e04aad`
- 有效期：2026-10-07 02:12:31至2026-10-14 02:12:31 UTC；到期为洛杉矶2026-10-13 19:12:31，不自动延长。
- [实际发布包只读核验](meter-publication-verify.log)：`verified: 1`；固定资产、四类可重算证据、模型golden匹配、精确路由及有效期通过，没有在线重放模型调用。
- [已确认预算配置](/Users/huhanwei/pdos-preview-config/input-metering/minimax-m3-20261006-candidate/budget.approved.env)包含固定正式路径/摘要及现有`research_discussion`档位；[配置检查](approved-budget-config-check.json)通过。摘要在受控发布环节确定并写入该部署文件，运行加载器使用固定值，不自行计算待加载文件摘要后信任。

现有模型golden可信根未改。四类计数采样不替代完整回答质量、真实研究整链、产品八能力资格、生产启用或原人工Exit。

## 切换前实际阻塞

确认Docker容器、127.0.0.1:57432/pdos及原失败运行租户后仅做只读诊断：[切换前检查](adoption-preflight.json)。当前租户模式`compatibility`、revision 0，未关闭调用0、未完成预算预留0；存在3条旧`PROVIDER_TRANSPORT_ERROR`调用的未知用量。零字段是未知状态的保存值，不能当作供应商确认零消耗。

| 内部调用ID | 创建时间UTC | 原供应商request_id |
|---|---|---|
| c5ac39e4-af83-4911-b40c-236ee4066c24 | 2026-10-06 06:44:38 | 未保存 |
| 95fe9204-c8f3-4aa6-a870-c51123a08833 | 2026-10-06 06:53:17 | 未保存 |
| a3b1253d-1c28-4272-92e9-4175ab9fdbfc | 2026-10-06 10:04:29 | 0713fa46fa9862e7ce68c2655b63a96b |

[原记录摘要](unresolved-legacy-usage.json)只包含状态/用量元数据，不含消息正文或凭据。仓库证据、tmp和output中定向检索这三个调用ID及供应商request_id，没有找到额外原始用量回执。公开官方文档索引也未找到可按Chat Completions request_id检索历史用量的公开接口；没有猜测账号接口或读取私有计费页面。

`cehub_ai.unbound_model_usage`保留所有未核对未知用量，不因日期改变自动变为零。[切换手册](../../../runbooks/application-budget-adoption.md)及`ModelCallModeService.change`在`complete`阶段拒绝这类未核对用量；不能重置账本、改写旧失败、补零或启用另一条绕过通道。当前浏览器账号`manager`为`project_manager`，实际切换还须由合法Owner/Admin通过原服务办理；没有借用已有`owner`身份、改账号或提权。

## 恢复条件与未完成项

需要上述三条调用的实际供应商用量回执或可核验导出，至少包含模型、时间/请求标识及输入/输出token，存在cache字段时保留。无消息正文要求；两条缺request_id的记录须凭对应时间和独立供应商凭证核对，不能猜配。

取得证据后，沿`LegacyUsageReconciler`保留追加审核记录，由合法Owner/Admin按真实revision完成draining/准入，再备份私有配置并应用已确认预算文件、重载API。原消息和旧运行不改写。此后执行用户已确认的一条合成公开研究整链，保留公开DNS守卫、预算/停止/幂等、引用及T1人工采用边界。

本轮没有写存续数据库、修改私有`.env`、停主API/前端、执行新的真实研究请求、push或生产操作。3000/8000继续运行；已批准包和未应用配置保留在本机私有目录。入口未知用量和Owner/Admin条件未满足，所以不能宣称自动研究已经启用。
