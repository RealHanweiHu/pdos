# 新开测完整凭证、原请求恢复与制造准备后端检查点

新 Start 已在同一共同 T1 事务保存完整 `test-resource-dependency-v2` 凭证，实际 Reservation 两个新列与原 Start、保存结果的资源摘要一致。完整十二键材料只包含实际使用的 issuer 依赖；其他范围新增配置不会改变已保存的凭证。旧 Start 不回填，真实旧预约保持 SQL NULL/NULL，严格旧版本历史兼容继续保留。

实际事务验证发现并修复了原请求恢复的额外写入：已有预约重核仍初始化样件门栓，冲突 INSERT 的 BEFORE 触发器也会增加 Product 生命周期水位。现在已有预约只锁定、读取原门栓，缺失则拒绝重建；当前写权限、来源、资格、完整消费归属、运行范围、同事务和最后时钟守卫保留。修复后的同一原请求恢复原回执，全部17张相关表的完整行哈希保持不变，包含 Product 和 T1 消费状态。

制造准备复用现有真实领域/API和可信导入端口，在独立合成夹具中完成控制计划独立首存、作业指导首存与续版、固定当前子文档的制造基线、历史与原请求恢复。基线保存完整 Process 范围与两个固定子文档链接；未知参数、未完成检查、草稿、未知放行和缺项保留。已提交响应丢失后恢复原回执；末端共同回执故障整组回滚；来源撤回后保留历史原文并拒绝原请求执行；private 同产品同行仍不可读。这是后端正向验证，当前前端不在本轮验证范围。

按影响验证，以下各组不能相加冒充完整联合出口：

- [实际新 Start/事务故障/原请求恢复](actual-versioned-atomic-pg-v2.json)及[原始PG日志](actual-versioned-atomic-pg-v2.log)：1条完整业务案例通过，652.74秒。覆盖缺失共同组、结构完整但原 Start 凭证错误、四条共同记录实际 flush 后故障、同一确认合法重试、实际提交后响应丢失、完整版本回读、范围外 issuer 增加、原请求零新增效果，以及真实 SQL 拒绝残缺凭证。失败候选及[修复说明](actual-replay-watermark-repair-v1.json)保留，未删除 Product 哈希断言。
- [实际制造正向事务](actual-manufacturing-transactions-pg-v1.json)及[原始日志](actual-manufacturing-transactions-pg-v1.log)：1条 WI/CP/基线业务案例通过，22.01秒。UNKNOWN恢复、回滚与撤回后拒绝均比较全部9张效果/控制表完整行；成功新增引用的父内容检查只排除合法变化的 Product 水位，见[边界说明](manufacturing-row-hash-adaptation-v1.json)。其余 Product 列和10张父表全列保留。
- [99项资源纯检查](actual-resource-dependency-pure-v2.log)、[157项历史/Launch纯检查](actual-retained-launch-pure-v2.log)及[12项无连接测量工具检查](actual-worker-profiler-pure-v1.log)通过。IO替身不是实际资格；第二十六波未改的9条慢PG案例没有重复运行。
- [受影响静态检查](actual-selected-static-v5.log)通过。Ruff覆盖所选文件，格式检查保留生成目录中既有制造尾部的格式差异；原失败记录保留。来源见[626路径冻结记录](actual-source-candidate-v4.json)：385运行/迁移、71所选测试、5工具，另捕获165前端文件；后者没有本轮构建或浏览器验证。

`next_0029` 在独立 `63866/pdos_test`、marker `20a17344-1e35-42e1-95ab-e100e56e9d88` 完成 [28→29→28→29](isolated-migration-checkpoint-v1.json)，旧完整目录恢复、ORM差异为0、Agent对122张业务表直接DML权限为0。[已使用v2的破坏性降级](used-v2-downgrade-refusal-v1.json)正确拒绝，全部122张表及目录不变。Repo测试始终没有使用62513或57432。

本地存续合成预览62513备份后升级至 `next_0029`，见[最终迁移核对](shared-migration-checkpoint-v2.json)。原122张表内容与精确迁移前备份一致；351个旧CHECK逐个核原备份DDL，旧触发器、函数、策略和权限保留；只增加两列、一条CHECK、两个约束触发器及其函数。首次目录比较漏算约束触发器的第二处登记，恢复备份的表达式显示又因数组转换重解析产生差异；均在只读核对中解决，没有重复升级或改旧谓词，原失败证据保留。

实际API8898与worker已用冻结后端恢复，健康200、Temporal workflow/activity两类当前worker轮询均核实，见[运行回读](runtime-read-only-checkpoint-v2.json)。旧账号会话及Product Grant仍过期，HTTP401 `UNAUTHENTICATED`，没有延长授权，不能宣称当前旧质量页面可办理；回读期间全部122张表保持不变。原回读计时包含随后全表快照，v2明确纠正范围，没有冒充单个HTTP时延。独立Root63866测试容器及其中用于备份目录核对的私有克隆库已[备份清理](isolated-test-cleanup-v1.json)；62513、状态PG65109、Temporal65425、Web3028及原工程环境保留。

[实际耗时分解](actual-current-read-measurement-v2.md)区分真实等待与业务请求：观测区间505.543秒，合法未来窗口等待216.315秒；开测预览12.211秒、实际提交42.290秒、原请求恢复12.973秒。104191次SQL包含Root和同Engine工作线程及本案例故障验证，不能当成单次API查询数；工作线程阶段全部为unattributed。资源完整读取与样件读取是下一优化候选，尚未完成安全重用和提速验收，不能宣称已提速。

下一步接八类影响覆盖的可信完整owner、必要显式边和批准各阶段的完整闭包重核，再办双线具名批准、实际领域实施回链、新合法Run复验、完整观察与独立Review。并行暂存的UNKNOWN覆盖接口与预览重用反例没有部署，不授覆盖事实或执行权限；缺材料继续未知。当前制造界面整链、试产持久化/资源/分别放行、真实专业资格、模型/golden-case、人工出口及全部G/AT/N/P/Q仍未完成。9/27备份后部分登录/序列不能完整重建的历史边界保持。
