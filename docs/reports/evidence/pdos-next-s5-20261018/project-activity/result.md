# 项目动态与独立履行消费 · 本地闭环

候选以 `8fbb6dd6494249f9aff7c6c03377ccdcd41fa476` 为基线，精确归属源码在 `/private/tmp/pdos-s5-activity-w4yjh0dj` 拼装。API、BFF、Project Now/旧工作区接线及本清单只提取本轮增量；同工作树的 UI 会话改动没有进入本候选。S1/S5 正式验收、P13 性能暂缓和 S3 一天观察保持。

已实现：项目动态从 55 个明确来源（51 个模型、81 个注册操作）读取不可变事实和真实 Receipt/主 Outbox，显示固定版本、真实 actor/requester、登记/实际发生时钟和原时区、来源及任务引用。G0 的 project.created 旁事件与样件子事实不重复成第二条活动；配置只按本项目实际固定引用关联。普通只读 RR/RLS、逐源私有/上游限制保留；0792 追加 app 专用 SECURITY INVOKER 布尔读取证明，未使用 owner 内部宽读。游标固定本人/范围和水位，当前锚点不可读即拒绝。工作区链接准确指向办理入口，不冒充历史详情；未读取 Run 对话或结果正文。

已实现：当前精确承诺 fulfilled 持久停止相对规则，不依赖 Task completed 或已知日期；退回继续。Category 锁内实际 admission 再核源版本、原时钟和履行，旧 queued 受抑制；已受理 Run 历史保留，新的承诺版本不自动复活已停止授权。显式 Task 条件、预算/冷却/权限/过期及真实 Temporal 架构保留。本轮测试只产生合成受控事实与 Run 元数据，模型调用为零。

验证按影响集中执行：

- [26 项活动/游标纯检查](backend-projection-pure.log)及[48 项规则纯检查](backend-automation-pure.log)；[56 项前端检查](frontend-tests.log)、[类型](frontend-types.log)、[相关 lint](frontend-lint.log)、[生产构建](production-build-network-allowed.log)通过。初次 sandbox 构建因公开字体 DNS 失败；允许下载 Geist 后构建通过，无业务资料出站。
- [4 项实际规则 PG/HTTP](pg-automation-diagnostic.json)通过，含未知日期/Task 等待、不同接收者、退回、续版旧队列、未 tick 的 SQL 受理守卫、持久停止与原 Run 历史。两项明确的 synthetic_host_queue_fixture 恢复项复制实际已解析 origin/due，仅覆盖受理恢复，不冒充真实跨委托人 Outbox 级联。
- [Build 实物链](pg-activity-repaired.json)通过；[Work/G0/Plan 与发布/两专业决定](pg-activity-final.json)通过。实际 51 来源和共同表行 hash 在每次 GET 前后相同；读取 SQL 未加载完整 body/command/source_basis/原文。分别覆盖同产品未关联配置排除、固定时钟、幂等、游标跨 scope/本人拒绝、后写不漂移水位及失权。最后仅办理入口提示文案变化由纯检查和最终浏览器覆盖，不宣称一次整仓或正式阶段验收。
- [实际浏览器](browser-read-check.json)：20→25→20 条，同游标503重试、刷新先隐藏旧页，3 次实际读取零非GET；1440亮色宽1152、320暗色宽288无横向溢出。[最终读回](browser-final-read.json)核真实三类任务实际时间与 Asia/Shanghai、准确工作区链接。截图：[桌面](desktop-light.png)、[手机](mobile-dark.png)。接口事实为真实合成记录；仅一次分页503为客户端故障注入，不冒充服务器权限验证。
- [0791/0792 升降升](migration.json)、[实际属主/权限/冻结函数](metadata.json)通过；51 来源强制RLS、Agent零直接业务DML，新活动证明仅app可执行且为INVOKER。既有来源证明内部的SECDEF仍是普通owner。数据库仅 `127.0.0.1:64245/pdos_test`，marker `f9048729-3f2a-4494-af75-56e1db7d743d`。

失败与界限保留：初版关联谓词漏了外层 Project 相关性，未跑新业务病例即撤回重装；G0 NULL 版本造成 psycopg 参数无类型，已修且实际链通过。测试原先错误地把 G0 全部 Outbox 当成唯一主事件、使用了错误发布操作名，现按实际协议核主事件。首轮旧承诺续版曾一次23514；未改业务/日期，窄诊断及同批四例后续均通过，仍未定位，不能称已修复。首轮样件分配409确认失败也未改期限/权限/业务逻辑，加入原确认的只读诊断后复验通过，原因未定位。见原 [规则失败](pg-automation.json)、[活动初次](pg-activity.json)与[中间复验](pg-activity-repaired.json)，不隐藏失败。浏览器原上传合成来源的扫描已失效，保持原状态，改为通过真实人工命令新登记明确合成说明资料；未续期或绕过安全扫描。

剩余：AgentRun 没有可靠 project_id，本轮只列真实项目领域回执实际绑定的 agent_run_id，不把同产品私人对话和只读运行推入项目。显式项目绑定/完整运行事件、注意项与完整个人分诊、知识/爬坡反馈、其他投影及正式出口继续。S1 真实模型/协议/出站授权仍缺，未重复探测；无真实资格、真实业务外发、push 或部署。专属预览与短期合成登录的收尾见 cleanup.json，原数据库、备份、共用Temporal保留。
