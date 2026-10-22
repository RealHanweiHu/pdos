# M3 G0 审查修订与普通属主复验

2026-10-09，响应用户转交的 2026-10-08 Claude 只读审查。**第 1、3–6、8–11 项已修订并通过所列检查；第 2 项的新型号路径已改用 B3，同项派生/变体仍未完成；第 7 项当时待决，后续已按用户 P11 落实，见 [P11 验证](../g0-p11/result.md)。本页证据属于历史候选。M3/S1 未判完成。**

**候选时效补注（2026-10-09）**：本文件的 44 项与源码清单属于当时检查点。之后公共 service、api、bootstrap 等文件继续修改，旧清单已漂移，不能代表当前源码通过。[后续复核](../review-followup/result.md)已修复命令上下文串号和完整受众名单返回，并以新的源码清单完成 146 项受影响复验；历史日志与清单保留。

## 逐项结果

| 审查项 | 结果与范围 |
|---|---|
| 1 普通属主与 FORCE RLS | 从空库安装现行 S0/B3、M2 迁移及 M3 候选；数据库、schema、表与全部 45 个已安装 SECURITY DEFINER 函数属主均为 `pdos_next_owner`，NOSUPERUSER、NOBYPASSRLS。启用显式内部政策，运行角色不能继承 owner、不能创建 public 对象；AI 角色业务表直接 DML 为零。已有迁移的属主问题按统一策略覆盖，见 [实库清单](definer-ownership.json)、[现行含 definer 的迁移材料](definer-migration-sources.json)及 [生产方案](production-owner-plan.md)。 |
| 2 G0 领域服务与派生 | 删除 `m3_materialize_g0` PL/pgSQL 业务物化；Python 在公共命令的同一 Session/事务内调用 B3 `create_product`、`create_revision`、`create_project`，不另开提交或回执；数据库保留读写政策与原子守卫。G0 新型号、封存定义、项目、待办和回执仍全有或全无。派生/变体继续明确返回 `derivation_adapter_pending`，没有另写派生引擎；此项仅部分关闭。 |
| 3 T0/T1 来源 | T0 接 M2 的实际 DomainCommands/模型账本/工具调用/当前资格，AI 草稿记原运行与 AI 署名，人工值拒绝自动覆盖。T1 由可信宿主从实际图的 intent 定位原模型调用，保存不可变候选并绑定 `prepared_by_run_id`、`candidate_digest`；本人实质确认后保留 `ai_draft`、原 writer/run 与 `confirmed_by`。实际 Bootstrap 已接入建提案、条目与问题三种准备；注册图遇到人工值保护时转 T1，不能把候选当成功回执。篡改、伪造运行、取消后的消费被拒绝，AI 问题转待办仍保留来源。 |
| 4 引用增量维护 | item.patch 只校验新添/改变的引用；删除引用与未改引用不重读原件。proposal_sources 增减 ref_count，只维护受影响行及私有来源计数，其他条目的共用引用保留。批准时仍按合同完整检查提案自身原件。 |
| 5 目标价与目标细分 | G0 同事务写 amount/currency/basis/includes_tax/as_of；缺失仍为 NULL。目标细分固定到实际本品类 kind=segment 的知识 lineage/version，写 product_target_segments；商业目标嵌套 source 进入统一引用校验。互相冲突的目标价要求退回处理，避免静默选择。 |
| 6 原受众判定 | 按有效可见性、有效品类成员、指定受众及全部历史评审人判定。受众记录对评审人不可见时由受控普通属主函数解析真实受众，不能以“未读到授权行”误判为新增。预览与决定共用同一结果。 |
| 7 availability 的处置规则 | 本候选检查时待用户决策；2026-10-09 用户已按确认稿 P11 决定，availability=unknown/conflicted 的规格（含 ai_draft）在批准前必须处置，not_applicable 豁免，提交不受此限制。实现与 AT-52 后续检查见 [P11 验证](../g0-p11/result.md)。 |
| 8 待办状态 | INSERT 守卫只要求 task 初始 assigned、risk 初始 open；CHECK 不再阻止后续状态。实库完成态更新检查通过；后续任务生命周期命令仍随相应业务闭环接入。 |
| 9 待办标题 | 标题取问题原文或参数名，处置说明独立存 note。 |
| 10 封存补洞 | 对封存定义的规格/来源 INSERT、UPDATE、DELETE 都拒绝；子项写入锁父定义，封存与新增串行化。原生定义及引用的不可变守卫保留，仅允许本次具名 G0 的一次封存转换。 |
| 11 来源类型 | 数据库 CHECK 固定 original/snapshot/knowledge/definition。兼容入口 artifact 在受控服务中归一为 original；非规范值实库插入被拒绝。snapshot/参数字典消费仍未接入，不用未核对引用冒充事实。 |

## 证据与覆盖

最终独立目标为 `127.0.0.1:54731/pdos_test`；仅合成数据。完整迁移由普通 owner 执行，bootstrap 超级用户仅用于本地角色/数据库/扩展初始配置及私有备份，没有担任业务迁移、业务表或 definer 属主。

- [M3 最终组装候选](final-m3-composed.log)：44 项通过，包括实际 HTTP/领域事务、普通属主、封存 INSERT 拒绝、资格撤回、T1 确认与取消、原受众、注册宿主准备及图回退。
- [实际模型绑定与注册图](final-binding-graph.log)：58 项通过，无真实模型调用。
- [品类/公共证明/B3 定义](final-b3-common.log)：32 项通过；[B3 项目创建](final-project-creation.log)：10 项通过。按影响补验，未跑与本轮无关的完整计划/全工程验收。
- 共 144 项受影响检查，计数与 JUnit 文件见 [检查清单](checks.json)。首次 40 项和定向诊断用于定位，最终结论以上述组装候选为准，不累计重复检查数。
- [实际 schema 对照](owned-schema.json)：12 张候选表无元数据差异；16 个函数正文一致，4 个递延原子触发器、3 个封存触发器及原生补充字段齐全；M3 未改变活动 Alembic head。
- 受影响代码规范与空白检查通过；[最终源文件指纹](final-source-manifest.json)复核无漂移。共享 B7 接线保留当前实现，没有撤销其他工作流修改。

本轮未改前端；[首个人工候选](../early-g0/result.md)中的浏览器、亮暗/尺寸及构建证据仅属于当时 UI 候选，不充当本次新后端的全链验收。原超级用户属主证明不足，本轮普通属主证明取代它。

## 剩余工作与恢复条件

派生/变体需要在 B3 原生定义与项目绑定上汇合变体命名空间：现有 VariantRevision 保存有效定义 JSON，而 DefinitionRevision 仍以型号×revision 唯一，ProjectProductLink 只指向型号定义。必须通过 `variants.py` 的唯一引擎完成固定父版、变体定义 v1 与项目关联；当前不伪造独立型号或另一套派生逻辑来绕开它。

第 7 项已在后续 P11 检查点关闭。知识/字典完整写入、证据/共享、剩余页面与视图、分组候选选择、整次运行撤回、实际模型/Temporal 整链及正式 AT/性能/迁移恢复出口仍待后续闭环。知识表目前只是 G0 固定引用所需的只读基础，不能称知识业务已完成。

正式迁移按 B7/B8 汇合后的真实 head 单调分配，候选仍在 `migrations/candidates/`。公共 T2 确认已允许无期限，本轮候选对 confirmations.expires_at 的可空一致性作补充，正式迁移需一起收口；未改回公共政策或覆盖旧迁移。

## 环境收尾

本轮诊断、增量调试和最终普通属主环境分别保留元数据与私有备份，最终环境已备份停服、容器和数据保留，见 [收尾记录](environment-closeout.json)；诊断环境见 [首次诊断收尾](environment-closeout-diagnostic.json)、[中间候选收尾](environment-closeout-intermediate.json)。只操作自己的标记环境，没有使用共享业务库、旧原工程库或真实客户材料。无真实资格授予、真实模型调用、外发、git push 或生产变更。

失败原始日志继续保留，包括最初迁移顺序、普通属主权限、原生来源、公共 T2 字段及增量准备/受众定位记录；它们是已定位并修复的候选历史，不能替代最终通过记录。
