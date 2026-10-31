# B · 当前项目权威上下文（冻结候选）

本包只落实已批准 RAG v0.4 §4/切片 B 的“这个项目为什么还没进入 DVT”。原生个人项目 HTTP 已有具名状态、计划、阶段与门禁，但原主图 project context 只有 id/name/revision/visibility；不新增业务来源类型、工具、表、权限或第二事实库。

## 精确应用

以 `apply-manifest.json` 为唯一交付清单：10 个 full staged 文件；不是整个 stage。原基线均位于 `base/`，完整源补丁为 `project-current-context.patch`。已在独立 `replay-check/` 按精确原 SHA dry-run/apply，并逐个核对输出 SHA；证据见 `evidence/patch-replay.json`。

1. 逐个核 manifest.files 的 old_sha256（新文件必须不存在），再只应用这 10 项。parent 已经持有 live；本 agent 没有写 live。
2. `agent_kernel/api.py` 不属于 full-file 应用清单。仅应用 `api-project-history-hook.patch` 的三行调用：现 personal_summary.checked_result / stored_answer 之后、AgentSession 读取之前。manifest.public_hooks 列精确 base/final SHA；完整 API 副本只用于本地验证。若公共 action API 已后叠，由 root 按该位置局部合并，不能覆盖后层 StartInput/action 代码。
3. `AnswerSources` 仅有 import、本地 Answer.project_basis 可选类型和 JSX 挂载三个小 hunk。D 若先叠 sourceObjectHref/relation 映射，用 `answer-sources-native-basis.patch` 局部合并，保留 D 映射。本层没有改公共 SourceType/引用类型、Xiaopai 或 PaiResponse。
4. summary_gate 的 work_followup prepare_candidate/context_projection/API 小 hook 由 root 在本层后叠；本包不含其 action。
5. 不含任何迁移、编号或安装步骤。

## 实际数据与边界

`project_current_context._collect` 用当前本人普通 RLS 与现有 native `project_work_summaries.latest`、PlanRevision、ProjectOpenItem、project_governance.view / 固定 definition / 当前 commitment 读模型，白名单输出：具名更新人的真实身份与回执、当前固定计划日期、实际阶段/各门禁状态和原因、专业规则条目、当前事项的真实 owner/due、原生承诺与履行状态。最多 20 条/组、文本 1200 字符，截断与不可用明确记 missing/partial；缺失日期/状态保留空或 unknown。不从记录人推断负责人，不产生健康度，也不复制完整 release package、签核 authority 或原件正文。

create_run 的现有本人 UOW 先核实际 project，再固定 native digest、as_of、只含身份/版本/hash 的 Artifact footprint 与 native 对象引用；合并实际 source read set、private_context 与 P26 分类。原请求 fingerprint/幂等和旧 Run 无绑定行为保留。读取由真实 Run 导出 requester，沿现有 `human_snapshot`；没有任意 owner 读取端口，也没有扩大 writer/service 业务读取权限。

Bootstrap 在动态 context 末尾附 `project.current_facts`，静态 typed context schema 对该字段封闭。现有每次模型发送的 context guard 与最终结果 verify_result 都重核原始固定依据；状态/依据变化不会以新事实替换旧运行，返回 SOURCE_STALE。现有 gateway 记录真实服务商和数据类别，本包不改政策或资格。

结果 `assistant.project_basis` 是服务器生成的 native 元数据（版本、原 as_of、完整性、固定对象 ID/revision/receipt、当前项目深链）。没有造 RAG lookup/citation/matched_count。单独 native 回答移除旧 `lookup=not_run`，所以 PaiResponse 不再误显示“未查公司资料”；前端显示“已读项目当前记录”。混合检索回答保留原真实 RAG lookup/citations。

历史 API hook 遵守 P32：普通本人当前 RLS 验原 footprint 与固定 native 对象；记录更新时保留原回答/原 as_of 并标 updated，原件或固定对象权限失效则拒绝返回。它不借当前新来源给旧答案补证，不追加权限、外发或批准流程。旧 Run 没有本包绑定及 project_basis 时原样通过。

## 已跑的本地验证

- 首轮四文件目标纯测试 89 项通过：`evidence/pure-targeted.txt`。
- 最终新 projection/历史/原生 release 身份测试及 context projection 22 项通过：`evidence/pure-final-affected.txt`。与未受影响的 scope/object-read 68 项分段去重为 90 个 nodeid，最终收集见 `evidence/pure-collection.txt`；不把 89+22 相加。
- 新前端 4/4：`evidence/frontend.txt`；真实 AnswerSources native 分支、原时间/版本/回执、P32 notice、链接白名单与普通 not_run 行为。
- TypeScript `tsc --noEmit --incremental false`、目标 ESLint、7 个目标 Python 的 Ruff/语法通过，日志在 evidence；无 build。
- 10 项 core + 独立 API hook 精确基线 patch dry-run/apply/输出 SHA 全通过。

## Root 待执行（真实 PG / Temporal 草案，尚未运行）

`evidence/pg-collect.txt` 仅证明以下 3 项可收集，不是 PG/Temporal 通过：

1. `tests/agent_kernel/test_project_current_context_pg.py::test_actual_current_project_context_has_named_status_native_unknown_gate_and_no_lookup_claim`
2. `tests/agent_kernel/test_project_current_context_pg.py::test_actual_native_update_requires_fresh_current_context_but_history_is_preserved`
3. `tests/agent_kernel/test_project_current_context_temporal_pg.py::test_actual_project_native_context_runs_main_graph_and_retains_history_after_update`

复用 work_management 原生 Human fixture，以真实具名 STATUS/阶段 adopt 命令登记合成事实。前两项经真实 BoundHost/context schema、classification/readset、最终 attach、更新后的 current guard 和普通 RLS 历史读取/撤权验证。第三项用真实 HTTP→Outbox/Temporal→唯一注册主 LangGraph，注入单次零出站合成 provider（200k 合成 window，无 T0 资格）读取真实 current_facts，核结果依据、原幂等、P26 实际 receipt、历史保留与撤权。它不依赖 assistant.search，不伪造检索，也不启动第二模型。显式临时 TEST_DATABASE_URL 与已核 checkpoint/local Temporal 的检查由 root runner 负责；本 agent 未访问 DB、Temporal、真实模型/embedding、出站、git 或 live。

实际“为什么未进 DVT”的模型语义质量仍须用户维护题集评价；纯测试不宣称证明自然语言忠实度。本包只补实际模型可达的权威事实与来源边界。
