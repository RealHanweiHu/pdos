# build / lot / sample / issue / run 领域结构读取（2026-10-22）

本次新增五个小Pai受控 READ 工具：`build.read`、`build.lot.read`、`build.sample.read`、`quality.issue.read`、`test.run.read`。已接注册表、Bootstrap 执行/恢复/同会话历史复核，以及 build_execution / quality_issue / test_verification 三个技能包（0.1.1-draft）。范围为[十份源码/技能/测试文件](source-manifest.json)，其余在途改动保留。

## 可用能力与边界

- 仅在服务器绑定的当前品类、型号、项目内读取，支持精确 id 筛选和 UUID 游标分页，默认50、每页最多100。Issue / 测试Run 从真实 Current 指针返回业务 id、当前 revision 及不可变 version_id；其他三类返回记录 revision 和固定关系。测试对象筛选参数为 `test_run_id`，不与小Pai运行身份 `run_id` 混用。
- 返回白名单结构元数据（id、版本、关系、记录状态、摘要/创建时间等）；`projection=structural_metadata/v1`、`basis_status=not_assessed`。不返回自由正文、客户名称、原件或测量原值；样件身份不证明就绪/可用/未消耗，固定请求版本不冒充请求当前版本，记录存在不证明来源仍适用。有效性和办理权限继续由领域命令判断。
- 新项目 Run 受理时，通过请求人的当前普通 RLS 核对实际项目和可读私有对象元数据；服务器保存 `project_metadata_context` 并绑定 `internal` 类别，必要时保守标记 private。共享项目中本人可读的私有 Issue 也受此绑定保护；模型无法传入此权限。每次读取仍执行当前 Agent/请求人/项目 ACL 和取消守卫；旧运行没有相应私有绑定时须新建运行。没有赋予业务表直接写权限或追加 RLS 例外。
- 每次模型发送继续走原网关的实际服务商/类别检查与回执；P26 无协议不阻断，当前有效协议不允许 internal 时零派发。恢复重新读取并比对原结果，Current 变化或权限撤回拒绝旧结果。

## 验证

最终结果见下方日志与收口记录；各组有重叠，不累加冒充整仓通过。

- [内核纯回归](kernel-pure-regression.txt)：1570通过、435按数据库/检查点依赖排除；4项初始失败中，三项为本机 loopback / Docker 沙箱权限，[有权限复核](loopback-container-recheck.txt)三项通过；另1项为既有技能覆盖缺口，未称全组通过。
- [既有技能覆盖对照](skill-coverage-baseline.json)：HEAD 与本候选同样缺 change.close / change.effectivity.record / change.verification.record 三条声明，新增五个 READ 均已被相关技能声明。此项未修复，不称整组全绿。
- [定向纯检查](pure-regression.txt)首轮206项通过；后续新增服务器绑定/独立进程导入检查已纳入上面的内核组，新端口纯用例共61项。
- [最终 PostgreSQL 结果](pg-tests.txt)：2项通过，覆盖实际五类读取、分页、同键回执恢复、11类业务/共同记录计数不变、Issue当前指针续版后旧结果拒绝、新读取得revision=2、错项目/不可见id/撤权拒绝，以及当前协议不允许internal时网关零派发。同一显式 TEST_DATABASE_URL 指向独立 `127.0.0.1:64245/pdos_test`，核验容器、marker `f9048729-3f2a-4494-af75-56e1db7d743d` 与真实 head `s0_0812`。无新增迁移。
- 原三入口上下文实库回归3项通过，包含在[前轮记录](pg-triage-fixture-failure.txt)中；该轮主链末尾因测试未发布既有风险政策而失败，不计该主链整条通过。
- [Ruff](static.txt)、git diff --check 通过。无前端变更，未重复前端构建/浏览器检查；无性能结论。

## 失败与恢复

- [首轮纯检查](pure-initial-check-failure.txt)：调用须知 source 使用了未登记标签，已按 READ 档位来源修正；从仓库根执行导致子进程 import 失败、误包含3个DB用例，已更正执行目录与分组。
- [首轮PG夹具失败](pg-initial-fixture-failure.txt)：合成模型回执用了全工具列表摘要，实际披露不同，可信守卫正确拒绝；改为真实 disclosure 摘要。
- [共享项目私有Issue失败](pg-private-issue-failure.txt)：RLS可读但未有私有元数据出站绑定，新增服务器受理绑定后五类实际读取/分页/回执与业务记录数不变验证已通过。
- [末尾夹具失败](pg-triage-fixture-failure.txt)：Issue续版的测试未先发布既有合成风险政策；按原夹具规则补齐，不修改领域政策。

## 剩余

本增量仅补上述五类结构读取。请求当前版本、测量/失败事件、Change、放行包与移交正文读取仍按原入口边界，不推定已经补齐。真实模型评测、租户启用与T0资格未办理；没有真实模型调用、外发、push或阶段验收声明。
