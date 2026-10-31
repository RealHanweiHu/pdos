# 小Pai 日常问答切片 A 与上下文 X1 实施检查点

日期：2026-10-28。范围为交接文档的 A1–A3、X1-1–X1-7，按已批准 P30/P32 与现有工作树实施。代码已落地；用户追加授权修复六项既有失败后，本轮同一候选集中回归 **79 项 PostgreSQL/API 全部通过、65 项披露与执行绑定纯测试全部通过**。前轮六项失败已消除，原始失败及开工前对照证据保留。真实模型仍按用户要求暂不调用，不声明整个上下文设计或正式阶段验收完成。

## 可用能力与验证边界

| 项目 | 实现 | 证据与剩余边界 |
| --- | --- | --- |
| A1 | 个人全局对话默认不预载业务技能；新建品类的专用入口通过 AppShell → PaiRail → PersonalXiaopai 请求当前启用的 category_framing 版本。读取技能失败不阻止发送。 | 默认预载纯测试、实际组件交互请求测试通过；品类/提案/项目默认分支保留。 |
| A2 | 固定系统提示增加日常问题直接回答、公司事实先查、未查到仅按范围说明的规则。 | 图测试通过；三条规则按既有行宽换行，保持语义。企业检索仍属切片 B。 |
| A3 | 服务器删除模型自写 assistant；无工具或只有 skill.load 时附加 general/not_run；完成的回答显示“未查公司资料”。 | 五项后端输入组合、短答/长答与未完成状态的前端测试通过。 |
| X1-1 | 连接配置支持可空、严格整数的 context_window_tokens（1024–10,000,000）；表单支持留空与读回，缺省按 32,000 估算。 | DTO、路由、合成安全存储读回、表单校验/渲染通过；实际 PG/T1 保存、读取、原请求恢复与权限拒绝已通过。路由、配置绑定、连接请求及受控命令的旧缺省摘要保持。 |
| X1-2 | 成功模型调用结果保存窗口/预留/焦点预算、六段体积、总量与 over_focus；不进入请求幂等键。 | 估算/分段纯测试通过；实际网关持久化、用量结算与原请求恢复通过（合成模型客户端）。这里只记录，不拦截或缩减。 |
| X1-3 | 历史状态分 current/updated/hidden；来源更新保留回答并标注，撤权隐藏正文与 sources；候选和未复核读取保留回答并加备注。 | 本地查询替身覆盖错误分类、隐藏优先级、T0 回执、候选与未复核读取；实际 RLS、来源撤权、内容更新与候选保留联验通过。 |
| X1-4 | 最近三轮回答上限 600 字加提示；较早轮次为 60 字目录；显式历史读取不分层，回答上限 8000 字。 | 30 轮合成长回答的默认历史估算 ≤4000 tokens，全文/上限与字段投影纯测试通过；30 轮实际 PG 会话及完整历史读取也通过。不是任意输入或全部工具上下文的预算保证。 |
| X1-5 | 在加锁事务内首次计算并保存历史及摘要，后续组装复用；模型前复核仅以新隐藏轮次/范围不可读作为历史中断条件，转为 partial；分页记录隐藏基线。 | 冻结、内容更新不停止、新撤权、旧分页撤权、事务开始即撤权及图 partial 测试通过；实际 PostgreSQL 的冻结、更新、撤权、注册执行图恢复及运行详情接口均通过。当前复用现有本地历史复核器，仍会读取并比较内容；独立的批量 ACL 专用通道不在本交接实现中。 |
| X1-6 | 直接父运行最近两个、当前仍启用的主循环技能与本轮请求合并去重，按当前版本加载；自动化与隔离运行入口不变。 | 纯测试覆盖最近顺序、去重、数量、当前启用和隔离过滤；真实事件与预载的最近顺序、两项上限、当前停用跳过、显式请求合并，以及非对话/隔离入口回归通过。 |
| X1-7 | Anthropic system、首条上下文与末条消息设置最多三个缓存断点；OpenAI 兼容请求不变。 | 两条协议的合成请求、单条与多条消息、不修改输入的测试通过；真实命中率、时延及费用未测。 |

## 六项既有失败修复（用户追加授权，本轮最终候选）

- 运行详情接口的受限查询显式加载 `trigger` 及服务运行回执核验所需的 writer、意图摘要、固定目标和预算字段，保留 `raiseload=True`，仍不读取 Run 的 result/versions 或工具原始载荷。这样既修复四个普通上下文用例，也避免服务运行分支继续缺字段；新增实库用例验证固定目标不进入响应、他人读取仍为 403。
- 渐进加载用例改为核对每次调用的精确披露集合、旧定义保持、集合严格扩展，以及提案写工具只在加载起草技能后出现；保留固定系统提示与恢复零重复调用断言。
- 快照测试的 `model_for` 通过服务器同一披露合同，按账本中实际加载的技能和隔离范围计算摘要；不再使用完整工具表伪造主循环摘要。生产 T0 来源、技能与披露摘要守卫未改动。

直接改动为 `agent_kernel/api.py` 和三个测试文件（context_projection_pg、snapshot_proof_transactions、process_view），没有迁移、依赖、合同或前端修改。见 [本轮直接差异](six-fixes-direct.diff)；其中运行详情新增服务用例位于 process_view 测试，完整候选指纹见 [source-manifest-six-fixes.json](source-manifest-six-fixes.json)。

最终验证：

- [六项定向验证与新增服务用例](six-fixes-targeted.txt)：7 通过，该组随后纳入集中组，不重复累计。
- [集中 PostgreSQL/API 回归](six-fixes-database-final.txt)：**79 通过，0 失败**；包括原 62 项、完整运行详情/分页/撤权/回执测试、快照 T0/T1 登记、跨请求读取与来源证明。43 项运行时/依赖警告保留，未当作失败或扩大本轮修复。
- [披露和执行绑定纯测试](six-fixes-pure.txt)：**65 通过，0 失败**。
- [本轮 Ruff](six-fixes-ruff.txt) 与四个目标文件的 `git diff --check` 通过。
- 仍使用 [已核对的 53502/pdos_test](database-target-continued.json)，每次运行从原状态文件核对容器标记并显式注入四角色连接串，无 `.env` 回退。未调用真实模型、未改资格/权限/业务守卫、未建库或迁移、未提交或推送。

## 前轮验证记录（保留历史，不覆盖本轮最终结果）

- 开工基线：[baseline-pure.txt](baseline-pure.txt)：110 通过、2 既有失败、10 数据库连接变量缺失错误。四个连接变量均未设置，未读取 `.env`、未连接数据库、未建库。基线状态见 [baseline-status.txt](baseline-status.txt)。
- 集中后端：[backend-final.txt](backend-final.txt)：269 通过、2 既有失败、10 因明确缺少隔离数据库而跳过；没有新增失败。覆盖交接总检查及模型配置纯测试。
- 最后受影响子集：[final-targeted.txt](final-targeted.txt)：47 通过，覆盖 8000 字上限、历史冻结/撤权/字段投影和连接摘要兼容。该组与集中组重叠，不累计通过数。
- 原数据库收集：[database-collection.txt](database-collection.txt) 为 45 项；续接实际补齐这 45 项及网关 7 项、入口投影 3 项，并补跑 A1 直接涉及的研究事务 7 项，合计 **62 项不同 PostgreSQL/API 用例：56 通过、6 项既有失败**。先跑主组 [database-first.txt](database-first.txt) 得 49 通过/6 失败，其中新增长会话测试在终态后改写结果，被不可变守卫正确拒绝。仅修正测试夹具为结束时一次写入长回答，[database-long-history-fixed.txt](database-long-history-fixed.txt) 单项通过；A1 关联组 [database-m3-preload.txt](database-m3-preload.txt) 为 6 通过/1 既有失败。单项修复与诊断重跑均不重复累计通过数。
- 测试库来自已保存的 `.local/runtime.json`，不是 `.env`：复核 [database-target-continued.json](database-target-continued.json) 中 Docker 容器 ID/标记、四角色同端点、environment_guard 与 `s0_0824` 后，按已有工具显式注入四个连接串，复用 `53502/pdos_test`。没有建库、迁移、改权限、改连接串或触碰预览库。认证角色按原夹具仅核对同端点和实际库名，不为读取 environment_guard 而扩大权限。
- 前端：[frontend-final.txt](frontend-final.txt)：149 通过，包含配置表单、小Pai工具组件、个人首轮请求和回答标注。
- [typecheck-final.txt](typecheck-final.txt)、[lint.txt](lint.txt)、[ruff.txt](ruff.txt)：通过。后端 Ruff 包含本次源文件与三个新增纯测试文件。
- 合同导出：[export.txt](export.txt)：原脚本在临时副本离线运行，脚本自身禁止数据库连接；仅取回 openapi.json 和 payloads.schema.json，分别新增 13、14 行，均为 context_window_tokens。未写回 operations.json/acceptance.json/events.json。合同验证 [contracts.txt](contracts.txt) 保留既有事件数量失败。
- 本次目标文件的 `git diff --check` 通过。全工作树检查另报两处既有空白（knowledge-library.tsx、projects/external-waits.tsx），未修改。

纯检查的两项既有失败，均已在开工基线重现并保留：

1. `tests/agent_kernel/test_context_projection.py::test_every_registered_skill_has_a_resolved_closed_context_contract_and_digest`：目录已有 18 个技能，旧断言为 17。
2. `tests/command_catalog/test_catalog.py::test_source_catalog_validator_runs_clean`：冻结事件目录已为 90 项，校验器仍预期 86。

修复前发现的六项既有数据库失败，均在临时副本中用开工快照复现了相同原因；用户随后明确授权修复，现已全部通过（见上方最终候选）：

| 用例 | 既有原因 | 改动前对照 |
| --- | --- | --- |
| `test_context_uses_loaded_methods_and_snapshot_is_idempotent_private_and_checked` | 运行详情读取的 `AgentRun.trigger` 未随受限列集加载，触发 raiseload；上下文快照前段断言已通过 | [context 对照](database-prechange-context.txt) |
| `test_unexpected_fields_fail_in_dev_test_and_are_explained_without_values_in_production[development/test/production]`（3 项） | 同一运行详情接口的 trigger 字段问题；字段拒绝/省略断言已通过 | 同上 |
| `test_registered_graph_progressively_adds_context_and_replay_never_calls_provider` | 旧断言要求加载技能前后工具列表完全相同，与已有渐进披露行为冲突 | 同上 |
| `test_actual_registered_page_returns_original_read_reference_on_restore` | 快照登记夹具的工具披露摘要与当前披露集合不一致，现有 T0 来源守卫按 VERSION_CONFLICT 拒绝 | [snapshot 对照](database-prechange-snapshot.txt) |

对照方法：复制运行源码到临时目录，将本次涉及且可追溯的 10 个已跟踪运行源码文件恢复为 Git HEAD + 开工时保存的工作树 diff；其他源码与失败用例保持不变，重新导入该副本，在同一已核对隔离库执行。这六项分别在对照中再次以相同原因失败，当前工作树和权限守卫未改动。文件指纹见 [prechange-diagnostic-source.json](prechange-diagnostic-source.json)。当时按交接的跨范围停止条件保留；用户随后明确要求修复，已按上方范围处理，没有修改来源或权限守卫。

运行方式：现成 `.venv/bin/python -m pytest`/`-m ruff`；原 `uv run` 因沙箱不可访问用户缓存而未启动，改用同一已安装虚拟环境，无新增依赖。上轮无显式环境变量时通过 `/tmp/pdos_x1_no_db.py` 仅跳过依赖 `engines` 夹具的用例；续接使用已保存、重新核对的隔离环境后没有使用跳过插件。只修正了本次新增长会话用例的写入时机，未改共享夹具或数据库安全护栏。

## 在途改动与实施修正

开工已有未提交改动：bootstrap.py、conversation.py、graph.py、gateway.py、providers/types.py、providers/agent_client.py、model_configuration/host.py、schemas/model_configuration/dto.py，以及 AppShell、category-workspace、personal-xiaopai、PaiRail、PaiResponse、其样式与模型设置组件等；完整列表见开工状态。现有范围绑定、模型预算、协议适配、连续工作区与其他业务改动均保留；未回退、提交或推送。相邻实现按实际代码衔接，未据交接中的“以本文件为准”覆盖 v1.1/P30/P32 或仓库权限边界。

交接外增加两处必要的模型配置配套修改（同属 X1-1）：connections.py 与 commands.py 在未设置窗口时排除新增缺省字段，避免旧保存/确认请求摘要失效；服务器模型列表也带回窗口。对应纯测试覆盖旧摘要与配置字段读回。

另外，历史守卫的错误转换包住整个事务入口，确保事务尚未 yield 就发生的范围撤权也转换为登记的撤权原因。未放宽权限。导出在临时副本运行，避免原脚本直接触碰冻结操作/验收文件。

## 未完成与恢复条件

- 数据库测试库阻塞及六项既有 PG 失败均已解除，本轮选定的 79 项集中 PG/API 与 65 项纯测试全绿。另两项前轮目录数量失败（技能 18≠17、事件 90≠86）不属于用户本次指定的六项，保持原范围与证据，不宣称全仓库全部门禁通过。
- 真实缓存命中/时延/费用：需要用户对应的真实模型调用授权；本轮没有真实模型或服务商调用。
- 系统提示和技能上下文合同变化后，旧运行恢复可能被现有版本/摘要守卫拒绝（VERSION_CONFLICT）；应新建运行，不绕过守卫或继承旧资格。
- 企业检索、个人偏好、工作状态、全局预算缩减、单结果续读和长运行清理仍属于后续切片，不能以本检查点宣称完整防溢出、真实资格、生产启用或正式阶段验收通过。


## 六项修复前的续接候选指纹（历史）

应用源码与前端均未再修改，沿用上轮通过的 269 项后端纯检查、149 项前端、类型/lint/Ruff 证据；只修改本次长会话测试夹具的首次终态写入时机，相关实库单项与 [ruff-continued.txt](ruff-continued.txt) 通过。当前指纹为 [source-manifest-continued.json](source-manifest-continued.json)，原 [source-manifest.json](source-manifest.json) 保留，不覆盖开工和首轮结果。已有备份与数据库记录保留，未清库、未提交/推送、未调用真实模型。

本轮最终候选采用 [source-manifest-six-fixes.json](source-manifest-six-fixes.json)；旧指纹仅对应各自历史验证，保留用于追溯。
