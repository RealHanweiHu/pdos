# X2 受控续读与模型上下文准入

本分支完成内核 READ 结果上限、`result.read`、必需上下文准入及对应恢复接线。生产代码候选摘要见 [SHA-256](candidate-sha256.json)；数据库、前端及公共候选由主会话集中验证。本分支没有迁移、真实模型/embedding 调用、提交、推送或外发。

## 可用能力

- `ToolSpec.max_result_tokens` 默认 4000。完整读取仍保存于原 `AgentToolCall.result`，模型消息改为有明确 `truncated`、总量、页数和受控句柄的 JSON 片段；`tool_results.value` 保留完整原结果供领域核对。
- `result.read(handle,page)` 必须属于当前租户、运行及同一隔离范围；句柄绑定已完成 READ 账本和结果摘要，不能引用模型、写操作或另一个续读页。每页经原模型调用来源重核，再重入原注册 read/restore；来源改变、撤回、撤权或范围变化均拒绝，不直接分页旧 JSON。各子图由原本地读取器续接，主图不能借句柄读取子图原文。
- 页正文精确拼回原 JSON，转义字符与中文计量一起预算。子图在片段未读齐时不能形成已核对证据；模型修复提示列明句柄和缺页。
- 续读使用现有持久 READ 账本；同 intent 经 advisory lock 串行。只对零费用、零预留、同隔离范围的 `ordinary/v1 result.read` 开放 started 恢复，不放宽写入、模型未知结果或其他读取。
- 历史中的续读页必须证明来自同一批被复核的主图原 READ，重核原来源一次；不会因新增续读工具把旧回答变成“未复核”，也不重发网络/模型任务。
- 模型前计入系统、工具/输出 schema、动态信封、历史、技能、工具参数与 continuation。保留输出和下一次 4k 结果预算，首轮预留 15% 估算余量；后续使用同路线上一实际 input 校准并保留保守下限。每个原请求的校准输入持久冻结，重放不会改变缩减或幂等键。
- 超预算依次缩减可恢复的旧历史回答、旧普通工具结果与提案正文目录；原用户问题、工作状态、引用、回执、证据、技能加载和错误不静默删除。缩减动作附恢复入口并记入调用预算记录，重新签署上下文快照，保留此前字段删减事实。仍放不下时零模型预留/调用，返回 `partial/context_incomplete` 及准确字段名。
- 固定系统/工具/必需技能本身超窗时明确提示核对模型窗口或选择足够窗口的模型；不会误导用户清理会话。本人的偏好作为动态状态按 Run 冻结，技能加载不重读配置；导航候选每次发送前按当前权限复核。

## 验证

- 校准后同候选纯回归 **278 项全部通过，69.41 秒**，见 [原始输出](pure-final.txt)。覆盖真实 host/claim/settle 的长结果、逐页恢复、重放、撤权/改变、跨运行/租户/隔离拒绝、历史派生复核、片段可见性、必需内容不截断与零模型准入。
- PostgreSQL 专属 4 项已由主会话完成：真实普通角色长原件读取与续读、中断后双线程同 intent 单行恢复、撤回后重放拒绝；模型前零账本/零预留；缩减快照保留原 omitted 字段与 Run 偏好冻结；真实 `ExtractGraph` 子 Host 续齐片段后形成核对行。记录为 [集中 3 过 / 1 个新测试返回值解包错误](../pdos-next-enterprise-knowledge-authority-20261029/result-continuation-final-focused-pg.txt)，按真实 `(rows,rejected)` 合同修正新测试后 [单项 1/1 通过](../pdos-next-enterprise-knowledge-authority-20261029/result-continuation-child-contract-fixed.txt)。生产代码未变化；不把这两次执行表述为一次 4 项全绿。
- 已读 `schema_s0_0830.REPAIRED_GUARD`：`ordinary/v1` 不限制工具名白名单，仍核对实际模型 response/参数摘要/运行/主体/隔离；无需新增迁移。主会话此前已实际跑过本文件前两项及关联结构化 8 项，共 10 项通过，后续恢复/校准修改需以最终候选重新验证。
- 目标 Ruff 与差异检查由本分支执行；公共构建与数据库回归归主会话。

## 必须保留的边界

没有配置窗口的生产路线继续按 32k 保守值办理。真实固定段测量见 [测量记录](fixed-context-measurements.json)：未预载的 61 个工具本体约 26916、输出 schema 462、系统 2850 tokens，总输入估算 30246，含余量 34783，高于 F=25952；仅离线合成 enterprise fixture 显式声明 200k 能力，未提高生产默认值或绕过预算。

实际 token 计数、Anthropic 接近上限时的 count_tokens、真实模型/缓存命中和语义注入评测未执行。已加载且不能证明不需要的技能正文继续保留，必要时如实 partial；不以猜测删除方法内容。上述实现不等于正式阶段验收、真实模型资格或整个 X3/企业 RAG 设计完成。

## 长结构记录接续

主会话追加检查发现，`assistant.extract` 在已完整加载并复核内部结构化来源之后，仍按旧的 6000 字符模型载荷限制返回 `structured_row_too_large`。该检查不限制查询、费用或合法领域字段，却会拒绝两个各不超过 4000 字符的合法 Wait 字段组合，与上述受控续读冲突。本次只移除该拒绝与无用 import；保留领域字段约束、来源当前权限、固定版本、外来原件隔离以及此前 `region` 的完整注册记录范围。

新增纯验证 3 项，连同受影响续读/预算用例共 **28/28 通过（9.87 秒）**，见 [输出](structured-result-pure.txt)。这与前序 278 项有重叠，不累计为独立用例数。

新增实际 PostgreSQL 用例为 `tests/enterprise_search/test_structured_passage_pg.py::test_long_registered_wait_uses_real_kernel_result_continuation_and_final_verification`：通过真实 Wait 领域命令写入两个各 4000 字符、含独立末尾标记的字段；经 Outbox 和真实主 Kernel 检索/提取后，离线 provider 只从收到的 `json_fragment.preview` 按页重建 JSON，经 `result.read` 续齐后才返回引用。断言完整账本与实际收到的完整结果摘要一致、最终来源核对成功、不调用隔离原件读取、当前来源复验不增加 provider 调用。该用例交主会话集中执行，当前等待结果；未自行启动数据库检查。
