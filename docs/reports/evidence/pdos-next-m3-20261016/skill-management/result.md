# 租户技能启用与停用闭环

按冻结 v1.1 §06、附录 A `ai.skill.enable`（T1）与 AT-58/63，管理员现可在「设置 → AI 运行与费用 → 租户技能包」办理真实启用/停用。这个闭环可用，M3/S1 仍未完成。

- 从当前服务器技能目录读取十二项配置及实际租户状态，显示中文能力名、用途、配置版本、领域动作与最近回执。普通成员只读；管理员先核对固定配置、版本及所有品类共用范围，再一次确认。
- 复用 COMMON 的 T1 确认、幂等、当前权限、Receipt/Audit/Outbox 事务与原回执。租户/技能锁和状态版本阻止两个品类同时覆盖首版；配置摘要由当前服务器技能文件重算，旧预览不能静默采用新内容。版本不写入数据库约束。
- 原请求只在本人确认后按人员/品类隔离保存在浏览器。重开先执行只读回执查询；只有本人明确重试且当前仍有权限时，才重试同一请求。已完成的过期原请求恢复原结果；没有结果的过期确认需重新预览。
- 只改启用开关与其版本/回执，不写入或清除试点标志、案例、模型/技能资格版本、审阅人与时间。停用后现有加载/领域执行守卫检查当前状态。新启用不会产生 T0 资格；已有审阅记录仍须由具体运行核对适用性。

## 候选和检查

[源码摘要](candidate.json)承接 `cc803f3`。仅使用已核对的独立 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`；新 head **`s0_0763`**。

- [迁移往返与 ORM 对齐](migration-result.json)：0762→0763→0762→0763，既有启用与资格事实摘要全程不变，新增版本为 0、回执为空，ORM 差异为空。原始日志：[上行](checks/migration-up.log)、[下行](checks/migration-down.log)、[最终上行](checks/migration-final-up.log)。跨其他旧表的既有循环依赖排序提示保留，不涉及本次表结构差异。
- [18 项实库](checks/skills-final.log)和[1 项实测](checks/interaction-timing.log)，共 19 个不同病例：成员/管理员、一次确认与原子记录、停用与资格保留、旧预览、同租户两品类并发首版、配置变化、管理员撤权和原回执、移除的技能、严格载荷及原模型/领域适配器回归。首轮 8 项与其重叠，不累加计数。
- [47 项纯执行绑定检查](checks/execution-regression.log)，覆盖新增注册命令后的技能加载和固定工具定义、运行/调用/模型绑定；[50 项前端契约与 BFF](checks/frontend-first.log)通过。合计 **116 个不同病例**。
- [类型](checks/typecheck-first.log)、[Ruff](checks/ruff-final.log)、[lint](checks/lint-final.log)和包含最终 TypeScript 检查的[生产构建](checks/build-final.log)通过。lint 为 0 错误，未修改的忽略生成文件 `verification/contracts.js` 保留 2 处既有警告。
- [实际 HTTP 20 次测量](interaction-timing.json)：p95 **354.86ms**，中位数 151.18ms，最大 483.03ms；每次 **25 SQL**（包含会话鉴权和领域）。仅为一个合成租户/技能的交互测量，不代替完整 S1 性能出口。

## 实际页面与结果

在[1280px 亮色](desktop-enabled-light.jpg)正常启用公开研究第 1 版，再本人一次确认停用第 2 版。随后资料查漏启用成功，仅将该次成功响应替换为 503，页面[保留原请求](unknown.ax.txt)；在[320px 暗色](mobile-recovered-dark.jpg)重开恢复[同一回执](recovered.ax.txt)。预览与结果自动获得焦点，手机页面可读。

[HTTP 记录](browser-http.jsonl)显示恢复场景只有 1 次预览、1 次业务写入和 1 次只读恢复；重开没有第二次业务 POST。[真实业务记录](browser-business-result.json)显示三次变更各有一份具名 T1 回执、Confirmation、Audit、Outbox；公开研究最终停用，资料查漏启用，所有资格字段仍为空/未授予。

## 剩余与收尾

操作步骤已补入[运行手册](../../../../runbooks/pdos-next-tenant-model-runtime.md)。实际预算办理、资格材料登记及真实协议/KMS/价格/模型联验继续推进；这里没有授予真实资格、调用模型/KMS、修改 golden-case、部署或 push，也没有新增攻防。完整 M3/S1 出口仍保留。

本轮自建预览关闭、临时登录失效、合成管理员停用，[收尾核对](browser-cleanup.json)保留所有合成事实。独立临时库、共用运行时和 Temporal 保留；后续检查须核对新的 `s0_0763` head。
