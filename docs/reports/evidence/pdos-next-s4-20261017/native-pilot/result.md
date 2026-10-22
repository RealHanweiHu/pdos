# S4 原生 Pilot 开发检查点（2026-10-17）

本稿记录已完成的开发检查点：最终 API06 与实际浏览器闭环通过，不代表 S4 或 S1–S4 正式验收。

按 v1.1 §04.9、§08.11 和确认稿 P21 续建，Pilot 是现有 Build 的制造扩展。原件均为实际登记的合成字节，专业依据使用受控 synthetic profile；本轮无真实模型或 KMS 调用。

- 已接通 `npi.pilot.create`、`npi.pilot.result.record`：实际 inputs → 共同预览 → 本人一次确认 → 保存及固定回读；项目、Build/Lot、实际双配置、制造发布和来源由服务器核对。
- 创建根固定 revision 1；原始观察及修正追加不可变记录，Current 按真实前版逐次推进，保留原观察、修正理由和固定统计口径。
- 投入、一次合格、返工、最终合格、报废及异常 Issue 可读可录；固定分母计算 FPY/FGY。分区尚未完整时保留已记录比例，最终良率不冒充已知；修正不改分母或覆盖历史。
- 共享内容可由具备实际范围权限的同行回读；其不可读取原提交人的 RequestKey 私钥正文。私有项目、实物、配置或 Issue 不得扩大为共享 Pilot。
- 同 key 与换 key 语义重放返回原回执，不新增业务记录；换 key 仅建立必要请求别名。共同尾部故障完整回滚，来源撤回后保留历史并阻止新消费。
- 始终保留 `qualification=unknown`、`start_authorized=false`、`manufacturing_release=null`；统计结果不授予资源、人员、启动或工厂合格资格。

本轮按 R8 收窄读取：请求内只 collect 一次；共同 T1 复用实际 Confirmation 所封存材料，确认及提交核对直接版本/水位；已发布制造基线保留原签署事实，读取比较真实 Current、来源摘要及签发注册水位，不重判历史签署资格。

- [API05](actual-pilot-05.json)／[日志](actual-pilot-05.log)：候选 `ik91a0if` 实际全链 **1 passed，217.14 秒**，覆盖创建、部分结果、完整修正、固定分母、Issue、同行读取、重放、尾部回滚及撤回拦截。
- 最终候选见 [candidate.json](candidate.json)，为 `yht8hdv0`；API05 之后补入私有父级共享守卫与两项纯回归，并移除测试对其他未交付 `tier_of` 改动的依赖。[最终 API06](actual-pilot-06.json)／[日志](actual-pilot-06.log)已通过 **1 passed，210.55 秒**，最终候选来源未变；两次成功是前后候选同类场景，不累加为两种验收覆盖。
- [后端纯检查03](pure-backend-03.json)／[日志](pure-backend-03-affected-pure.log)为前一候选 **585 passed**；[独立拼装检查02](delivery-pure-02.json)／[日志](delivery-pure-02.log)经根确认 **587 passed**，基于 HEAD＋48 个归属文件，排除四个共享文件的其他工作上下文。
- [后端静态03](static-backend-03.json)：Ruff、35 文件格式检查及测试收集通过。独立拼装01曾因测试借用未交付 `tier_of` 导入失败；已改为核对既有 T1 显式注册，不改变生产分级，保留[原失败证据](delivery-pure-01.json)。
- [前端01](web-01.json)：请求流、组件及 BFF 共 **131 项通过**；[完整类型检查](static-web-01.json)、[修正路径后的 lint](web-lint-01.json)、[生产构建01](production-build-01.json)通过。静态01内初次 lint 路径错误的失败记录保留。
- [复用范围核对](reused-web-and-schema-checks-02.json)：八个本交付前端输入逐字相同，迁移/metadata 输入未再改；其他工作的小Pai两个文件不在交付中，不据此宣称整体 UI 新一轮全验通过。
- 0778 已完成[升级02](migration-up-02.json) → [降级](migration-down-01.json) → [再升级](migration-reup-01.json)，当时尚无 Pilot 历史；[metadata02](metadata-02.json)归属模型差异为空、RLS 生效、无 Agent 直写和删除权限。既有循环外键警告保留；[首次迁移语法失败](migration-up-01.json)已更正，原日志未覆盖。

[API06 计时与 SQL](actual-pilot-06-metrics.json)仅为单组合成场景观测：创建 inputs 6.54 秒／174 SQL、预览 1.16 秒／88 SQL、保存 0.92 秒／62 SQL、首次固定回读 0.70 秒／42 SQL；不是 p95，正式性能验收依用户授权暂缓。

- [实际浏览器结果](browser-result.json)：页面共同预览时业务记录数为零；确认创建后追加部分观察，再追加完整修正，Root 保持一版、Current 到第三版、两份原始观察保留。固定投入 2，首遍良率 50%、最终合格率 100%，Issue 为同项目实际记录。
- 首次创建的响应中断尝试未命中实际带品类的 URL，[第一次记录](browser-fault-attempt-01.json)不算恢复覆盖。随后对真实结果提交执行 `route.fetch()`，断言后台返回 200 后中断响应；[第二次记录](browser-fault-attempt-02.log)及[提交后读取](browser-partial-response-lost.json)证明仅新增一条观察。刷新后需本人显式重放，[重放读取](browser-replayed-partial.json)与原记录、回执完全相同，Current 未增加。
- 已查看[创建预览](native-pilot-create-preview.png)、[响应恢复](native-pilot-response-recovery.png)、[修正预览](native-pilot-correction-preview.png)、[桌面亮色](native-pilot-complete-light.png)、[390px 暗色](native-pilot-complete-dark-mobile.png)；桌面与窄屏文档及面板均无横向溢出。页面使用构建过且逐字相同的八个归属前端文件，后端为最终 API06 候选。
- [收尾记录](cleanup.json)：专用浏览器已关闭、cookie 已清除、种子短期凭据已移除；本轮 API/Next 进程已结束，测试库及必要备份保留，其他预览未触碰。

S4 后续仍需整改接续、分别办理的放行/接收及受控人工或外部接收生效；S3 观察与独立评效按其真实条件续接。

S1–S4 均保持未验收；真实模型联验、签约服务商资料外发、生产启用等既有批准边界不变。唯一清单 M8 仅更新本轮可用能力、证据与余项。
