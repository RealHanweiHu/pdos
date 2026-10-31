# 两份设计完成度独立审计 v2（2026-10-29）

审计对象为日常助手/企业 RAG v0.4 §13 的 A–G 与上下文 v0.2 §11 的 X1–X3，共 **63 条 DoD**，并核对两份正文的关键合同与 RAG §14 矩阵。只读源码、既有原始证据和52题候选；未运行数据库、真实模型、embedding、外发或修改题集/清单。仅执行一次生产固定前缀的离线计量。审计后主会话已授权补下述本地差异；本报告记录发现时状态，实施结果另报，不预先判通过。

结论：现有证据支持大量本地机制与真实 PostgreSQL/HTTP/Temporal/浏览器链路，**不支持两份完整设计全部验收完成，也不能把剩余全部归为真实模型/用户条件**。发现三项正文实现差异与一项评测预算差异，均能在关闭实际外部调用时实施和验证。新题集的召回基线与失败保留诚实；合成 provider 的固定答案不是模型质量证据，原始回放输入长度也不是实际上下文压力。

## 可独立修复的差异

1. **历史模型前仍重跑完整读取。** 上下文 §5.1/§5.2 要求批量访问检查、运行内不重算正文。`agent_kernel/bootstrap.py::check_conversation` 对冻结页和每个已打开历史页再次调用 `memory`；`conversation.py::classify_turn` 对每条 READ 查询实际模型参数和旧结果，再执行历史 callback 并 digest 比较。`assistant.extract` 的 callback 还会以 body=True 重读正文。A/X1报告已明示“独立的批量 ACL 专用通道不在本交接实现中”。冻结/更新保留功能已通过，不等于该合同已实现。最小修复为从实际账本一次建立封闭依赖 manifest，模型前 union 所有已携带页后批量普通 RLS metadata/撤回/scan复核；内容更新只在下一次历史组装标 updated，不能当撤权。当前事实的独立适用性/版本守卫保留。
2. **Anthropic 精确计量端口未实施。** 上下文 §6.1 明确接近上限使用 count_tokens；`providers/agent_client.py` 无该请求，`gateway.py` 仅调用估算/上次 usage 校准。可以先实现受原出站与注册图约束的计数端口并用 MockTransport 验证；实际调用继续关闭。
3. **协议限制留存时无法关闭显式缓存。** 上下文 §8 要求按已登记协议关闭；`ProviderRoute` 无开关，`agent_client.request_body` 对所有 Anthropic 请求无条件添加 ephemeral。当前 retention_terms 仅登记/展示，不能自行猜测文本含义。需从服务器明确登记的当前协议事实导出开关并传至协议适配器；不能由模型参数声明。
4. **新上下文两档 F 在固定前缀前已不可准入。** 发现时 `rubric.md` 指定 F=8192/16384（W=14240/22432、输出2048）。实际 `disclosure(default_registry(), main, ())` 为61项工具披露（含 T2 prepare，**不是61种READ**），系统2850、工具与输出schema27644，固定估算30494、15%准入35069。两档任何题都先触发 CONTEXT_INCOMPLETE。仅W在DTO合法范围不代表可做正确率对比；应保留原预算失败，选择能容纳同一生产前缀的两档并记录实际运行压力，不缩工具面制造通过。主会话已安排修订，审计未预先宣称修复通过。

## 63 条 DoD 对照

编号按设计内每个切片 DoD 列表顺序追加，避免把正文中的交付项误算成额外验收。L=已有对应本地机制/实际链路证据（有范围与候选限制）；Q=真实模型/人工/试点尚缺；P=仅部分覆盖。L不表示新的最终候选全仓回归，本审计未重跑原检查。

| DoD | 核对结果与证据 |
|---|---|
| A1 普通零误检索/业务加载 | L：[A/X1](../pdos-next-slice-a-x1-20261028/result.md)，轻预载与服务器ordinary_answer；新v0一般问题尚未实模型回放。 |
| A2 单次general/not_run | L/Q：图与服务器标注覆盖；模型是否正常一次完成尚缺真实小样本。 |
| A3 三专用入口 | L：A/X1 79实际PG/API与入口投影证据，后续当前项目独立报告。 |
| A4 续聊/取消/后台/恢复 | L：A/X1与受控续读/当前候选实际恢复证据。 |
| A5 偏好本人隔离 | L：[偏好](../pdos-next-personal-preferences-20261029/result.md)，本人保存/冻结与peer隔离。 |
| A6 端到端p50/p95 | Q：无真实模型时延；离线检索96ms不能替代8秒观察目标。 |
| A7 真实模型合成小样本 | Q：按要求关闭。 |
| B1 HTTP→Temporal→图三类问题 | L/Q：assistant_temporal、project_current_context原始链路；合成provider证明路由/持久化，不证明答案质量。 |
| B2 原文隔离/注入/零write/skill | P/Q：隔离tool face与授权拒绝已有测试；新候选v0注入参数故障测试由其他代理追加；实际模型语义注入仍未测。 |
| B3 引用/定位/依据状态 | L：[引用](../pdos-next-enterprise-citations-20261028/result.md)、[共同候选](../pdos-next-enterprise-knowledge-authority-20261029/result.md)。 |
| B4 编号题 | L：v0四题完整编号命中exact_code，规则v2；只有当前候选四类，不外推任意编号。 |
| B5 跨轮/撤权 | L/Q：实际保存回答/历史/继承撤权测试；模型追问质量未测。 |
| B6 权限负向全集/关系无痕 | L：retrieval_pg、assistant_originals、知识依赖、关系与原件实际矩阵；新v0只有4私有负向，不能取代全矩阵。 |
| B7 检索后撤权partial | L：assistant_pg最终撤回、历史分页与工作状态撤权。 |
| B8 I14/I22候选拒绝 | L：[动作完整足迹9项](../pdos-next-action-footprint-20261029/result.md)及taint链。 |
| B9 未确认业务零写 | L：原复验/跟进的实际领域命令和快照。 |
| B10 检索/复核1秒与SQL | L：[71来源13类](../pdos-next-search-performance-20261029/result.md)，0.966/0.515/0.675秒、5/4/4 SQL。历史复核非同一实现，见差异1。 |
| B11 企业回答端到端p50/p95 | Q：没有真实模型25秒观察值。 |
| B12 v0召回/答案/成本指标 | P：28题实际检索，正向macro97.92%；QUA-04漏报告保留；答案、未知/该查没查、真实费用未测。 |
| B13 同品类不足补查 | L：[scope](../pdos-next-enterprise-scope-20261028/result.md)，服务器阈值、分组及客户私有选择。 |
| B14 比较无法对齐单列 | L：[比较](../pdos-next-assistant-material-workflow-20261028/result.md)，实际比较图/固定引文。 |
| B15 逐格引用/未知/负责人日期 | L/Q：[四类结果](../pdos-next-structured-answers-20261029/result.md)，字面和登记字段机制；分析语义仍需人工。 |
| B16 复验候选未确认零写 | L：[复验](../pdos-next-verification-action-20261029/result.md)，真实准备→确认→请求与恢复。 |
| B17 首期故事观察项 | P/Q：本地技术闭环和浏览器已连通；用户独立开始/省几次打开或复制/愿再用等真人观察未执行。 |
| C1 profile未确认零出站/客户默认排除 | L：[后台14实际](../pdos-next-embedding-background-20261029/result.md)。 |
| C2 共用权限/低权限exact与iterative对照 | P：小样本真实SQL两种路径均执行且共享私有过滤；无实际ANN planner/规模召回，报告已注明。 |
| C3 重启/Outbox/重建/换版/unknown占账 | L：后台、查询、原生来源恢复的实际证据。 |
| C4 固定正文/权限根 | L：权威目录连接、固定CID/正文子串，索引损坏不成为权限来源。 |
| C5 同题收益才默认 | L/Q：代码默认关键词；真实embedding同题质量收益未验，不得启默认混合。 |
| C6 实测时延/索引/覆盖/费用 | P/Q：本地合成与账本机制有值；真实服务商成本和模型总时延无值。 |
| D1 四岗位高频证据 | P/Q：四岗各10合成题就绪；不是员工真实高频问题/试点证据。 |
| D2 同题关键词/混合/人工成本 | Q：真实同题混合和人工修正未做。 |
| D3 不授资格/生产/外发/push | L：本次范围保持。 |
| D4 每片唯一清单与候选边界 | L：task_plan与最终本地报告均保留分段/去重，不冒充一次全量。 |
| E1 页面零模型/出站/权限/1秒 | L：[Issue](../pdos-next-similar-history-20261029/result.md)、[Change/标题](../pdos-next-similar-history-completion-20261029/result.md)。 |
| E2 归并T1与未确认零写 | L：原T1预览/取消/重新预览/确认。 |
| E3 摘要回链/as_of/导语/无模型降级 | L/Q：确定性摘要可用；真实模型导语人工抽查未做，当前未调用导语模型。 |
| E4 本人启用/权限/与我有关/继续 | L：摘要20实际与原生/浏览器设置、四问三组及本人钉钉选择。 |
| E5 无字段不空白 | L：相似历史结构化字段和渲染检查。 |
| E6 采纳率/不相关率 | P/Q：append-only opened/not_relevant/merge_prepared+排序版本记录；真实采纳/不相关率和版本对比无试点样本。 |
| F1 人工具名/ai_draft/去标识 | L：[核实知识](../pdos-next-verified-knowledge-20261029/result.md)、[完整足迹](../pdos-next-answer-footprint-20261029/result.md)。 |
| F2 到期降级/负责人提醒 | L：verified_knowledge排序needs_review；本人reminders API和知识页展示；原生日期检查。 |
| F3 周报隐私与阈值 | L：explicit Gap共享、无文字统计SQL、少于5隐藏与原件闭包测试。 |
| G1 未绑/撤销 | L：[17实际分段](../pdos-next-dingtalk-20261029/result.md)；真实官方网络未调用。 |
| G2 默认私发/群覆盖 | L：实际绑定/受众元数据与本地协议Mock；真实群发送未做。 |
| G3 客户派生过滤 | L：完整carried足迹与实际生命周期原件链。 |
| G4 业务深链重授权 | L：只读路由、原run/object/candidate链接；不在钉钉执行命令。 |
| G5 投递回执与钉钉provider | L：实际持久账本+MockTransport；不声称真实送达。 |
| G6 PDOS与钉钉同依据来源 | L/Q：同原Run/verify结果与私发投影一致；未做实模型两端问答质量对照。 |
| G7 不读群历史 | L：单条签名入站合同与未提供群历史读取端口。 |
| X1.1 候选/更新/history跨轮保留 | L：A/X1和当前候选11项；运行前复核方式有差异1。 |
| X1.2 撤权回答不出站/界面提示 | L：实际历史/分页撤权、UI字段；差异1不削弱既有功能结果。 |
| X1.3 内容更新不中断/撤权partial | L：冻结历史功能；实现仍重跑读取，不能视§5.2完全实现。 |
| X1.4 每调用分段token | L/Q：估算分段/actual总量、零调用不造usage；真实精确计量/缓存无值，另见差异2。 |
| X1.5 30轮不超F/固定缩减 | P：30轮历史分层PG＋独立准入/清理机制；未有新12题的真实30轮逐call压力/质量。原始33682tokens不等于最终S0–S6。 |
| X1.6 快照/check_messages | L：A/X1与受控续读/完整工具披露恢复纯测。 |
| X2.1 15轮约束/逐字拒绝 | L：work_state_pg::test_first_turn_constraint_remains_at_turn_fifteen_and_proposals_need_verbatim_proof。 |
| X2.2 删除不复活 | L：工作状态原生版本/修正CAS与冻结测试。 |
| X2.3 超长句柄/续读撤权 | L：[受控续读](../pdos-next-result-continuation-20261029/result.md)，原native read恢复、跨运行/隔离拒绝。 |
| X2.4 必需超限context_incomplete | L：模型账本/预占前停止与missing字段；错误F题集也正确被此守卫拒绝。 |
| X2.5 信封/工具/历史注入 | P/Q：结构、工具隔离和授权拒绝有纯/实际证据；模型行为忠实度需要实际回放，不能听合成答案断言。 |
| X3.1 长运行有界/保护项 | L/Q：[完整61工具披露机械测试](../pdos-next-x3-full-disclosure-20261029/result.md)使用9份明确synthetic_capacity；另有实际Temporal受限fixture。证明机制，不证明真实研究任务完成/质量。 |
| X3.2 四类题/两档正确率/人工维护 | P/Q：12题具备锚点，但发现时F不可准入；修正后仍需合法原生fixture、实际回放及人工审阅。题集非golden-case。 |

## 关键矩阵与证据边界

RAG §14的21个维度均能追到上述条目：普通问答(A1–2)、依据状态(B3/B12)、当前事实(B1/B5)、语义(B12/B15)、编号(B4)、引用(B3/B5)、跨轮(B5/X1)、排序(B13/E6)、权限(B6/C2)、隔离注入(B2/X2.5)、恢复(A4/C3/X2.3)、出站(C1/G5)、行动(B8–9/B16)、主动呈现(E)、知识(F)、钉钉(G)、体验(A/B17/E浏览器)、性能(A6/B10–12/C6/E1)、补查(B13)、比较(B14)、结果纠正(B15/X2.2)。矩阵覆盖是功能/控制证据映射，未测的语义/真人维度仍明确未测。

上下文 G1“不丢失”已有历史/工作状态/句柄/可见提示；G2“不溢出”有保守估算准入，Anthropic精确计量未实施；G3聚焦有固定信封、证据行、分段/进度，是否提升答案仍未评；G4有调用预算与缩减/缓存usage的诚实字段，真实值不可由估算补造。旧X3纯Host/受限registry证据不得替代完整生产披露；新完整披露测试自称机械验证是恰当边界。

保留的外部条件为：候选正式人工审阅、30–50员工真实题/真人试点、获授权真实模型/embedding/渠道；真实混合收益/缓存/时延/费用与答案正确率。上述本地实现差异修复并验证前，不能写成“剩余仅这些外部条件”。


## 审计后获授权的历史 ACL 实施候选

主会话追加授权后，已在 `agent_kernel/conversation_acl.py`、`conversation.py`、`bootstrap.py` 实施封闭的39种READ分类：实际模型/READ账本、显式来源、已携带默认历史与已打开分页、未引用检索候选、定义/BOM/知识旧根、研究来源、MCP当前合同/授权及T0回执都进入历史依赖；模型前只批量metadata/当前scan复核，不重跑历史reader、正文或网络。writer通过已核对持久Run的实际requester另开只读snapshot，原事务身份不变；终态Run不追加manifest。unavailable始终优先于updated。

**当前证据**：三个纯测试文件合组 **98 passed / 14.55秒**；八个改动Python文件Ruff通过，已跟踪目标diff检查通过。新增测试覆盖真实ReadBinding形状、默认A历史影响无自身READ的B后续撤权、初始隐藏历史不扩大依赖、固定旧根不被新根替换、MCP grant/expiry/connector digest、owner snapshot与terminal不改写。实际PG文件已collect-only成功（新增1项与原续聊14项），未由本代理连接数据库或调用模型。

主会话须统一执行 `tests/agent_kernel/test_conversation_acl_pg.py`、`test_run_continuation.py` 及原assistant保存/历史分页、当前项目历史相关实际组后，才能声明差异1已验证收口。原续聊两项callback假故障已改为实际Artifact版本漂移与真实Audience撤回；没有删断言冒充通过。差异2/3/4由其他已授权代理实施，本文不预判其最终结果。

### 主会话统一PG后的定向修正

统一PG首组实际为44通过、2失败，原始记录见 `../pdos-next-context-contract-completion-20261029/pg-history-run1.*`。其一是新合成完整披露夹具的wire字节预约超过API默认10万Run预算，尚未调用Provider；已给隔离queued Run配置与现助手PG相同的200万预算，不缩小工具集、不改生产预算守卫。其二是显式`read_sources`撤Audience后，普通RLS已隐藏整个Run，测试错误地把`None`传给`memory`；该夹具现走真实`store.finish→record_finish`保存安全原话，保留模型前拒绝，原话展示改用已认证HTTP owner投影，原结果/事件读取权限不放宽。owner投影由另一实施代理完成，仍须统一实际验证。

焦点run2实际1通过、1失败（17.93秒）：新增无显式来源的真实`assistant.search→extract→verify`读取撤Audience场景已通过，Host历史保留原话并隐藏回答；跨品类本人私有READ完整执行、同owner保留与一次metadata均已通过，末尾误把当前显式固定选择的`SOURCE_UNAVAILABLE`期望为历史错误。实际路径是`check_conversation→check_frozen→context_corrections.resolve`，当前选定版本预检先停止，历史批量尚未开始。修正候选明确断言该当前选择错误及历史metadata零次，再不改冻结选择地用原持久`conversation_access`独立验证该历史回答hidden与一次metadata，保留两层契约。此定向修正尚未由本代理执行数据库。


## 正文三项差异最终收口（2026-10-29 UTC）

上文差异表保留审计时状态；三项实现差异现已补齐并通过本地检查。历史冻结实际依赖并批量metadata复核、Anthropic近F计数单列技术账本、具名协议许可控制显式缓存均已接入。另用既有普通owner工作状态的current_goal保留RLS不可读Run的本人原话，API/目录/UI均支持hidden；不恢复旧body或动作权限，旧无工作状态记录仍不可读，不加0854/新权限。

最终236纯后端、57历史/会话/项目/Temporal实际组、12缓存/计数实际组均通过，实际两组去重69项；109前端、类型/ESLint/31文件Ruff、757输入生产构建和离线合同一致性通过。缓存两版确认刷新及原话hidden深链刷新实际通过，390px暗色已看，临时服务与新登录已清理。原失败候选保留。详见[最终收口报告](../pdos-next-context-contract-completion-20261029/result.md)。

这里的完成指本地实现差异收口；上文P/Q中的正式人工审阅、真实角色题/真人试点、真实模型/embedding同题质量、长会话正确率与真实缓存/成本/时延等仍未执行。遵守当前不调用真实模型的用户约束。

## 当前任务与项目历史续验

后续对正文当前项目场景的核对补齐实际 WorkTask/PlanTask、实际负责人、计划预测与承诺的区分，以及项目历史的完整来源闭包、成员变化和首次具名状态更新。`project-current-facts/v2` 与0854来源守卫已接入，保留v1历史合同和旧缓存相容。230项纯检查、41项去重原生、6项前端及TypeScript/ESLint/Ruff通过；0854备份、升降升与26个非空v2历史下拒降级均已验证，详见[本闭环结果](../pdos-next-project-tasks-context-20261029/result.md)。

四格定向补验使CTX-04两档均从partial补为bound；CTX-11低档预算停止、高档保留候选且零任务新增。它们是新候选的定向结果，不重写此前12题×两档24格的历史统计，也不赋模型正确率。

C2的大集来源去重与低权限同集合对照另在[ANN续验](../pdos-next-ann-authority-20261029/result.md)跟踪。8192完整矩阵已证明来源数量修复及同权限精确一致，未实际走HNSW；32768旧候选观察到部分自然HNSW，但连续预编译计划退化后中断，不能计完整通过。新的查询级修复已通过101项纯检查与独立窄审阅；最终32768矩阵完成12组控制、24次同SELECT计划匹配，nearest预编译为0且其他SQL仍自动prepare。8组最终实际HNSW的宏recall@5/@10为0.25/0.15，未观察到加速收益；因此C2权限、撤权、去重及真实计划同集合对照可收口，ANN质量/混合收益和默认启用不能记通过。最终92项输入哈希、原生T1清理及观察设置恢复均已核对，完整结果见上述ANN报告。


## 2026-10-30 模型关闭下的本地续建收口

原矩阵保留审计时状态；后续检查点不改写其历史。来源级权限物化与同一32768向量的64次同SELECT实测已完成，exact结果保持一致，owner/peer插桩耗时显著下降；四ANN配置仍无稳定质量/速度收益，关键词继续默认。[ANN实测](../pdos-next-ann-quality-performance-20261029/result.md)。query-only功能词过滤保留原题、预期和24份资料，通过22项纯检查及原28道HTTP题；正向macro recall@5/@10为97.92%/100%，来源加权为96.43%/100%，QUA-04仍第10，[独立复算](../pdos-next-keyword-query-grammar-20261029/result.md)。

CTX-09/12两档四项原生断言通过，但CTX-09自然目录和独立cursor不能拼成同绑定3→6/9，仍partial；CTX-12低档在实际48379>48000后停止，高档bound，未赋答案质量分。[原始失败和最终范围](../pdos-next-context-fixture-completion-20261029/result.md)。

正文新增核对的两处实际实现缺口也已补齐：溢出后显式另开空历史会话并保留服务器可信工作状态；可移除最近两个实际延续技能，固定原版本、启用状态复核和空选择不回填。恢复保留全部READ的metadata权限闭包，包含未引用来源，内部ACL不进入公共或模型投影。168项纯检查加1项类型检查、60项去重PG/API、40项前端/helper、88项BFF及758输入构建通过，153项原生输入结束SHA不变，无迁移，离线OpenAPI仅同步两个StartInput字段。[本轮结果](../pdos-next-context-recovery-skills-20261030/result.md)。原生60项由不变生产输入上的run2四项与run4五十六项组成，不宣称一次全量进程通过；三个新增夹具失败均保留。

上述两处本地实现已验证；CTX-09同绑定夹具仍partial。正式人工审阅、真实岗位/真人试点，以及真实模型/embedding同题质量、长会话正确率、缓存/成本/时延仍未执行。遵守当前不调用真实模型的要求，不能把模型关闭下的机制验证当作两份设计正式验收全部完成。


## CTX-09候选绑定澄清（2026-10-30）

独立读取冻结自然READ并按当前生产函数复算：9条为9325字符、估算2451tokens，低于4000上限；按体积分页也只产生一段。现有题的精确同句柄3→6/9为候选假设，不是上下文§6.3/X2或RAG切片B要求。`page_size=3`属于原生list/cursor，不应与result.read混为同一绑定。现标注needs_case_revision并交付[具体修订候选](../pdos-next-ctx09-binding-audit-20261030/ctx09-revision-draft.md)，原题、原partial和所有旧指标不改；[源码/证据核对与复算](../pdos-next-ctx09-binding-audit-20261030/result.md)。这不新增生产特性或人为加严DoD，正式人工审阅和真实模型等条件仍待满足。
