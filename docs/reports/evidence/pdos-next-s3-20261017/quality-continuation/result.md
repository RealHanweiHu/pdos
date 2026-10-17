# S3 分批测试到质量整改与影响分析

依据确认稿 P21，在 S2 候选 `3d6cb71` 的实际功能链证据具备后接续。本闭环修复质量读取仍按单 Run/全接收校验的阻断，并将质量与整改入口绑定当前项目。S1、S2 正式验收状态保持未验收，S3 仍在建设。

## 可用能力

- 每个 Run 保留固定 origin、非空测试子范围、样件与配置；请求可追加合法接收。首个请求时钟保留，后续 Run 的承诺/Start 核对自身不可变动作事实。
- 质量跟进支持分批测试输出。多个当前 Run 共用聚合请求版本时，枚举各 Run 的精确输出；歧义 Formal 不冒充唯一 Run，显式读取仍拒绝，不吞掉 owner 错误。
- 当前项目的 Build 索引约束后续 Run/Issue/Change 深读；用户、型号、项目共同隔离草稿、预览和未知请求恢复。全型号旧草稿不迁入项目。

## 必要检查

最终 PostgreSQL/API 同链检查 **1 passed**（326.06 秒），见[原始结果](batched-quality-chain-current-consumption.log)与[目标及前后源码记录](batched-quality-chain-current-consumption.json)。运行期间后端、测试、运行框架与合同源码未变。显式目标为 `127.0.0.1:64245/pdos_test`、标记 `f9048729-3f2a-4494-af75-56e1db7d743d`、head `s0_0774`；不新增迁移。测试墙钟耗时不作为性能验收。

该同一实际链从两个 Lot 各一件样件开始：A 批最终原值 11 超出固定上限，建立一次有效 Issue，继续分诊/遏制/CAPA、根因及两项调查完成；此时请求仍 executing。随后接收 B、独立计划/承诺/Start、返回原值 10，A 的失败、旧 Run、Issue 和措施均未被覆盖。两 Run Review 共用 Formal 时，跟进仍返回两个精确 Run，显式读取歧义 Formal 拒绝。最后经实际 Issue/CAPA 创建 Change、捕获实际工程/制造对象、保存影响分析，维持 analysis、unknown、orders=[]。这不是新配置复验，措施有效性和 Issue 关闭仍为空。

首轮在 A 失败建单、根因/措施、B 接收及独立承诺后，读取 B 计划输出时因合成夹具仍冻结公共时钟、配对 owner 使用真实时钟而被 `INVALID_TIME` 拒绝，121.71 秒；源码在运行期间未变，见 [原始失败](batched-quality-chain.log)及[目标/源码记录](batched-quality-chain.json)。只将夹具恢复真实时钟的步骤移到 B Promise 之后、跟进读取之前，生产时间守卫未变。

第二轮恢复真实时钟后，在同一位置被 `MISSING_REQUIRED_EVIDENCE` 拒绝，539.03 秒，运行期间源码未变，见[第二轮失败](batched-quality-chain-real-clock.log)。[对实际失败记录的只读诊断](missing-source-diagnostic.json)确定唯一缺失引用是三个 Formal 快照的旧 `timeline.offered.source`。实际 Start owner 已保存最小必要来源；纯配对校验却将旧交接事件当作新消费。修复仅从当前消费投影移除历史 offered 时钟，旧内容仍参与不可变摘要和单调校验，当前 Fact/Run/载荷的来源与 live 原件校验继续保留。修后先复读同一失败材料，再运行完整链，不把局部结构通过当作实库全链通过。

[修后只读复验](missing-source-after-fix.json)已读取同一实际 storage 配对材料并完成当前结构核对；该诊断保留了旧投影的缺失路径以解释差异，不构成 live 授权或完整 API 链通过。

- 最终后端受影响纯检查：144 passed，见 [backend-pure-final.log](backend-pure-final.log)。新 paired 结构测试含严格子范围、首时钟、历史改写拒绝、相同接收时钟的退回后再接收，以及历史 offer 不重复消费但当前 Fact/Run/载荷来源仍须完整；旧候选的 138 项记录另保留。
- 前端两个质量 view 的纯检查：101 passed；局部 TypeScript、ESLint 通过（独立交付代理执行）。
- 主目录完整 Web 构建通过，见 [web-build.log](web-build.log)。当前目录同时含其他聊天的 UI 工作，本报告只归属质量入口接续，不以构建结果宣称整仓或 UI 全验收。

全部本轮检查进程已结束，fixture 已恢复临时分类/host/view/结果桥配置并禁用合成发布者，未启动预览服务或浏览器；已确认的合成库继续保留供下一闭环复用，不清除历史证据。

## 尚未完成

完整 S3 的双线影响完备性、正式变更具名批准、受控新工程/制造配置、新 Build/新请求/新 Run 和适用独立有效性仍须贯通。当前影响分析允许如实保留 unknown，图存在不等于完整，措施完成不等于有效或 Issue 已关闭。

同请求多 Run 的正式独立复核接口仍以聚合 Formal 绑定材料，尚不能宣称已支持；后续完整复验先走真实新配置/新请求/独立新 Run 的合法链。正式有效性、Issue 关闭和变更复验的 public command 接线仍须实施。另已发现正式变更读取 Issue 当前版的字段疑点，留至相应真实链验证，不计为本批修复。

性能验收暂缓；S1 真实 MiniMax 联验与三项既有间歇失败仍未关闭。本批无真实模型、真实 KMS、客户资料外发、资格授予、生产操作或 git push；未重复启动攻防。
