# 同品类补查与本人范围背景条检查点

日期：2026-10-28（本地）。本轮补齐当前项目/提案不足有效候选时的同品类补查、本人范围选择及输入区背景条。原六项既有失败在本最终候选再次 **6/6 通过**；完整两份设计仍在建设，真实模型与 embedding 按用户要求暂不调用。

## 可用行为

- 先按实际 Run 绑定的项目或提案检索，经权威来源、当前权限、版本与扫描复核后，少于 3 个不同有效来源才由服务器补查同一品类一次。原 Run 的品类/型号/项目/提案不改写；模型检索输入没有新增扩大范围开关，类型、日期等收窄条件仍保留。
- 默认排除同品类补查中的客户私人资料（private 且 customer_original）；本人内部私人资料仍按实际权限读取。排除在计数和分页前执行。本人可明确选择纳入其他客户项目资料，也可选择只查当前项目/提案；选中不授予来源权限或领域写权。
- 首条消息保存本人选择；后续选择通过封闭的人用工作状态命令、CAS 与原请求幂等保存。运行开始时冻结选择，完成时保留运行中较新的本人编辑，模型 context_proposals 不得修改偏好。复用会话但旧私有上下文不可带入时，来源无关的本人范围选择仍保留，避免收窄偏好被意外重置。
- 背景条显示服务器核对的当前对象、查找范围和明确客户资料选项；支持修改/移除对象。保存失败可在折叠面板之外看到并恢复原请求。当前运行及旧引用保留原选择，下一条消息使用更新后的选择。
- 回答来源卡片区分当前项目/提案与同品类来源，仍保留固定引用、服务器来源身份和当前权限复核。实际历史 Issue 的默认排除及本人明确纳入后读取均已验证，原 Run 范围保持。

## 同一最终候选验证

| 范围 | 结果 | 证据 |
|---|---|---|
| 后端集中回归 | 59 文件 **468/468 通过**，0 失败/跳过；335 条运行时/依赖警告保留 | [日志](database-final.txt)、[JUnit](database-final.junit.xml)、[选择](test-selection.json) |
| 原六项既有失败 | **6/6 再次通过** | [逐项](original-six-reverified.json)、[原修复说明](../pdos-next-slice-a-x1-20261028/result.md) |
| 新增范围功能用例 | 5 个模块 10 项，包含在集中组；实际 G0 项目、客户原件/扫描、跨项目 Issue、HTTP→Temporal→注册图、冻结/恢复及真实并发 | [汇总](verification-result.json) |
| 前端 | **87/87 通过**；TypeScript、生产构建和目标 ESLint 通过 | [测试](frontend-tests.txt)、[构建](frontend-build.txt)、[ESLint](frontend-eslint-final.txt) |
| 源码/合同 | Ruff、87 操作/90 事件/63 场景覆盖、目标差异检查通过 | [Ruff](ruff-final.txt)、[合同](contracts-final.txt)、[差异](diff-check-final.txt) |
| 候选一致性 | 255 个受影响输入未变；665 个前端输入与工作树/构建副本一致（两组有重叠） | [源码](source-recheck-final.json)、[前端](frontend-source-recheck.json) |

真实并发用例定位并修复 Session 行锁与新工作状态外键之间的锁序问题：Session 键不可变，续接使用 FOR NO KEY UPDATE 继续串行化会话续接，同时允许外键 KEY SHARE；父 Run 锁与工作状态锁保留。并发本人编辑和续接均成功，不通过放宽事务或权限跳过冲突。

实测当前项目无命中、同品类两个可读内部来源、客户私人原件默认被过滤的范围读取：12 次暖读 p95 **0.173418 秒**，每次 SQL 数 [12]。同一集中组关键词 8 来源/12 次暖读 p95 **0.057021 秒**、3 SQL；原 1 秒与查询数门槛未改。这是当前合成规模，不能代表全来源规模性能。[本轮数据](performance-final.json)。旧候选的一次 1.023 秒超限和诊断保留，根因尚未确定，本次通过不抹除历史。

## 带认证的实际页面验证

实际生产前端对接独立测试库中的真实 RLS API，使用本轮合成账号，API 的推理派发被明确禁用。已完成本人范围/客户选项真实保存与数据库核对、刷新并重新打开会话、补查分组及固定段落读取、修改器移除对象进入个人工作。前后模型调用数与业务命令回执数不变，原 Run 仍在原项目 completed。[浏览器记录](browser-result.json)、[落库历史](browser-scope-history.json)。

1280px 亮/暗、390px 亮/暗、320px 暗色已截图并目视检查；无页面横向溢出。原生范围摘要可用 Enter 展开/收起，Tab 可到输入框；320px 收起后输入框在可视范围。手机展开范围选项会增加高度，收起后恢复输入布局。[桌面](output/playwright/desktop-light.png)、[手机](output/playwright/mobile-dark.png)、[320px 键盘](output/playwright/narrow-dark-collapsed.png)、[来源段落](output/playwright/restored-source-dark.png)。专用浏览器/API/前端已停止，临时登录文件已删除，共享服务未操作。[收尾](browser-closeout.json)。

构建最初受公共 Google 字体 TLS/网络重试阻塞，保留中断日志；后用前一成功构建中的实际 Geist/Geist Mono 二进制做临时构建输入覆盖，产品源码未改。第一次覆盖 CSS 的本地路径格式未被 Next 字体重写，浏览器发现后按实际 loader 格式修正；最终构建通过，11 个字体资产均自托管，实际浏览器字体 loaded。[字体来源](frontend-font-cache.json)、[网络中断](frontend-build-network-interrupted.txt)、[路径失败](frontend-build-cached-font-path-failure.txt)。此处不宣称公共字体网络访问已恢复。

## 实施中暴露的问题及修复边界

- 严格技能上下文投影首次拒绝新增 work_state 字段；只补入 search_preferences/search_context 的封闭 schema，未放开额外字段。[首轮](scope-authority-temporal-first.txt)。
- 已注册的 5 个 work.stage/work.baseline 工具遗漏技能声明；补齐原 T1 与 T2-prepare-only 档位并递增技能版本，42 项覆盖通过；没有新增操作、T0 资格或 AI T2 执行权。[修复验证](skill-coverage-fixed.txt)。
- 原生 Issue 首次看似未跨项目命中，实际因来源继承了客户私人类别而被正确排除；保留诊断，测试先断言默认排除，再用本人显式选择验证读取，没有放宽默认敏感过滤。[原失败](scope-business-and-regression.txt)、[原生验证](scope-business-explicit-customer.txt)。
- 首次他人拒绝断言预期 403，而私人资源按现行规则返回 404；断言接受现行 403/404。收窄偏好保留测试曾因夹具变量位置错误失败，纠正夹具后通过，原失败记录保留。分散通过不与集中组累计。

复用已核对的 127.0.0.1:53502/pdos_test，marker f117bb5b-b3d7-4286-aaec-c54d9255e96b，head s0_0830；四角色连接显式给出，不读 .env，无新建库/迁移。此前 71,300,987 字节备份与运行环境保留。[环境核对](database-target-final.json)。没有真实模型、embedding、真实业务外发、生产或提交/推送。

## 剩余范围

完整领域当前适用性/继续执行、知识等依赖更新保留、其余来源关系/对象入口、显式 I14/I22 携带与复验准备→请求行动故事、全索引损坏恢复和全来源规模性能仍须补齐。范围背景条不等于完整 X2；更多焦点对象/候选、非 RAG 成果及批量证明、个人偏好、X3 全局预算/result.read/固定缩减与进度，以及 C/E/G/D/F 依[完整对照](../pdos-next-two-designs-20261028/task_plan.md)继续。真实模型质量/缓存、embedding、钉钉发送与人维护题集/正式验收仍保留其实际条件。
