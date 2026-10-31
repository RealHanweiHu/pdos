# 小Pai企业关键词检索基础与生命周期相容修复

2026-10-28。完整目标仍为日常助手/企业 RAG v0.4 和上下文 v0.2；本检查点交付企业 B 的两类来源检索与投影公共基础。用户要求暂不调用真实模型继续生效；本轮模型、embedding 和真实业务出站调用均为 0。活动状态只见[唯一清单](../../../../tasks/ai-native-integrated-todo.md#current-queue)，全设计验收映射见[范围对照](../pdos-next-two-designs-20261028/task_plan.md)。

## 可用能力

- 固定 jieba 0.42.1、关闭 HMM，固定随包词典、领域词表和停用词表并计算版本摘要；整句用 OR 召回，按租户 DF/BM25、标题权重和长度归一化排序，普通查找加入轻量新近度，历史模式不加新近度。工程编号独立抽取、规范化并支持精确/编号族通道；日期不会识别成编号。精确对象 ID 优先，排序规则有固定版本。依赖来源见 [PyPI](https://pypi.org/project/jieba/0.42.1/)，版本与源码摘要由本地 lock 固定。
- Artifact/UploadedOriginal、品类 KnowledgeCurrent/KnowledgeEntry 共用普通 RLS 的权威来源关系；按固定版本/哈希生成有行号、字符偏移和原生 locator 的 chunk、tsvector 与 GIN 编号索引。索引不复制受众名单，不拥有事实，不调用扫描、解析或模型服务。
- 真实 Outbox 信封连接实际回执后才进入投影；重读当前执行者权限，核对事件、租户、品类、actor/requester、主体及修订。Temporal 专用 Workflow/Activity 持久执行；重复事件幂等，错误保留有界错误码并可重试。通用发送器保留实际索引工作流 ID，原件安全工作流的原身份保持。
- 投影与词频统计同事务替换；先锁租户再锁来源，避免多来源批次围绕共享 DF 形成锁循环。支持按本人实际可读集合重建，个人全局重建由服务器按各来源的真实品类绑定。重建不改变业务事实、领域回执或资料受众。
- 本人个人/品类 POST 检索接口与 BFF 返回元数据：标题、固定来源版本/哈希、locator、范围、正文性质、排名和命中通道；返回数量在权威过滤后计算。无正文、存储键、向量、词频或分数。条件只能缩小范围，租户/身份/可见性参数拒绝。接口无 Run、模型或读时重建。
- 原件当前扫描证明按一批 SQL 复核，沿用既有纯规则；扫描规则变化、撤回或撤权即时影响新查询。召回、健康检查与返回使用 API 的同一 REPEATABLE READ 只读快照。返回查询 as_of、可读索引检查水位和 generic partial 提示，不暴露不可读来源的 ID 或计数。

## 发现并修复的既有生命周期缺口

集中目录校验暴露两项失败。已补齐 6 张既有表及 3 个既有列的显式目录：收件箱消息/阅读状态和项目分组只记元数据；项目治理事实继续要求实际来源守卫，既有 PlanProposal 保留资料消费分类。未知表/列仍使检查失败。

真实数据库还缺少目录已要求的 12 张资料消费表的 24 个通用触发器。s0_0827 补齐 BEFORE 引用守卫和 AFTER 品类时钟，保持普通 owner、强制 RLS 和原权限。补齐后，现场反馈由未知范围经 T1 定位到实际项目的一项既有整链被通用不可改绑条件误拒绝；s0_0828 只识别实际 `field.feedback.locate` 同事务版本、具名确认引用、精确前版/修订、同 tenant/category/owner/visibility 和单步 Current CAS，其余守卫逻辑保留。原领域同事务回执/确认/审计守卫仍生效，未取得新的 AI 写入权限。

故障注入在回滚事务内临时禁用原 field Current CAS 触发器，验证通用生命周期守卫独立拒绝没有新定位版本的改绑；随后正常 T1 定位、变更评估和来源保留整链通过。禁用任一补齐的通用触发器时，schema coverage 仍立即失败。

## 验证证据

**最终同候选集中验证 135 项全部通过，0 失败、0 跳过**：[完整日志](database-final-0828.txt)，包括[六项既有失败逐项复验](original-six-reverified.json)、检索/Temporal、会话状态与私有成果、实际来源证明、生命周期目录/负例，以及外部等待、风险、知识、现场反馈/变更和项目治理。182 条既有依赖/运行时 warning 保留。下方定向组与集中组有重叠，不累计成另一总数；61 个源码输入在验证后[保持不变](candidate-check.json)。

- [检索最新候选](enterprise-final.txt)：21 项全部通过，含真实本机 Temporal 重试/worker 重启、OR/编号召回、当前/历史知识、私有与跨租户、失权/撤回/扫描变化、重放、失败恢复、并发 DF、范围缩小及 API 参数负例。
- [现场定位修复定向](field-location-repair.txt)：4 项通过，含合法链、独立守卫负例、真实 schema 与触发器；属于集中组的子集。
- [纯检查](pure-final.txt)：57 项通过，含披露、上下文投影、工作状态、窗口、执行图和冻结目录。
- [前端与类型核对](frontend-snapshot.json)：21 项 BFF/续聊/本次携带测试通过；目标 ESLint 通过；隔离副本 TypeScript 通过。659 个前轮生产构建输入中只有 BFF 路由变更，隔离类型检查输入逐项匹配当前源码；本轮没有重新声明完整生产构建或新弹层浏览器通过。
- [Ruff](ruff-final.txt)：通过；最终输入见 [source-manifest.json](source-manifest.json)。共享工作树中既有改动保留，指纹不表示全部内容均由本轮编写。
- [查询指标](query-metrics.json)：8 份合成可读资料、12 次本地暖读，p95 约 0.38 秒，4 次检索 SQL；条件校验和原件证明各加一批 SQL。该指标不含 HTTP 鉴权和事务准备，不代表大数据规模或真实模型时延。
- [s0_0826](migration-0826.json)、[s0_0827](migration-0827.json)、[s0_0828](migration-0828.json)：每次先核对同一 53502/pdos_test 与 marker，再备份、升级/降级/升级。0826 新表普通 owner/强制 RLS/Agent 零直接写已核；0827/0828 原记录数不变、24 触发器和精确函数往返通过。当前 head 为 s0_0828，三个备份保留，没有清库。

## 失败记录与修正

- [pg-first](pg-first.txt)：4 通过/1 失败，测试将 SQLAlchemy Result 直接转 dict；改为显式 `.all()`。随后 [pg-second](pg-second.txt) 9 项通过。
- 首次 Temporal 探测发现原本机进程已退出；核对原标记、存储与二进制后恢复同一开发服务，保留历史。没有启动能调用真实模型的完整 worker；验证专用队列只注册索引 Activity。
- [temporal-second](temporal-second.txt) 的观察方式错误：Temporal 内部重试尚未耗尽时不会为每次重试添加最终失败事件；改为核对真实 pending activity 的 last_failure。随后 [temporal-third](temporal-third.txt) 和最新集中检索组通过。
- [database-candidate](database-candidate.txt)：78 通过/2 项目录失败；[catalog-repair](catalog-repair.txt)、[catalog-repair-second](catalog-repair-second.txt) 保留逐步定位到列目录和缺少触发器的过程；没有跳过失败项或放宽未知 schema 守卫。
- [query-watermark](query-watermark.txt)：11 通过/1 失败，新增测试错误期待内部 INVALID_PAYLOAD；改为核对 API 既有收敛错误码 VALIDATION_FAILED，422 保持。
- [database-final](database-final.txt)：124 通过/1 现场定位失败。通过 s0_0828 修正与原领域 T1 定位的相容性，再对最终候选集中重验。

## 剩余范围与恢复条件

1. 企业 B 仍需 Issue/CAPA/Change、外部等待、供应承诺和 Build/TestRun 来源，一跳关系、个人化/同品类补查、服务器引用、物理隔离提取、回答依据/比较 UI、跨轮引用及三条回答转行动整链。当前企业检索只开放人用元数据接口，`assistant.search/extract/passage.read` 尚未注册；向模型提供资料前仍须完成出站分类、来源绑定和 I14/I22 检查。
2. 重建当前覆盖本人可读来源的健康投影；若缓存行被管理员错误改到不可访问品类或物理丢失导致统计损坏，查询会隐藏失配命中并标 partial，尚需补具备明确权限的整体派生索引恢复流程。大规模召回/扫描证明的候选规模与时延还需专门检查；不以小夹具替代真实规模证据。
3. X2 仍需更多已读对象固定版本、候选当前状态、批量 ACL 与检索引用接续；个人偏好、X3 全局预算缩减/结果续读，以及 C/E/G/D/F 继续按完整范围推进。当前超限守卫仅覆盖已实现的工作状态基础。
4. 真实模型/embedding 质量、缓存和服务商时延，人工维护的 golden-case 问题集、岗位材料与评审，以及真实钉钉接入，保持各自授权与材料条件。未写 golden-case；合成端口不授予真实资格、T0 或 T2。
5. 无生产、RDS/OSS/ECS、真实外发、git push 或原工程修改。未把本检查点作为完整 B/X2、两份设计或阶段验收完成。
