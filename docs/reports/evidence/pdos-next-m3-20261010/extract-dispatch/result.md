# M3 隔离抽取作业派发与恢复

从 `365f1e6` 续建，head 保持 `s0_0757`，无迁移。`evidence.extract` 现在真实派发：主循环调用经 `verify_read_source` 绑定实际模型回复后，服务器按 Run 绑定的挂载原件集合解析目标（`None`=全部挂载，显式列表须为子集），逐原件在注册执行图内开 `extract` 隔离子任务；子任务只有 `evidence.artifact.read`，模型按行合同交行，宿主账本逐字核对引文必须命中实际读过的行，覆盖由代码按已结算读取计算。行结构 `row_schema` 必须同时 (a) 登记在服务器 `RowSchemaRegistry`、(b) 由本 Run 实际加载且当前启用的技能在 frontmatter `row_schemas` 声明（rfq_extraction 0.3.0-draft 声明 `rfq_requirement/1`）；目录启动时校验声明可解析。未解析原件（uploaded/failed/needs_ocr）不派发模型，覆盖明确 `source_not_parsed`；超 24,000 行原件按 `artifact_too_large` 拒绝。子任务崩溃后按检查点恢复：重放把检查点内已结算页与当前固定原件逐字节比对后重建账本，技能内容变化按 `VERSION_CONFLICT` 拒绝。结算结果经 `read_restores` 精确重放：重放对当前 seal 身份（版本/内容摘要/解析状态/行数/定位映射摘要）、覆盖与逐字引文重新核对，任何漂移拒绝而不是重跑模型；运行取消后重放拒绝。真实模型调用 0 次，未授予资格。

- [最终 9 项纯检查](pure-1.xml)：引文核对行/未读拒绝/编造拒绝/结构拒绝、子任务工具白名单、预算上限与耗尽、检查点崩溃恢复与技能钉住、页重放抗漂移、focus 上下文。
- [最终 5 项实库检查](pg-1.xml)：真实上传/扫描/解析/提案/Run → 合成主循环绑定调用 → 隔离子任务合成模型读页交行 → 覆盖/回执落库核对；同 intent 重放逐字节一致且零新增模型调用；双原件扇出与显式子集；未装载技能、未声明行结构、未绑定原件拒绝；跳过读取的行按 `source_location_not_read` 拒绝；取消后重放拒绝。仅有合成管理员/协议/技能启用夹具，未授真实资格。
- [受影响 215 项定向回归](affected-1.xml)（extract 页/账本/契约、技能合同、预加载、原件绑定、读取/快照证明、计算 Claim、Temporal 域）与[全量 1526 项 agent_kernel + 证据套件](full-regression-1.txt)通过；[规范检查](python-lint-1.txt)通过。首轮全量有 7 项 Temporal 用例因缺 `M2_TEST_CHECKPOINT_URL` 环境变量失败，补齐后通过，与本段改动无关。
- [源码清单](source-manifest.json)固定本段 1785 份源码。仅使用核对标记的 `127.0.0.1:64245/pdos_test`（marker `f9048729`），无迁移、无前端/构建产物变化，未重复完整构建。

本轮修复的开发期缺陷（均未出库）：纯图夹具路径返回缺 `execution_ref` 导致恢复重放跳过页；重放与同进程已登记页按 call_id 幂等去重；`ExtractInput` 须带服务器绑定 `proposal_id`；合成夹具预算容纳完整冻结前缀。失败 XML 未保留（首轮即修，最终统一为上述文件）。

本段完成 `evidence.extract` 作业派发、技能声明绑定与恢复重放。抽取 Claim 消费证明（`evidence.claim.record` 消费抽取行的绑定链）、失败原件挂载后的解析库存（parse_manifest 落库与未知范围）、标准品匹配仍未启用，不能把当前行当作这些能力通过。继续该接线及平台、AT/演示/性能；无 push、生产、真实外发，M3/S1 未完成。
