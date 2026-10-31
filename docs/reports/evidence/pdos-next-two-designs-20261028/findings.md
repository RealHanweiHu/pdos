# 续建所需的代码与环境依据

本文件是取证/恢复资料，不是活动进度清单。进度与范围以唯一清单和 task_plan.md 的验收映射为准。

## 工作状态接线

- 模型输出仍用原 `WireAgentOutput.result_json`，不扩大工具写权限；约束提议键为 `context_proposals.constraints`，原话证明与删除记录在 `agent_kernel/work_state.py` 校验。服务器只持久化经核验的会话元数据。
- `KernelStore.finish`、本人取消和普通 Activity 失败在终态事务追加状态。`record_finish` 用 `session.no_autoflush` 防止先写终态再改元数据，最终显式 flush 与外层事务一同提交/回滚。已有终态重放不追加第二版。
- `Bootstrap.project_context` 把工作状态冻结在 `AgentRun.versions`；`check_conversation` 同时复核冻结状态来源。`BoundHost.skill_context` 的原快照签名包含完整投影；`omitted_fields` 必须匹配快照中的字段删减记录。
- 现行网页 `withMaterialContext` 把附件页数据拼在 goal 末尾。工作状态对已知页面边界后的文字拒绝作为目标/约束证明；该措施是旧格式的保守处理，未来新的材料格式应保留独立且明确的数据边界。
- UI `WorkStateCarry` 接在共用 `RunContinuation`；API 路径从 `agent-runs` 切到 `agent-sessions/{id}/work-state`。个人用完整 personal 路径；品类工作台传 scoped api，所以 root 仍可用 `v1/agent-runs`。
- 新表只保存技术会话状态；来源消费边仍归原 Run.read_sources 与实际领域事实，生命周期分类沿用既有 Agent 工作产物策略。没有把状态当作业务事实、资格或权限。

## B 的现有基础与缺口

- 现行 `agent_kernel/domain_reads.py` 提供品类知识/参数等结构读取，`project_object_reads.py` 提供项目相关结构记录；`research/search.py` 是公开搜索，不能当作企业检索。
- `models.Outbox` 是 `outbox_events`；派发实现入口 `pdos_next/dispatch/outbox.py`。企业投影须接此持久事件/Activity 机制并保留重建和水位，不能在用户请求里做无限重建。
- 企业知识同时有品类的原有知识条目和 `domain/knowledge/models.py` 的 candidate/rule version/current 表。草稿不等于具名发布的当前规则，SourceProjector 必须明确 nature、current/withdrawal/scan 与受众。
- `source_for` 在 `pdos_next/service.py`，不是 preproject.provenance。它检查权威 Artifact/受众/原件安全；历史判断先检查安全与撤回，再比较旧 revision，避免用 SOURCE_STALE 掩盖扫描/撤权。
- 后续已固定 jieba 0.42.1/字典/停用词与 OR + DF/BM25、工程编号通道，新增 `enterprise_search/` 的两类来源投影、普通 RLS 权威连接、人用元数据检索 API、真实 Outbox/Temporal Activity 和受限重建。当前尚无 assistant.search/extract/passage.read 或 embedding profile；主模型资料出站与物理隔离尚须接续，不能直接把人用 API 注册成工具。
- WorkState 当前的焦点还不是全量读工具对象集合；候选保存的是事件引用，不能将其直接称为当前 pending/adopted。B 引用继承与 X2 接续时一起补这两部分。

## 安全验证环境

- 只复用 `pdos-next/.local/runtime.json` 经 `tools/local_environment.read_state/verified` 核对的 53502 / pdos_test，marker `f117bb5b-b3d7-4286-aaec-c54d9255e96b`。不得打印 URL 或回退 .env。
- 当前真实 head 为 s0_0828；原 0825 备份保留，后续另有 `.local/enterprise-53502-before-0826.dump`、0827/0828 同名备份。新迁移往返和记录数核对见企业关键词检查点，不清理或改写历史。
- `/tmp/pdos_two_designs_tests.py` 仅核对该既存目标并执行显式 pytest；新证据文件名不得覆盖。已存在的另一份 x1 helper 输出到旧目录，不用于后续新范围。
- 前端构建在 `/tmp/pdos-work-state-build-20261028/pdos-next/web`，659 输入复制并链接原 node_modules；不碰源码 `.next`。首次字体代理被 sandbox 拒绝，后续允许网络的同副本构建通过。构建输入与当前源码已有指纹比对。
- 本轮无真实模型/embedding、真实业务出站、钉钉发送、生产或 push；真实质量/缓存/时延、人维护题集仍保留条件。

## 企业检索与生命周期续接细节

- `enterprise_search.sources.catalog()` 以普通 RLS 的 UNION 关系绑定来源，查询再按 tenant/category/type/id/revision/hash 与派生索引连接；不可用投影 partial，不引入 ACL 副本。扫描证明在同一只读快照批量核对。
- `workflows.transport.TemporalSender` 会把索引工作流 ID 回给 Outbox；原件安全工作流 ID 优先保留。`EnterpriseProjection` 独立轻量工作流只调用索引 Activity，不是另一 Agent。
- 重建按本人实际可读集合执行，个人入口按每份来源的权威品类重新绑定；管理员误改派生行范围/物理缓存损坏的完整恢复和大型候选规模检查仍待后续，不把 healthy rebuild 说成全面灾备。
- s0_0827 恢复 12 张已登记消费表漏装的引用/时钟触发器；s0_0828 保留实际 T1 `field.feedback.locate` 的同事务版本 CAS。全部前版函数精确冻结，原字段/租户/品类/受众与收据守卫保留；无泛化改绑例外。
- 本机旧 Temporal 进程已退出，后续在同一标记、二进制和本地 SQLite 历史上恢复开发服务。测试用随机专属队列，worker 仅有投影 Activity；没有启动真实模型 worker。

2026-10-28 引用续建：来源身份由实际不可变读取账本签发，不新增权限副本；历史页应复核实际 conversation.history 结果，分页描述本身不含 turns。知识 Current 指针变化也须标注已更新，即使旧 entry 的版本和字节不变。源资料失效与历史更新需在 UI 分开处理；最新证据见[引用检查点](../pdos-next-enterprise-citations-20261028/result.md)。

## 行动整链的代码续接依据（2026-10-28，只读取证）

- §11.3/§14.1 要求“品质历史经验→准备复验请求→本人确认→可再次打开”；不是仅展示按钮或返回裸 command。`Bootstrap.prepare_candidate` 目前只有 CONTENT_OPERATIONS 和特殊 category/claim/snapshot 分支持久化可见候选，其他操作只返回 event_id 为空的 candidate；`domain_candidates.read` 与网页 `lib/domain-candidate.ts` 也未覆盖验证准备/请求。后续应接真实候选账本和原预览/确认/幂等恢复，不能只给网页增加 operation 标签。
- 真实公共 payload 在 `domain/verification_front/schemas.py::RequestCreatePayload`：request_id、固定 preparation_id/revision/sha256、reason；不能用旧纯领域 DTO 中 title/purpose/items 直接替代。技能包与 command_usage 也明确先 `verification.preparation.record`（T1），再按固定准备记录建立 `verification.request.create`（T0）；无 T0 资格仍应保留具名确认，不改现行档位。
- §9.3 的 I14/I22 需要对实际已发行 citation/source 与目标受众逐项核对，候选形成及确认时由服务器重核；已有 Run.read_sources 只表示显式 Artifact 读集，不能将企业搜索得到的其他对象 ID 直接塞进它或当成授权。客户派生标记、私有或指定受众限制必须沿同一来源证据传播。
- 本轮只是为下一闭环定位接口，未修改上述生产文件、合同或权限；资料比较最终候选继续保持冻结。先按 v1.1 和具体领域准备记录补齐当前适用性/依赖读取，再确定最小候选适配范围与受影响测试。

## 显式关系与范围补查续接依据（2026-10-28）

- 本轮一跳入口是 `enterprise_search/relations.py`，只取质量快照的 CAPA/合并、变更 roots/references 的固定版本，以及 Build 与执行/供应/TestRun 的真实父引用。两端均经权威关系、普通 RLS、原件扫描和当前范围过滤；已直接命中的对象仍保留一个真实关系入口，不重复计数。新关系来源的原对象 ID/版本/hash 会进入不可变读证明，继承引用重签不删除该约束。
- `navigation.py` 生成当前对象入口；CAPA 必须解析到所属 Issue ID，不能把 CAPA UUID 当 Issue 选择器。问题的首个固定 FailureRef 带 Build 引用，先经 Build RLS 才放入路径；TestRun 和供应从真实行取父 Build。SourceCard 保留固定引用，链接明确打开当前对象；BuildSummary 只从实际授权列表接受目标，读取不提交命令。
- 外部等待的 `target` 是 Text，不能据其文字推断图边；Snapshot.build/replaces 才是可继续接入的显式 VersionRef。本轮不声明所有来源的全部关系或所有对象入口已齐。
- `is_current` 只说明固定版本是否为当前指针；当前业务适用性/继续执行仍须经领域服务重核。例如 `quality_execution.service._view` 会读原失败、当前专业政策和资格。不能把 RAG 的 is_current/read_basis_status 或 record_policy 文案当作执行许可。
- 下一闭环同品类补查：按设计少于3条有效候选触发一次，客户私有资料须本人显式选择，模型过滤只能收窄。WorkState 当前 ChangeInput 要求 item_id 且只有移除/排除三种动作，宜增加独立且封闭的人用输入分支；`AgentWorkState.body` 当前仅有 JSON object 约束，新增技术选择仍须核对实际 schema/触发器，不把偏好当授权。
- 知识依赖版本更新保留仍须补齐：当前 knowledge→Artifact/Claim 检查较严格。若 Claim 根来源可能改变，必须先冻结旧根的可读/扫描足迹并同时复核旧根与当前 Claim ACL，不直接放宽 revision 判定，避免旧根撤权后历史回答被新根权限遮蔽。

### 同品类补查的现有接点（下一闭环的只读核对）

- 当前 `AssistantReadAdapter.search` 将 Run 的 product/project/proposal 强制写回 selectors，模型只可收窄；`current`/引用账本复核绑定的是实际 requester + tenant/category，并没有把检索 project 条件当成读取权限。补查须由服务器在当前有效候选不足三条后单次触发，不能新增可由模型传入的扩权开关。
- 设计 §7.1 要求默认排除其他客户项目私人资料、支持用户本人点选纳入，以及“只查当前项目”的持久选择。现有 `work_state.ChangeInput` 只有移除约束/排除来源/恢复排除三种人用编辑，须增加明确的人用范围选择并在 Run 冻结，不能通过模型 context_proposals 授予。
- 补查应保留原 project/product/proposal 作为当前对象/分组依据，仅由服务器从已核对品类构造补查查询。来源受众、原件扫描、当前权限、引用隔离与 I14/I22 行动携带仍逐层复核；关系来源数量与组别需明确，避免用未授权或扫描失败元数据触发错误的覆盖声明。

## 同品类补查实现后的续接依据

- `assistant_scope.retrieve` 在来源复核后决定阈值；人用 `SearchPreferences` 从 work_state 冻结，补查查询不改变 Run 范围。客户敏感过滤在直接与一跳计数/分页前执行；原生 Issue 可能继承客户原件类别，默认无命中不等于范围丢失。
- 本人范围选择是来源无关的技术偏好；旧私有上下文不可带入时仍保留，不继承旧来源权限。`conversation.prepare` 的 Session FOR NO KEY UPDATE 继续序列化续接并兼容工作状态外键 KEY SHARE，真实并发已验证。
- 5个既有阶段工具的技能声明已补齐原档位，工作技能版本改为0.1.1-draft；不继承旧版本资格。新增 work_state 字段已登记封闭技能上下文合同。
- 当前实际浏览器只用了合成账号与禁用推理派发的临时API，专用服务/浏览器及临时token文件已收尾。构建公共字体网络受阻，使用前次实际字体二进制的临时测试覆盖，产品源码与665个构建输入一致。最终环境仍53502/pdos_test、s0_0830，无新迁移。[本轮证据](../pdos-next-enterprise-scope-20261028/result.md)。
- 下一闭环优先补当前领域适用性/知识旧依赖足迹，再做明确I14/I22与verification.preparation.record→request候选；不能把RAG当前版本或本人范围偏好当作执行许可。

## 对完整判据的再核对（知识依赖检查点）

- 上下文设计§11明确把单条结果上限/result.read、服务器信封/字段删减可见和必需内容超限context_incomplete归到X2；X3是运行内清理、进度与两档F评测。验收映射已纠正，工作状态基础不代表X2完成。
- RAG§6.4默认快档初始最多提取3个来源，深入查应有计划说明与同会话后台续接。当前ExtractInput仍仅有max_length=8的通用上限，尚无已核对的快/深入流程差异与按钮闭环；不能据有界读取宣称快慢两档完成。
- RAG§8.3除差异表外还需阻塞清单、案例表、评审清单、承诺表的逐格引用/未知与责任人日期不推断。§11.11还需完整对象/版本/指定片段/不相关反馈纠正；现有排除与范围选择只是部分能力。
- 问题集v0和上下文评测题都要求人工维护，自动化不能把pytest材料写成golden-case；recall@5/10和真实质量/时延、两档F对比尚不能由当前控制流测试替代。

## 知识依赖历史实现后的续接依据

- `assistant_dependencies.py`固定实际根身份/版本/hash/原件，存于签名读结果；只是足迹，不是ACL。`assistant_sources.current`同时核对旧根、当前Claim、当前扫描，元数据历史与精确主正文分开；旧账本缺足迹且依赖已变仍拒绝。Claim数据库守卫仅允许具名撤回，不能按可变根设计夹具或放宽该守卫。
- 依赖更新后的原KnowledgeEntry可用原固定正文；`fixed_body_available`由服务器根据主版本/hash决定。人用引用API只从已授权Run/CID进入历史读取；Agent仅对服务器继承的引用允许历史依赖，当前新读漂移仍拒绝。前端严格true才展示更新引用的原片段，后续不可读清空内容。
- `enterprise_search.api.searching`仍直接调用元数据query，knowledge目录的字面private=false/original_ids=[]尚未统一展开依赖。当前Assistant在分页后复核会丢弃不可读依赖；后续须把知识依赖的授权/扫描及真实类别推进计数与分页前，覆盖人用元数据入口，不能仅以历史读取测试宣称所有召回元数据无泄漏。
- 下一行动闭环仍需真实候选账本支持verification.preparation.record，再按固定preparation版本/hash产生verification.request.create；`domain_candidates`和前端domain-candidate目前主要按CONTENT_OPERATIONS处理。Source audience/customer足迹必须在准备候选和确认时重核，不把查到引用当作目标受众许可。
