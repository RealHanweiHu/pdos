# G0 规格处置 P11 与 AT-52

2026-10-09，按用户批准的确认稿 §8 P11 与 M3 合同 §3.4/AT-52 落实审查第 7 项；该项已关闭，M3/S1 未判完成。

`views.required_dispositions` 统一判定固定副本中待答问题与须处置的规格。规格只要 item_status 为 unknown/expert_pending，或 availability 为 unknown/conflicted（含 ai_draft），就要求逐条 task/risk、owner、due_date；availability=not_applicable 豁免，仍须由既有 schema 保证理由。G0 approved 校验和预览的 required_dispositions 继续共用同一函数、读取提交固定副本；提交、退回与拒绝不新增此门槛。未改 schema、前端或 AI 资格规则。

[新增 AT-52 回归](at52.log)的四个实库案例通过：

- 真实合成 AI 候选的 availability=unknown、item_status=ai_draft 规格可正常提交；缺少处置时，批准预览与实际批准均被拒，返回 VALIDATION_FAILED / unknown_without_disposition。
- availability=conflicted 的 ai_draft 同样被拒；两种情况补齐处置后可批准，生成风险待办并保留 owner 与 due_date。退回预览不要求处置。
- not_applicable 的 ai_draft 及 unknown 状态规格均无需处置，理由保留；批准不生成该规格的待办。
- 成熟度的处置列表、固定副本和批准预览的 required_dispositions 核对一致。

[最终冻结 M3 组装回归](frozen-m3.log)共 50 项通过，新 4 项包含在其中，不重复计数；[规范](scoped-lint.log)、[编译](compile.log)通过。计数与范围见 [checks.json](checks.json)，[最终源码指纹](final-source-manifest.json)的冻结快照无漂移，P11 三个实现/测试文件与当前工作区一致。[实库 schema](owned-schema.json)12 张 M3 表及 16 个函数一致，4 个原子守卫、3 个封存守卫保留；[普通属主清单](definer-ownership.json)中的 52 个已安装 definer 均为 NOSUPERUSER/NOBYPASSRLS owner，AI 角色业务表直接写权限为零。

[首轮 50 项](final-m3.log)通过后，共享 api.py 再次变化，故该轮清单保留为 [冻结前历史](pre-freeze-source-manifest.json)。最终检查在独立源码快照中运行，保留当前并行工作区；最终清单分别记录 snapshot_drift 和 working_tree_drift_after_snapshot，不把后来变化的公共源码算作已通过。冻结回归耗时 155.94 秒，未作为性能达标证据；结束后隔离库没有阻塞等待。没有扩大到共享 B8 的完整回归。

复用此前已确认的自有独立 `pdos_test`，保留标记 `bfcfb45f-4eaa-4a65-a038-c1da6b98f8af` 与 `s0_0719` 基线，恢复后端口为 52693。恢复前核对容器身份/标记，恢复后及各检查前核对真实数据库目标，只使用显式 TEST_DATABASE_URL。没有操作共享 B8 库或把本轮当成其 `s0_0720/0721` 整体验收。自有库已再次私有备份停服、容器和数据保留，见 [收尾记录](environment-closeout.json)。

前期 44/146 项候选和源码清单继续保留为各自检查点历史，不冒充 P11 当前候选通过。无真实模型调用、真实资格授予、生产属主转交、git push 或真实外发。

剩余：派生/变体唯一引擎接线，知识/字典、证据/共享、剩余视图、整次运行撤回、M3 正式迁移与完整阶段出口。共享通用 owner 政策现已有 B8 的 `s0_0720` 正式迁移；M3 候选表/守卫尚未正式汇合，生产转交仍须相应明确授权。
