# PDOS Next：制造准备、当前依赖闭包与受控覆盖开发检查点

已将作业指导、控制计划及固定子文档制造基线接入实际变更依赖图。新增数据库所有的依赖水位及同事务共享锁，覆盖隐藏新增依赖、业务字段撤销再恢复和跨产品共享资产；共同回执尾部不会自行使图失效。旧捕获保留，缺少新证明的历史不能用于新的正式批准。Tooling/Fixture/Pilot/Release 等尚缺的真实关系及八 facet 可信覆盖保持 UNKNOWN。

制造图和依赖水位的实际 PG 检查点为 `next_0030`、123 张表；下述完整业务案例只覆盖对应的旧冻结候选。[冻结源与覆盖范围](head30-development-checkpoint-v1.json)包含 612 个实际源/迁移/测试文件。两个完整失败报告→Issue/CAPA→变更事务案例通过，涵盖旧图的资格 ABA 拒绝和事件尾部失败的整体回滚，耗时 49 分 41 秒；进程在末端 impact SHARE 小接线前已导入旧模块，不能声称它覆盖了该接线。最终实际共享锁函数由三个制造图/水位/双 Session 案例验证，其中含租户共享资产变更被锁拒绝、零部分效果及释放后重试。362 项变更内核/宿主/闭包纯检查通过，受影响静态检查通过。更宽静态扫描中的三处未改文件 import 顺序失败保留在 v4 原日志，未据此宣称全仓库 lint 通过。

[实际完整编号往返](clock-roundtrip-v3.json)验证 122 张原表完整行摘要保持、最终目录重建及 schema 一致。真实闭包保存后，[拒绝破坏性回退](clock-used-proof-downgrade-refusal-v1.json)验证全部 123 张表及目录不变。备份保留在本地私有目录，角色凭据不放入报告；Agent 对业务表直接 DML 为零。

新的有限合成账号通过实际 API 创建 WI/CP/基线，再通过独立预览 3037 的 BFF 完成[只读入口](preview-http-read-v1.json)及[WI 续版、原请求零新增重放、历史保全](preview-http-save-v1.json)。旧基线仍引用原子文档，并如实标记待重核。旧账号/Grant未延长。实际前端生产构建通过，使用冻结的真实 Geist/Geist Mono 缓存字体；Google 下载网络未验证。Mac 锁屏且浏览器不可用，GUI 整链与亮暗/多尺寸未通过。3028 及原共享 API/worker、62513/57432 未用于仓库测试，也未升级或替换。

当前实际隔离库已至 `next_0032`、125 张表。[覆盖迁移往返](coverage31-migration-v1.json)验证 30→31→30→31、全部 123 张旧表完整行摘要不变、原/新完整数据库目录恢复和 schema 一致。两表强制 RLS，Auth/Agent 零直接 DML，全仓业务表 Agent 直接 DML 为零。首次真实 publication 在成功提交阶段发现头31约束的 JSON 包含表达式缺少右操作数括号，整体回滚，未保存覆盖 Fact。[新32修复往返](coverage32-migration-v1.json)验证31→32→31→32、全部125表完整行摘要不变、两个head完整目录恢复/重建、schema一致与原函数ACL保持；未改已应用31。第二次实际发布已保留一个合成 Fact，[历史覆盖降级拒绝](coverage32-used-proof-downgrade-refusal-v2-result.json)验证32→31明确拒绝、全部125表完整行摘要与数据库目录保持、Agent有效直接DML为零；完整0600私有备份及摘要保留。[验证脚本首版错误](coverage32-guard-harness-v1-failure.json)发生在降级前，只读权限扫描构造了错误的public系统表名；修正版改用实际关系OID，原始脚本未覆盖。

实际覆盖 owner 已接入图捕获、影响计算及正式变更单的每相位复核，保存与合并完整来源读集、事实/原件/issuer/Current/依赖水位证明和最早期限。跨合法 canonical 后继版本仅放宽当前 Change 的 version_id/revision，Current 身份、固定 origin/request 及其余证明保持；同相位 refresh 仍完整精确比较。缺 Current 的新图保持 UNKNOWN；保存过的完整图遇失效、宿主撤销或原件/权限变化拒绝当前动作，缺少 NEXT 明示边仍 UNKNOWN。新增逐祖先 owner/visibility ABA、完整覆盖导入次序及所有其他 owner IO 后实际发布者权限尾部复核。它们的真实业务接线尚未全部通过正例。

[当前实际纯检查](actual-coverage-binding-pure-v3.log)527 项通过，[受影响静态检查](actual-coverage-binding-statics-v2.log)通过；v1 的六个旧测试替身缺新字段失败与修复日志保留。独立进程验证注册模型及四类覆盖运行入口，不打开数据库。[实际权限行锁](actual-coverage-permission-fences-pg-v1.log)4 项通过，涵盖 A/B 权限行在事务结束前阻止撤销、释放后撤销及 pending Grant 三字段保全；它不代替完整 A 发布/B owner 回读正例。[只读范围检查](actual-scope-only-pg-v1.json)因没有有效旧夹具退出，没有执行 helper 或延长 Grant，不声称实际提速。

实际前端已新增八facet只读覆盖表，逐对象完整统计已列明、UNKNOWN与待核对，对应影响缺边仍分别保留；原完整图/来源详情、办理权限、请求恢复与Current选择保留。新3文件及父级2片段绑定[实际源码](coverage-reading-actual-source-v1.json)，[55项实际纯检查](actual-coverage-reading-pure-v1.log)和[受影响4文件lint](actual-coverage-reading-lint-v1.log)通过；[175文件实际冻结构建](coverage-reading-development-checkpoint-v1.json)通过，使用真实Geist离线缓存，所有实际源码在构建后保持；浏览器仍未验证，3028/3037未替换。

[范围减读审查](coverage-scope-review-analysis.md)证明 supplemental Issue/CAPA reference 可不在roots闭包，两次roots registry不能代替它们的完整Source/失败/政策守卫。本次未合入范围减读，8项仅为禁DB/网络的暂存纯反例，不登记真实性能改善。更窄末次binding候选仍因原Start签人Principal可在其他IO后变化而拒绝，保留第三次完整seed。当前代码保有该守卫。

[首版真实发布日志](actual-coverage-publication-pg-v1.log)保留26分20秒的实际失败：[645源冻结检查](actual-coverage-publication-run-v1.json)确认源码未变，提交被上述SQL缺陷拒绝。[头32第二次实际发布](actual-coverage-publication-pg-v2.log)耗时29分44秒，646份[冻结源始终未变](actual-coverage-publication-run-v2.json)。其执行已通过三处flush故障后的整体行摘要相等、成功发布提交、Current owner真实read/refresh与旧UNKNOWN图/TTL保全，最终原key重放在真实当前有限窗口守卫处失败；整体案例保持FAIL，不宣称原key恢复通过，不延长原窗口。日志未记录各deadline的最终值，不仅凭总耗时判断是哪一项期限失效。缺scope/缺facet原件不得获pin；完整声明仅为该固定合成范围，不能当真实库存、客户、生产切换或培训资格。

新捕获现在取覆盖材料的最早期限，并为缩短后的完整图重新取得真实owner读取凭证；旧捕获和原窗口不改。保存fullflush后重核Current、依赖水位、发布者访问、运行配置及实际期限。[实际14项纯回归](actual-capture-deadline-pure-v1.log)通过；它们替代owner IO，不能当PG正例。共同影响/正式变更回执最后fullflush后的固定尾部核验已接入：当次真实CoverageRead绑定Session/UOW、完整command/context、返回ORM原行与完整proof，按closure→当前access→runtime/真实Host→材料/UOW→真实期限核对并清理；无JSON重建token、跨命令cache或新注册权。[612项受影响实际纯回归](actual-change-publication-tail-pure-v2.log)、[受影响静态检查](actual-change-publication-tail-statics-v1.log)通过，范围和源码见[检查点](change-publication-tail-development-checkpoint-v1.json)。其中新增尾部64项+捕获14项是明确替代SQL/领域事实的检查，不代表真实正式批准或事务提交通过。

[653份冻结实际源](coverage-public-capture-actual-source-v1.json)的单一公开capture→impact→原command恢复案例已在已核对62158结束，[29分27秒真实日志](actual-public-capture-pg-v1.log)整体FAIL，[源与插件全程保持](actual-public-capture-run-v1.json)。真实新key完整捕获包含12节点/96覆盖项，原UNKNOWN捕获与窗口保留；进入impact inputs时材料还余181.89秒，该调用实际耗时197.79秒，最终409 COVERAGE_OWNER_STALE，[退出已超原期限15.91秒](actual-public-capture-pg-v1.json)。没有执行共同impact保存或原command恢复，不登记其正例，不续旧窗口。测试静态遍历由约37次缩至约25次，仍未取得可用速度。

[被动真实计时](actual-public-capture-sql-v1.json)记录585493次成功SQL、1061.34秒累计SQL耗时；fixture setup为1067.88秒，业务body为699.51秒。仅保存形状SHA/次数/耗时，无SQL正文/参数/URL；全Engine/线程合计、成功SQL限定且并发聚合精度未验证，不能把累计时间分配到业务相位。[离线精确形状解码](actual-public-capture-sql-decoded-v1.json)在top25中匹配9项schema/可能调用候选，主要为Artifact、source_for Product/Artifact与人员读取，其余保持unknown；所有真实owner/phase/Engine仍未归因。后续据此查找同一物料读取内重复Source/权限路径，完整fullseed、来源原件、安全epoch与末端守卫不删。旧key/缺Source负例与独立deep successor全proof回读的完整候选仍保留未运行。Process wrapper cache因每ref权限/Source刷新边界未能安全证明，尚未采用。

制造资源只读owner与精确Build/Process/工序关系已贯通实际认证API、BFF和Build界面，复用固定OperationalFact/Current、原件字节/完整读集及同事务人员守卫。Product→私有Current/Fact/publisher pin→完整People NOWAIT→Scope Clock；Clock后先比pin，Asset仅精确MVCC SELECT并保留完整材料/元数据/末端时钟复核。shared _one/lock_people只增加默认False的NOWAIT转发，55P03由资源wrapper映射409并逃出整事务。[4项实际锁/水位PG](actual-manufacturing-resource-locks-pg-v2.log)验证跨Product共享Asset、People NOWAIT整事务释放、合法业务值ABA/序号及Clock+2和占用序号回退整体拒绝；[首版夹具错误](actual-manufacturing-resource-locks-pg-v1.log)保留，未放宽约束。

[最终资源公开入口检查点](resource-public-entry-development-checkpoint-v2.json)记录当前源码与覆盖：[748项实际受影响纯回归](actual-resource-and-professional-affected-pure-v1.log)含32项认证路由/strict DTO检查，[7项资源前端纯检查](actual-resource-reading-pure-v1.log)、[67项实际BFF回归](actual-resource-reading-bff-pure-v2.log)、[最终类型/受影响lint](actual-resource-reading-final-type-lint-v3.log)和[178文件冻结生产构建](actual-resource-reading-build-v3.json)通过；纯路由替代SQL/owner/auth，BFF替代host IO，不当实库验证。界面核固定操作和微秒级Scope，丢弃过时异步结果，完整展示原件、关系出处及<=20读集；只读失败不会提示恢复业务命令。

[真实注册来源/资源Fact/读取及认证HTTP](actual-resource-and-professional-native-pg-v2.log)在62158的头32通过：实际NativeText原件注册与可信合成issuer的固定Fact/Current保存，同一真实Session/UOW inspect与refresh一致，原始期限和issuer不变，实际API认证读取与直接owner投影逐字段一致，未认证/异租户拒绝；21张相关表完整行摘要保持。[冻结的677份实际源](resource-and-professional-native-actual-source-v2.json)全程未变。[首版PG](actual-resource-and-professional-native-pg-v1.log)中观察器以业务角色读取login_sessions被数据库正确拒绝，改为原有auth角色只读完整摘要后仅重跑失败病例；未改业务授权、原窗口或生产代码。所有材料明确synthetic，该正例不授真实资源资格。A验收/校准/人员资格仍UNKNOWN，execution/global completeness仍false；资源图注册及WI/CP/Pilot/Release真实关系待齐。

为加速完整业务闭环，只合入专业Fact读取的一次full-ORM ID-IN查询：先枚举完整Current（含无效/过期/撤回/私有记录），pending或不一致内存数据回退原路径，同Session第二评估仍重新读取；原件字节与安全/权限交错校验保持。[43项新增实际纯检查](actual-professional-fact-batch-pure-v1.log)通过；上述首版PG其余4项真实专业病例通过，涵盖每次评估一次bulk、同Session fresh、pending资格保全，以及原issuer ABA/Source撤回/RLS和Agent零DML。首版整体仍FAIL，不能用4项局部PASS冒充完整通过。Artifact元数据提前批读、Process wrapper缓存和common原子组批读没有合入。新的完整capture→impact→原请求恢复v2正在同10分钟新材料政策下实测，性能尚无结论；旧失败/窗口保留。

下一实际施工为仅fixture的 `npi.fixture.accept` T2：独立具名不可变Decision/连续Current，固定资源、双配置/工序、用途窗口与完整来源，由当前有制造职责及资格的本人签署，复用共同预览/消费/回执。schema/models、领域服务和共享迁移接线在私有独占候选并行；公共后端已冻结供性能实测，尚未合入或宣称可办理。拒绝/撤销保留完整历史，撤销不因旧资源材料或旧决定已过期而被禁止；校准/人员资格、released制造基线和Pilot的依赖不下调。

公开完整捕获/影响/合法后继proof、正式双线批准/实施正例、新Run全部复验、完整观察、独立Review/关闭、GUI与真实资格和人工出口仍待齐。9/27部分登录/序列无法完全重建的恢复边界保留，不能宣称历史零丢失。
