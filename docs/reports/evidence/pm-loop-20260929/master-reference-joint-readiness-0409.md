# 产品经理0409联合验证用例准备

2026-09-30，续接[D22交接引用候选](master-references-0409.md)。本次补可执行的合成数据库/API用例与迁移测试边界，并修复本闭环测试可能误接保留库的地址护栏缺口；原13份D22源与摘要一致，没有修改业务/迁移实现。此前68项受影响检查保留其原覆盖范围，不能据此认定新增数据库用例已通过。

## 已准备的用例

| 文件 | 待执行的真实数据库/API检查 |
|---|---|
| [API用例](../../../../server/tests/test_product_master_references_api.py)（9项） | 四种合法系统/对象组合的登记、纠正、撤回与固定历史；原请求重放不重复行/事件/审计；真实定义替代、撤回与产品退役；实际viewer/manager及撤权、跨空间与原操作者；元数据/空白正文拒绝、来源失效后拒读；独立HTTP并发的相同/冲突请求、后继及重复活动定位；真实事件审计写入后注入异常，核对事务整体回滚。另分别撤销Line权限而保留Space权限、撤销岗位而保留原登录JWT及原空间/产品线权限，核对历史读取和原请求重放拒绝、不披露标识或新增写入，以及恢复权限后的显式重新读取/重放。 |
| [迁移用例](../../../../server/tests/test_product_master_references_migration.py)（5项） | 空库0409→0408→0409恢复表、触发器及函数；实际目录与metadata列/类型/约束比对、真实pdos_agent零表/列写权限；有数据拒退、UPDATE/DELETE拒绝及历史字节不变；非法系统/对象/未来时点/范围外键/当前发布及产品版本；单一后继、撤回固定字段、撤回后拒绝再续。另以空引用表、非空已发布产品定义/协审/策略/证据/事件/审计和全部既有业务表为基线，核对往返时已有行及列/约束/索引/用户触发器保持。 |
| [共享合成准备及地址护栏](../../../../server/tests/product_master_reference_fixtures.py) | 使用实际产品定义发布与保存正文的领域/API路径；准备阶段模型替身调用次数必须为零。会话级护栏在共用迁移/租户清理夹具前要求显式TEST_DATABASE_URL与pdos_test，拒绝已知本地保留端口57432/57433/57434/57439/57440。地址形状通过不构成分配授权或实际目标核验；不自行创建数据库。 |
| [护栏纯单元](../../../../server/tests/test_product_master_reference_test_safety.py)（18项已通过） | 本地保留地址拒绝、显式变量缺失不回退旧变量、非测试库名拒绝，以及非保留地址形状无需连接。用例中的地址仅为字符串，未分配、探测或连接。 |
| [现有迁移链检查](../../../../server/tests/test_migrations.py) | 初次准备时更新至0409/410步；交付核对发现其他线新增0410/0411，现按真实源head0411_plan_lineage_aliases与0000～0411共412个单调修订更新显式边界。原唯一head、无分支及逐步前序断言保留，不从当前文件自动推断期望值。 |

API九项与迁移五项共14个测试函数，均为**待执行**。Line/岗位撤权与已有非空数据保全已经写成用例，但尚未得到实库结果。迁移用例直接使用真实迁移函数和事务中的操作上下文，不移动Alembic版本；不能替代实库CLI升级、`alembic check`与版本往返，也不能代替实际浏览器或真实主数据原件核对。

七组D22数据库场景中的DB04已纠正一处过宽的拒绝判据：产品路径的tenant/Space/Line/product及当前权限必须成立，来源另按其自身真实授权、版本与正文复核；合法同租户共享证据不因已被其他产品引用而失效。完整合同D22/§15.2/§20及对象合同§4.6均未规定此类证据独占产品线，现有来源和历史领域路径符合这一边界；见[只读审阅记录](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/source-authorization-review.json)。这不是新增授权，也不是权限实库验证通过。

两个并发用例不再只靠HTTP同时提交：控制连接先实际锁住本空间，观察包装仅增加会话超时及真实PID采集，随后调用原领域上下文。独立AUTOCOMMIT连接必须同时观察两个API事务正在市场空间`FOR UPDATE`上等待锁，才释放控制锁；异常时先释放锁再收尾线程。PID采集、结果读取、监测及SQL等待设有上限，线程收尾仍依赖实际SQL结束，不能据此宣称生产调度超时已验证。PID、原始锁等待/查询/阻塞关系及HTTP结果写入测试属性；未来实库执行须保存JUnit属性输出。此处是可执行判据准备，不是已观察到并发通过。

## 离线检查与证据边界

- 新增数据库/API用例仅收集14项，未执行fixture或测试正文，见[收集输出](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/collection.log)。执行计划确认会话级地址护栏先于函数级迁移/清理夹具，见[夹具计划](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/fixture-plan.log)；计划明确为no tests ran，不能计作迁移通过。
- 地址护栏18项纯单元通过，见[输出](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/safety-tests.log)。收集、夹具计划和纯单元子进程均移除数据库环境变量，并安装数据库/网络连接拒绝守卫。纯单元仅在测试内设置合成URL字符串。
- 五份归属文件Ruff与格式检查通过，见[lint](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/lint.log)、[格式](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/format-check.log)。随后只有迁移链期望值变化，对该文件单独补做[lint](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/migration-head-lint.log)和[格式](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/migration-head-format.log)。
- 五份归属文件严格类型检查通过，导入依赖保留类型但不报告其诊断，见[归属类型检查](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/owned-types.log)及更新期望值后的[迁移链类型检查](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/migration-head-types.log)。前一检查点普通检查曾在排程、物料两个非归属模块报类型错误，原输出见[首次检查](../../../../output/pm-master-reference-0409/joint-test-readiness/types.log)；其他线随后继续修改，本轮不重判它们，也不宣称共享仓库完整类型检查通过。
- 初次0409/410步的迁移链离线检查1项通过，见[旧输出](../../../../output/pm-master-reference-0409/joint-test-readiness/migration-history.log)。共享源变化后对0411/412步补做同一项，见[当前输出](../../../../output/pm-master-reference-0409/joint-test-readiness/resumed/migration-history-0411.log)；不是两项不同用例，也没有数据库迁移、约束或往返执行。0410/0411业务与触发器效果仍属其他线待验证范围。
- 独立审阅发现迁移用例将反射时间类型的默认字符串与PostgreSQL编译结果比较，会误报`TIMESTAMP`与`TIMESTAMP WITH TIME ZONE`。已改两侧使用同一真实方言；[离线方言核对](../../../../output/pm-master-reference-0409/joint-test-readiness/dialect-check.log)仅证实类型编译差异，不是数据库证明。
- [本次补充源摘要](../../../../output/pm-master-reference-0409/joint-test-readiness/source-candidate.json)单独记录五份归属文件及原13份D22源不变的核对结果；[初次11项准备摘要](../../../../output/pm-master-reference-0409/joint-test-readiness/initial-11-functions/source-candidate.json)与原日志保留为前一检查点。上一候选的68项没有重复执行或扩充计数。

## 独立前端构建与未登录HTTP

前一检查点的1049份前端源独立快照已用真实Next 16.3.3/Geist完成生产构建，含编译、TypeScript、97页生成及打包追踪，见[构建输出](../../../../output/pm-master-reference-0409/web-build/build.log)、[源快照](../../../../output/pm-master-reference-0409/web-build/source-manifest.json)、[结果与归属核对](../../../../output/pm-master-reference-0409/web-build/result.json)。七份D22前端源与构建和当前源一致；构建期间四份项目页面/测试由其他线更新，后续这些改动不计入本次快照，也不宣称整个共享工作树冻结或最新全树已构建。本轮仅补测试与证据，未重跑这一构建或四项HTTP。

初次受限构建无法解析Google字体服务，保留[原失败](../../../../output/pm-master-reference-0409/web-build/build-sandbox-dns-failure.log)；运行权限放开本次现有字体依赖下载后，同一快照构建通过。重试前的全共享源保护检查曾因另外三份文件更新而停止，随后核对七份PM源不变，继续固定快照；没有修改共享前端源、字体实现或使用字体mock。

已仅启动本快照的临时生产前端，后端固定为禁用地址，不使用cookie/令牌。新引用路径GET/POST均401、PUT及扩展history路径均404，四项均no-store；见[真实HTTP回执](../../../../output/pm-master-reference-0409/web-build/http-checks.json)。本轮自有服务已关闭；受限进程首次本地监听被环境权限拒绝，未启动服务，放开本次临时监听权限后执行。实际使用`next start`，其standalone配置警告保留于[服务日志](../../../../output/pm-master-reference-0409/web-build/http-server.log)；这四项只证明编译后前端的未登录/非法路径边界，不是standalone部署、合法登录领域HTTP、数据库、浏览器或业务整链证明。

## 剩余执行顺序与恢复条件

1. 获得跨会话交接授权后，请“估算执行计划完成时间”按现有安排分配产品经理独立临时pdos_test。显式核对TEST_DATABASE_URL及目标，建立本次候选记录；真实pdos_agent必须存在，不能将角色缺失当零权限证明。
2. 以届时冻结的真实共享head集中执行上述14项、[0408八项API](../../../../output/pm-research-source-0408/queued-api-scenarios.json)、[0407父版/策略来源API](product-lineage-0407.md)。当前共享源为0411，0409只是本PM功能的迁移步骤；CLI升级、metadata与版本往返须覆盖实际冻结链，D22函数操作用例不能替代后续步骤验证。保存历史保全、当前权限/独立来源原始日志和并发JUnit属性。
3. 将上述快照构建范围带入同一候选，完成合法登录HTTP与RFQ→竞品/市场→机会/实验→策略→发布→矩阵整链，以及D22真实页面亮暗/多尺寸与恢复；源变化或具体失败再做相应构建。14项待执行数据库用例、18项纯地址护栏及四项未登录HTTP不能替代这些出口。
4. 补允许的真实研究材料/搜索服务、有效计量及调用授权、八能力独立人工参考/服务商原始证明、RFQ四类原名称、实际外部主数据原件、具名专业协审和人工Exit，才可按原条目关闭。

跨会话发送授权问题仍待人类回复，未发送指令；本次没有读取.env、连接任何数据库、迁移或清理任何环境，也没有模型、真实搜索、业务外发、资格授予或生产操作。联网仅为构建的现有字体依赖，临时前端仅做本地无凭据请求。57432/57433/57434/57439/协调保留57440均未操作。N1-01～06/N6-04仍为部分完成，0377恢复不能宣称零丢失的历史边界保留。
