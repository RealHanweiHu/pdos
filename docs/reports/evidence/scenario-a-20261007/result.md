# 场景A：后台研究、候选有效性与研究质量（2026-10-07）

冻结验证实现见 [17文件候选摘要](candidate-manifest.json)，前端构建见 [1086文件冻结摘要](build-manifest.json) 和 [一致性核对](frozen-candidate-check.json)。本次没有新增迁移、生产操作、git push 或 golden-case 写入。后台工作及年龄限制已修复；真实候选保存整链尚未通过。

- 普通小Pai研究已解除全局导航与页面卸载拦截；按原范围保留会话，支持收起、跨页工作和后台完成/失败提醒。当前标签页刷新后只查询原回执，不重新派发模型。
- 修复浏览器断开时请求依赖关闭模型连接的缺陷：后台任务持有自己的连接和租约维护资源，工作结束后释放。服务器停进程后的自动续跑不在本次覆盖内。
- 品类候选取消30分钟年龄拒绝，仍须研究完成、当前原件/权限有效、最新消息、原摘要、去标识确认和T1一次采用；事务与幂等重放保持。
- 正文提取优先main/article，去除导航、页脚、追踪同意、隐藏促销等噪声，保留段落和规格行以及链接发现。引用标明页面标题来源和实际发布站点；失败严格绑定该次工具和目标。
- 修复真实网关过滤丢弃preproject目标/前次追问，以及研究覆盖、候选URL、失败对象、来源发布者的接线缺口。只允许明确领域字段；账户/权限管理字段、私有原始材料与其他未列字段继续过滤。
- 原固定提示词保留，本轮冻结验证的品类候选使用preproject-dialogue-v6、普通对话使用xiaopai-reply-v6。宽泛研究要求分路线补查，最终摘要与结构化候选分工，减少重复输出。已批准运行策略及实际4000 token输出上限未修改。
- 实测还发现嵌入视频的title拼入文章标题，已修复为文档元信息优先、正文首个h1后备，忽略iframe内标题；规格表格单元格保留间隔。[八份原件只读重解析](actual-source-title-audit.json) 确认OutdoorMaster文章不再拼接YouTube标题；未改写既有快照或引用回执。
- 已准备独立的8000输出策略、服务端品类/提案选择与计量资格不足拒绝守卫，默认关闭。真实发布包仍只合格4000，扩大输出策略及资格需要对应明确批准；[可审阅方案与恢复步骤](proposed-output-budget.md)。

## 已完成的开发验证

后端集中检查 [首跑](backend-final.log) 84通过/1测试漏导入失败；修正后 [原失败病例复核](backend-final-recheck.log) 1通过，共85个不同病例。覆盖受控研究实际网关载荷、当前权限/原件变化拒绝、31分钟与24小时候选保存、一次去标识采用/重复确认、后台连接生命周期、正文提取、字段过滤和原预算守卫。此前 [50项回归](backend-regression.log)、[24项API回归](background-api-regression-final.log) 和 [8项过滤检查](context-projection-final.log) 为中间候选证据，不重复计数。[最终后端规范](backend-lint-final.log) 通过。

输出策略及嵌入标题后续变更的 [最终增量检查](output-candidate-regression-recovered.log) 98通过，覆盖策略采用、实际工厂载荷/冻结账本、原模型预算、后台生命周期、回复/品类API和正文提取；与此前85病例有重叠，不合并计总数。初跑 [18项失败](output-candidate-regression.log) 全因同期接入的持久执行服务未配置；补隔离测试开关后 [收集失败](output-candidate-regression-final.log) 发现新工作区包未在本虚拟环境路径内。最终显式设置当前仓库包路径及 `PDOS_AGENT_RUNTIME_MODE=injected-test`，仍核对同一自有TEST_DATABASE_URL后98通过；未移除生产持久执行要求，也不将注入测试当作真实Temporal整链通过。

前端 [28项回归](frontend-final.log)、[类型检查](typecheck.log) 和 [受影响规范](frontend-lint.log) 通过；[冻结生产构建](build-final.log) 通过（98页），1086个源文件摘要与工作区一致。

98项检查及收尾后，共享源码 `conversation_reply.py` 将两处提示词选择改为v7；核对仅这两处变化可还原并匹配本轮v6冻结摘要。保留已验源记录，不覆盖并行工作，也不将v7普通对话/品类真实生成计入本轮通过；17文件中仅该文件与冻结候选不同，前端1086文件仍一致，见一致性核对。故本记录不是当前共享源码的全仓/真实保存联合门禁通过声明。

所有repo数据库检查仅使用显式TEST_DATABASE_URL，目标为新建、自有容器 [隔离目标](test-environment.json) 的pdos_test；未在存续57432执行测试，也未回退.env数据库。最初缺pdos_agent角色失败见 [原日志](backend-initial-role-failure.log)，只在自有库初始化角色并配置锁容量。旧夹具直接修改产品线投影成员，被0426共同来源守卫拒绝，见 [原失败](background-api-regression.log)；夹具改为撤回品类唯一成员来源，现有数据库守卫保持。

## 真实浏览器与公开资料研究

仅使用全新合成租户和公开桨板泵输入，沿现有合格模型/计量配置；不声明产品八能力资格或人工Exit通过。验证使用隔离3063/8863与自有pdos_test。GUI工作采用 [web-access Skill](/Users/huhanwei/.codex/skills/web-access/SKILL.md)。

中间失败全部保留：

1. [断开连接失败](real-research-disconnect-failure.json)：初版刷新导致请求清理关闭模型连接；修复前的真实失败，不能当作后台研究成功。私有备份见 [备份指针](disconnect-backup.json)。
2. [长度截断](real-research-truncation-failure.json)：后台刷新后继续执行，第二轮达到4000输出上限，未生成可保存候选。未放宽预算；改进字段接线和紧凑完整候选结构。
3. [格式失败](real-research-schema-failure.json)：紧凑提示词早期版本在目标字段仍被过滤时失败，随后补齐实际出站字段并明确篇幅只适用于ready候选；原失败保留，私有备份见 [备份指针](quality-failure-backup.json)。

[桌面后台导航](background-navigation-final.png)、[390px浅色](background-narrow-light.png) 与 [390px深色](background-narrow-dark.png) 均能收起研究面板并继续使用导航。临时视口恢复默认。

最终 [真实样本](real-research-blocked-4000.json) 完成三轮搜索、保存八份公开原文；离开面板、跨页及刷新后仍继续原请求，没有新增模型POST。OutdoorMaster日文产品页429被准确记录在该网址，其博客成功读取，不能把这次失败归到另一品牌或当作没有资料。第四次模型输出达到4000而截断，终态 `PROVIDER_OUTPUT_TRUNCATED`；[其他页面的失败提醒](background-terminal-failure.png) 可见。四次模型调用均有known用量，共39,440输入/8,699输出/48,139 token。没有完整候选，没有实际T1保存或品类创建，浏览器保存整链不能标通过。

研究质量仍有实际缺口：样本有八份原件及多个品牌线索，但两次查询使用2024关键词，官网规格、地区/时效及热门程度证据尚未全面核对；来源数量不能等同候选内容可靠性。紧凑提示词未解决真实截断。当前 [只读资格核对](current-output-qualification.json) 确认实际MiniMax-M3发布包输出上限4000、输入资格17000且8000开关未启用；不再在条件未变化时重跑相同真实请求。

最终真实样本及回执已私有备份，[指针及摘要](final-real-backup.json) 保留；各次失败备份和最终检查后备份均核验摘要/恢复目录。自有测试租户已清理、3063/8863及自有容器停服、容器/卷保留，临时浏览器关闭且视口复位，见 [收尾记录](cleanup.json)。共享3000/8000由其他工作维护，本次未停止或重启，也不以其当前页面冒充本隔离候选加载验证。

下一步只等待8000策略及真实计量资格变更批准，批准后按方案核验并补真实候选保存整链；原未知用量、真实八能力资格和人工Exit仍保持独立未完成状态。
