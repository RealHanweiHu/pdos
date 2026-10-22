# M3 审查补充复核

2026-10-09，响应 Claude 复核 a/b/c。本轮三项已处理，146 项受影响检查通过；M3/S1 未判完成。

| 补充项 | 实现与证据 |
|---|---|
| a 检查后的源码漂移 | 原 owner-review 的 44 项证据保留为历史候选。[旧清单差异](previous-manifest-drift.json)包含检查后共享代码变化及本轮修改。本轮重新检查 M3、公共命令、B3、模型绑定与注册图；[最终源码清单](final-source-manifest.json)覆盖 140 个源码/迁移/所选测试文件，覆盖范围内从检查前到检查后无漂移。 |
| b Session 写入上下文串号 | M3 validate 返回命令独立的 `ValidatedWrite`，公共 execute 显式交给 `apply_validated`；条目、来源增量与 G0 携带问题继续显式传递。移除 `s.info["m3_provenance"]` / `s.info["m3_reference_privacy"]`，取消条目版本缺少来源时默认记作人工值的兜底。新实库回归先校验两个不同 Run 的 AI 候选和一条人工命令，再写入全部命令，核对独立 Run/writer/confirmed_by、私有来源计数与 Session 无残留。 |
| c 完整受众名单返回 | 删除 `m3_effective_audience`，改为 `m3_audience_member(tenant,category,proposal,person) → boolean`。问题指派、G0 预览与决定只查询本次指定人员。函数保留当前可读提案和有效品类资格边界；跨租户、陌生人员与不可读提案均返回 false。品类可见、指定受众、往轮评审人原规则继续通过。候选刷新工具也会删除旧名单函数。 |

## 当前候选验证

独立标记库 `127.0.0.1:59418/pdos_test`，标记 `bfcfb45f-4eaa-4a65-a038-c1da6b98f8af`。从空库以 NOSUPERUSER/NOBYPASSRLS 的 `pdos_next_owner` 执行现行迁移至 `s0_0719`，再安装 M3 未汇合候选；每次数据库检查都验证独立目标，仅使用显式 TEST_DATABASE_URL。

- [M3](final-m3.log)：46 项通过，含两项新增回归和实际 HTTP/领域事务、注册宿主准备路径。
- [模型绑定与注册图](final-binding-graph.log)：58 项通过。
- [品类、公共命令、B3 定义](final-b3-common.log)：32 项通过；[B3 项目创建](final-project-creation.log)：10 项通过。
- [检查计数](checks.json)合计 146 项不同受影响检查；[服务规范](scoped-lint-server.log)、[工具规范](scoped-lint-tools.log)及[编译](compile.log)通过。
- [实库 schema](owned-schema.json)：12 张 M3 表无差异，16 个函数正文一致，4 个延迟原子守卫、3 个封存守卫存在。[属主与角色实库清单](definer-ownership.json)：52 个已安装 SECURITY DEFINER 函数均由普通 owner 持有，运行角色没有 owner 成员资格/public CREATE，AI 角色直接业务表写权限为零。

共享 B7 的两个未选测试文件在检查期间继续变化；它们未参与本轮检查，也未列入最终源码清单，具体范围在清单 comparison 中保留。这不是全工程或 B7 验收通过。没有改前端，不用历史浏览器证据替代当前后端复验。

新增回归初轮的合成 fixture 重复资格行与期望漏算具名来源已修正，失败日志保留；最终 M3 组装结果覆盖修复后的代码。合成模型台账与资格仅用于隔离回归，不授予真实资格，没有真实模型调用或实际 Temporal 全链运行。

## 剩余与恢复条件

`tools/owner_policy.py` 仍为本地步骤。B7/B8 须按当时真实 head 单调分配正式迁移，固化 owner 政策并核对实际对象属主，见[生产属主方案](../owner-review/production-owner-plan.md)。生产账号创建、属主转交和部署须有对应用户明确授权；本轮未执行。

第 2 项派生/变体命名空间与唯一 `variants.py` 接线仍待完成。第 7 项在本检查点之后已有用户 P11 明确决策并实现，见 [P11 验证](../g0-p11/result.md)；本页 146 项及源码清单属于此前候选。知识/字典、证据/共享、剩余视图、整次运行撤回、真实资格/模型/Temporal、完整 AT/性能/恢复及 M3/S1 阶段出口仍未完成。

自有合成库私有备份后停服、保留容器和数据，见[收尾记录](environment-closeout.json)。旧候选环境和备份保留，未操作共享库或生产，未 push 或真实外发。
