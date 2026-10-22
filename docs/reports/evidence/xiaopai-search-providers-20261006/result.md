# 小Pai普通会话搜索接线 · 2026-10-06

用户授权普通会话接通Tavily、加入Firecrawl、SearXNG保底。本轮完成接线与配置；真实服务端点可用，当前机器的fake-IP DNS仍阻塞部分公开来源的应用内采集，因此不宣称真实会话整链验收完成。

普通会话现在复用研究搜索的有界链路：有效本地索引→Tavily→Firecrawl→SearXNG。某一服务无命中、限流、额度不足或连接失败时只尝试下一服务一次；停止/撤权或显式`ReachDeniedError`中止链路，回退不会放行被拒地址。失败不能当作“无结果”，回执与会话资料记录保留实际服务、尝试路径与覆盖缺口。

公开网页优先通过Firecrawl读取HTML；服务不可用时回到已有固定IP公开GET读取。本地快照直接复用。目标与返回的来源/最终URL继续检查，无法核对的地址变化改由原逐跳读取处理，私有地址拒绝仍保留。正文形成带来源版本、时间、digest及`untrusted_external`标记的快照后才能引用；不使用Firecrawl的actions或LLM清洗。顺带修复备用服务造成`partial`状态被误判为正文截断的问题，真正截断的正文提供快照续读位置。

Firecrawl密钥只写入被Git忽略的根目录`.env`；证据及候选源码未含任何已配置密钥。SearXNG采用固定镜像digest、`research`可选profile、只绑定`127.0.0.1:8888`的本地JSON端点，当前容器保持运行。普通URL采集没有开放非标准端口或内部地址；本地搜索端点为服务器配置的精确例外。空密钥模板下原PostgreSQL/MinIO启动配置仍可解析。

| 验证 | 最终结果 | 原始证据 |
| --- | --- | --- |
| 搜索服务、抓取政策、Firecrawl和普通会话 | 106项通过；其中13项普通会话，覆盖Tavily成功/失败、本地无命中、Firecrawl引用、长正文截断、停止、回放和来源失效 | [backend-final.log](backend-final.log) |
| 产品研究入口/权限 | 7项通过 | [research-entry-final.log](research-entry-final.log) |
| 前端受影响组件 | 3文件32项通过 | [frontend-tests.log](frontend-tests.log) |
| 后端规范/新增搜索核心类型 | 13份受影响文件ruff通过；3份搜索核心mypy通过 | [规范](backend-lint.log)、[类型](backend-types.log) |
| 前端类型/规范 | `tsc --noEmit`及两个受影响组件eslint通过 | [类型](frontend-types.log)、[规范](frontend-lint.log) |
| Compose空配置模板 | 默认服务与research profile均可解析 | [compose-template.log](compose-template.log) |
| 真实端点诊断 | Tavily搜索200、Firecrawl搜索200、Firecrawl已知公开页面正文200；不是应用整链或模型资格证明 | [live-provider-smoke.json](live-provider-smoke.json) |
| 本地SearXNG/配置 | JSON接口200、20条原始候选，2个上游引擎未响应；Tavily/Firecrawl配置已识别 | [local-search-smoke.json](local-search-smoke.json) |
| 当前API存活 | 原本地8000进程`/healthz`200；此检查不访问数据库 | [api-liveness.json](api-liveness.json) |

数据库测试仅复用已核对的独立`pdos-proposals-test-20261006-0424`，显式`TEST_DATABASE_URL`指向`127.0.0.1:63419/pdos_test`，实际head为`0427_category_reference_aliases`。初次误将共享此隔离库的测试并行运行，夹具相互清理产生401/来源漂移；随后串行复验。恢复时适配了新品类结构下的产品线夹具与统一成员权限测试，并修正旧SearXNG mock的导入位置；没有放宽应用权限。初始失败日志保留：[首次批量](chat-search-api.log)、[后续诊断](chat-search-final.log)、[快照诊断](local-receipt-diagnostic.log)。最终一次串行106项全通过，独立7项入口检查保留其覆盖，不拼接成全系统门禁。

测试库完成私有备份后恢复停止状态，容器与卷保留，SearXNG保持运行，详见[环境收尾](environment-closeout.json)。本轮没有对存续57432库运行repo测试或数据库操作，没有迁移、git push、真实模型资格授予、生产发布或改动N/P/Q验收勾选。

当前机器解析公开来源时仍返回保留地址，现有地址守卫按合同拒绝候选/读取；真实端点诊断的原始候选不能当作应用内可引用资料。恢复条件为本机网络提供真实、可核对的公开DNS地址后，复核登录后的真实搜索→快照→模型引用链。未修改系统代理/DNS配置或允许fake-IP进入公开采集。完整会话模块的严格mypy历史问题不在本轮3份核心类型覆盖内；没有重跑全系统构建、迁移往返、正式红队或人工Exit。

候选范围与SHA-256见[源码清单](source-manifest.json)，不含共享工作区其他修改及私有`.env`。实现依据为[Firecrawl搜索API](https://docs.firecrawl.dev/api-reference/endpoint/search)、[Firecrawl正文API](https://docs.firecrawl.dev/api-reference/endpoint/scrape)、[SearXNG Docker部署](https://docs.searxng.org/admin/installation-docker)。
