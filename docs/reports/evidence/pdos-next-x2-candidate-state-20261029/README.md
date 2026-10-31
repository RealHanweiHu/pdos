# X2 候选当前状态 · 冻结 stage

只关闭已批准的一个独立缺口：跨轮工作状态原先只携带候选 event_id/run_id，且 finish 未登记研究快照与复验准备。现在四种候选均由实际当前原生只读 view 投影为类别、状态和真实采用回执；本次携带 UI 展示这组元数据。没有模型调用、候选采用动作、payload 复制、第二事实库、新工具或迁移。

交付顺序为 `apply-manifest.json`（10 文件 core）→`fixture-delta-manifest.json`（1 个既有纯测试夹具独立差量）。精确重放说明见 `replay-plan.json`。两个 patch 已在只含精确 base 的 scratch 依序 apply，11 个输出 SHA 全部相符。整个 pdos-next 验证副本不可覆盖 live。

## 六个来源文件及挂点

1. `agent_kernel/work_state.py`：finish 登记 snapshot/verification 事件的固定 ID；当前只读 `_project` 调 metadata helper；`check_frozen` 只阻止真实来源运行失去可见性，不重写运行内冻结版本。原约束逐字证明、版本化 CAS、本人删除 tombstone 与覆盖范围逻辑保留。
2. 新 `agent_kernel/work_state_candidates.py`：服务器从已核实际消费 Run 导出本人普通 RLS READ 快照；只在同 tenant/requester/session 中查真实事件与 Run。Human 使用当前会话，Agent 先核实际 writer/run/cancel_epoch，再复用现有 bounded human_snapshot。不是通用 owner 接口。
3. `agent_kernel/domain_candidates.py`：只抽出原页内 native 投影为 project_rows；domain/snapshot/verification 使用原 PreparedCandidate、RequestKey、Receipt、pending proof 和 verification view。公共候选页保持原形状和校验。
4. `agent_kernel/category_candidate.py`：新增只读 metadata 入口复用原 validate。执行默认仍 FOR UPDATE；仅只读入口省锁，完整模型来源/快照/skill/当前身份核对保留。
5. `agent_kernel/category_adoption.py`：原 resolve 保持原 Human 事务与 category_scope(lock=True)；只读 metadata 在当前投影会话复用完整原生 adopted validator，省写锁、不另开 owner 写事务。只有实际 AgentInput、Category、Receipt、adopted event、本人当前 Grant 相互匹配才能 adopted。
6. `web/src/components/pai/work-state-carry.tsx`：四种类别及 pending/adopted/cancelled/unavailable 中文状态、真实采用回执；沿用只读刷新，没有确认/写入按钮或原生 payload 展示。

另 4 个 core 测试文件是新 metadata pure、PG、Temporal 模块与既有前端 test 修改。公共 API/Host/Activity/graph/worker/schema 没有改动；public work-state `candidates` 从裸 IDs 扩为 `{event_id,run_id,kind,operation,state,receipt_id}`。只读状态是本次读取时的 native 当前状态；已经冻结进某运行的内容不随 UI 刷新改写，下一轮重新投影。metadata 不授予执行权，实际候选页/命令仍按原生守卫核对。

未知/失效证明只显示 unavailable（不显示 operation/receipt）；不可读原事件/运行不回显其 ID，附原隐藏提示。旧工作状态中的 state/receipt/payload 等任意字段不参与证明。没有命令、标题、引文、专业正文或 source_proof 进入 metadata。

## 独立 MemorySession 差量

原 baseline 的 Activity 测试先在 requested_skills.preload 读取第一事件时断言失败；用原 category_adoption 源码复现，见 `evidence/base-activity-single.txt`。补支持之后，同一原负例又走到当前已有失败收尾：fixture 缺 result/versions/read_sources/no_autoflush 和 WorkState 查询支持。

独立测试差量只补这个显式内存数据集：seed 必须匹配当前 tenant、指定 run/sequence；max 按真实 run 过滤；既有失败收尾的 WorkState、Run goal、真实 Agent receipt、候选事件查询依实际集合返回；未知查询继续 assert。原生产 Activity 字节未改。原 proof 类型、终态不重开、不重复执行、FORBIDDEN_SCOPE 断言完整保留，并增加实际失败工作状态 root_goal、候选引用、无伪 Agent 回执断言。新增 seed 测试验证空、存在、错 run/sequence。没有 blanket scalar=None、跳测或削弱断言。

## 已做验证

- 162 唯一定向 pure，按影响分段：95 个未变 candidate/constraint 测试在 backend-targeted 通过；53 个最终 MemorySession/adoption 测试在 native-adoption-metadata-final2 通过；14 个最终 metadata 测试在 metadata-final 通过。final2 中仅 3 个新增测试误把已收敛 code 与 reason 混用而失败，改成断言 FORBIDDEN_SCOPE+CONVERSATION_HISTORY_REVOKED 后这 14 项全通过。诊断日志保留，不把失败日志算全组成功。
- 前端 8/8，包含四种真实状态、刷新 pending→adopted 不产生写入、撤权清除旧回执及原删除/丢响应/CAS 行为。
- tsc --noEmit --incremental false、目标 ESLint 通过；9 个改动 Python 文件 Ruff 与 AST 通过。
- 4 个真实 PG/Temporal 草案仅 collect，未运行 DB/Temporal。无真实 provider、网络、embedding、出站或构建。

## root 待执行的 4 项

完整 nodeid 见 `pg-temporal-nodeids.json`，用已核隔离库/原安全 runner，不回退 .env。

- domain：真实 conversation ledger 准备平台草稿→finish→只读 pending→原生 Human T1→真实 adopted receipt；幂等重放；已有子 Run 冻结不变、下一轮刷新；当前 Grant 撤销隐藏。
- snapshot：原 native read proof/候选→finish→真实 Human 注册→工作卷丢失仍由实际回执显示 adopted；不复制 markdown、不增 WorkState 版本。
- category：原 personal category fixture→finish→Human 真实新品类回执→当前新类别 Grant 撤销后 unavailable；个人 Agent 无新 Grant，原 Run scope 仍 personal。
- Temporal verification：原 registered Xiaopai graph 以合成 provider 完成父回答/复验准备候选；只读状态 pending→原生 Human 确认（提交后丢响应、幂等恢复）→真实 adopted receipt；无第二模型调用，无准备 payload/proof 复制。

实际普通角色 PG/Temporal、浏览器和最后构建由 root 集中验证。本层不宣称真实模型质量验收、全部 X2 焦点对象扩展或整个设计完成。
