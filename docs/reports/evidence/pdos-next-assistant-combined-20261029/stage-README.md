# 小Pai 下一组合候选：冻结暂存交付

2026-10-29。只改本 `/tmp` 目录。未改 live、未运行 DB/Temporal、模型、embedding 或出站，未运行生产构建、git 或安装迁移。explicit-context-corrections 尚未叠入。

## 应用与精确身份

以根已应用的当前 live（C1 + 负例两文件）为唯一基线，原始 2614 份源码/配置输入保存在 `base-files/`、`live-base-manifest.json`。C1 清单 780/781 原 SHA 保留；唯一差异是根批准的新负例 test，它及新 helper 均与 negative-fixture-application.json 精确一致。11 个生命周期/检索缓存/PG helper 保护文件继续与 live 一致，其中 C10 有记录的条目也匹配。

交付仅 `deliverable-files/` 的 **83 文件（36 修改 + 47 新增）**，或相对工程根 `combined-next.patch`。**不要整目录覆盖**，尤其不要复制任何原 stage 的 server/web 旧验证副本。`combined-delivery-manifest.json` 记录每文件 current-live 基线 SHA、组合 SHA 与来源层。原负例两个测试/helper、lifecycle_access/catalog、assistant_sources、共享 readable/business/execution/relations/query 均没有被本轮覆盖。

完整最终源码/配置输入为 **2661**，包括 **714 web 输入**；`combined-inputs.json` 与 `combined-input-set-sha256.txt` 给出精确身份。生成 cache、node_modules、.next 类型输出不计为源码输入；.env 未复制或加载。TypeScript 只消费独立复制的原类型声明，未生成新构建。

`compose.py` 是可重放的严格应用器：在放好 `base-files/` 内容和 live-base-manifest.json 的新临时目录运行其副本，逐份核 manifest 自身/交付源 SHA、逐步核当前目标基线，仅执行 declared changed 文件。与 staged 相同者登记为 already-applied；depth integration 三个 changed=false 只核验并跳过。它遇到实际基线不一致会登记 conflict 并停止最终挂点，不猜测覆盖。

本轮 **112 个精确操作、0 个实际基线冲突**。已在独立 `replay-check/` 从原始基线完整重放，并在 `patch-check/` 对统一补丁 dry-run、实际应用；两条路径的 83 个最终 SHA 都与候选一致。逐步证据为 `application-plan.json`、`operation-counts.json`、`conflicts.json`（空数组）与 evidence。

## 精确叠加顺序

后端：depth 首层→depth integration（跳过 changed=false）→feedback 四文件→policy PG 补充→X3→observability admission/runtime 与 public 后端→personal summary foundation→integration→summary UI 后端。API 在 depth 版本后加入根批准的 `checked_result` 历史读取挂点。

前端：当前 live 已逐文件等于 verification **694**，只核其 12 交付文件（均相同）；加入 corrections 四新文件，再 integration 16 交付文件，累积完整输入逐项等于冻结 **702**；随后只叠不冲突的 observability 七 UI 文件及 summary 十五 UI 文件，得到 714。694→702 两个完整输入集合没有遗漏、漂移或额外文件。见 `web-layer-input-audit.json`。702 是完整输入数，绝不是复制 702 份文件的授权。

policy 的 `schema_retrieval_feedback_draft.py` 仅放 `migration-drafts/`，不放 server/migrations、不编号、不安装。root 复核实际 head 后另行包装正式迁移，实际反馈 PG 用例需先有已审阅的数据库守卫。

## 两个显式集成差量

1. `agent_kernel/api.py` 原 GET Run 的 Human RR 事务、visible_run 后，先 `checked_result(s,ctx,row)`，非摘要返回 None 才 fallback `stored_answer`。组合 API SHA 为 `2a7f4ed6a2f62adbe6d75bc4e2a7360be8d9ece9759962910a236db641d64c47`。没有改其余原路由/权限。
2. 原 automations/test_runtime.py 六参数共用的旧假 scope 只有 trigger，新增 depth Host 合法读取真实 RunScope.isolation 后该替身不完整。根批准仅给这处 SimpleNamespace 加 isolation="main"；生产守卫不放宽。精确前后 SHA 见 `compatibility-test-delta.json`，compose.py 也登记此重放步骤。

## 组合验证

- 后端首轮 572 通过、6 个上述旧替身 AttributeError；只修该测试 scope，再按根明确指示复跑六例，**6/6 通过、572 deselected**。最终为 **578 个去重通过用例的分段证据**，不是一次全量通过声明。所有首次运行成功用例的生产输入在随后完全未变，只有六例的测试替身变化。`segmented-test-evidence.json` 逐 node ID 指向原始日志；pure collect 578 个唯一项。
- 后端选择是 depth/X3/observability 冻结 runner、feedback 与 summary 冻结纯测选集的去重并集，另含 verification source guard 相容纯测。`pure-selection.json` 给文件来源；所有 *_pg/Temporal 草案均排除。runner 在 import 前删除所有 DATABASE_URL 与 PDOS_TEMPORAL 环境变量，不加载 .env。
- 前端 **229/229**，26 个去重测试文件。`frontend-selection.json` 与 `run_frontend.py` 可重放真实 TS/TSX/事件/transport substitute 纯测试，无浏览器或模型资格声明。
- 整份 web `tsc --noEmit --incremental false` 通过；42 文件 ESLint --max-warnings=0 通过；40 个交付 Python 文件及另一个相容 fixture Ruff 通过；变化 Python AST 通过。
- 初次 ESLint 使用 /tmp 绝对参数与 /private/tmp 的规范 cwd 不一致，42 文件均被工具忽略，不能算检查。改用项目相对参数后的 `evidence/eslint-relative.txt` 是真正零警告通过证据；未改生产代码处理它。
- 补丁、独立重放、C1/负例/C10保护、694/702/714 输入守恒均已核对。未执行构建、实际 PG/Temporal 或浏览器，因此不把本轮当产品整链通过。

## 后续独立补丁位

`explicit-context-corrections-slot.json` 明确该层 **未包含**。代理确认 work_state 基线 69f1e253…、source-scope 基线35ca2b3…、UI 来自702；API 将交基于 depth666ee894…的独立 patch，根应保留本候选 checked_result 挂点并按真实 delta 合并，不能用它整文件覆盖组合 API。其后需重新冻结受影响输入和运行对应检查。

`pg-draft-selection.json` 只列本组合携带的实际 PG/Temporal 草案，不在 pure 统计中。根统一复核当前隔离目标、正式反馈迁移、DB/Temporal 环境，再执行有关深度/反馈/摘要/过程展示整链。新 X3 长运行草案由对应代理另行交付，本轮也未叠。本人摘要 UI 中专门 Issue/CAPA 订阅、节假日/调休日历、外部投递仍是已登记缺口。

另有 root 新授权的 `context_runtime.cleanup.retained_latest_results` 提前 break 计数修复，由 result_continuation 独立交付；见 `context-runtime-delta-slot.json`。本候选仍为冻结 X3 的 b386747…，没有猜测叠入尚未交付的修改。root 需在后续按其 manifest 合并并补受影响检查。
