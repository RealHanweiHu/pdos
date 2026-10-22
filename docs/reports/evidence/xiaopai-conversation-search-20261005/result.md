# 小Pai普通会话搜索 · 2026-10-05

用户明确允许像 Codex、Claude 一样在普通会话搜索。此检查点覆盖原 server/web；pdos-next 与其他未提交工作不属于本次变更范围。

普通交流直接流式回复；需要公开资料时模型在同一回复合同中选择搜索关键词或用户提供的公开页面 URL，服务端使用当前租户/会话范围检索。每轮最多一次检索、两份正文读取、两次模型调用；读取后才生成结论。本地命中读取现有不可变快照，公开命中经原 Reach 防护采集快照，搜索摘要不能作为引用。最终回复保留检索记录与来源链接，同一消息重复请求复用原运行。

工具意图、派发、观察、原模型选择、权限、租约和累计预算绑定；新 0423 数据库守卫只扩展普通会话的两项工具，并保留原专业工具条件。已保存的研究回执不可改写；来源替代/停用或权限变化使旧回复失效。停止与失败不能冒充搜索完成或没有事实。

## 检查点证据

| 范围 | 结果 |
| --- | --- |
| 后端稳定候选 | [55项通过](xiaopai-chat-search-final-backend.log)：普通会话、真实预算/租约端口、工具回执、本地索引、公开采集与原研究API；模型/网络为合成响应。 |
| 外部回退与数量上限 | [3项通过](xiaopai-chat-search-fallback.log)，含2项公开读取复核；本地无命中回退已配置端点，超量线索最多读取两页。 |
| 最终停止增量 | [4项通过](xiaopai-chat-search-final-stop.log)，含3项原能力复核；准备阶段收到停止后零模型/工具派发，检索中停止不读取页面或启动第二次模型调用。三轮共57项不同后端案例；最后增量按影响验证，没有宣称全系统联合门禁。 |
| 前端/BFF | 最终[46项通过](xiaopai-chat-search-final-web.log)：搜索进度、资料记录、引用、流式/原请求恢复、权限撤回、普通与专业入口兼容，以及非JSON错误的可理解提示。 |
| 类型、规范与构建 | [TypeScript](xiaopai-chat-search-typecheck.log)、[ESLint](xiaopai-chat-search-web-lint.log)、[Ruff](xiaopai-chat-search-ruff.log)、[冻结web生产构建](xiaopai-chat-search-build.log)通过。 |
| 0423迁移 | [迁移历史1项通过](xiaopai-chat-search-migration-history.log)；[0423→0422→0423](xiaopai-chat-search-migration.json)保留3份快照、守卫逐字恢复，pdos_agent 对所查会话/来源/快照表无直接INSERT权限。 |
| 浏览器 | [记录](browser-checks.json)、[桌面暗](desktop-dark.png)/[亮](desktop-light.png)、[320px手机](mobile-320.png)/[展开资料与停止](mobile-320-expanded-stopped.png)。实际登录后普通提问完成搜索与引用，刷新恢复，原请求继续与停止通过；手机文档宽度320px无横向溢出。 |

源码候选与范围见[candidate.json](candidate.json)。浏览器模型、原文与资格仅为该合成进程的测试替身，没有写入golden可信根。正常搜索回复持久化2次模型调用记录、2份工具意图/派发/观察及1个引用；在途停止保留未知用量的保守预算状态，不能当作零消耗。

## 环境与剩余条件

repo测试仅使用新建独立PG16/pgvector `127.0.0.1:49458/pdos_test` 和最终停止复核的 `54571/pdos_test`，显式TEST_DATABASE_URL；两个容器已清理，测试快照备份 `/tmp/xiaopai-search-tested-a72b.dump` 保留。未使用存续57432或`.env`回退。

原64185合成预览已备份后升级到0423，原会话保留；只新增合成研究空间与公开规格样本。备份 `/tmp/xiaopai-preview-before-search-a72b.dump`；[预览3035](http://127.0.0.1:3035/ask)/API8899继续保留，前端冻结目录 `/tmp/pdos-xiaopai-search-a72b/web`。账号仍为 `beepump / owner`，仅此合成环境密码为 `correct horse battery staple`。

真实全网搜索尚未配置 `PDOS_RESEARCH_SEARCH_ENDPOINT`；真实运行需租户模型资格、有效计量发布与budgeted通道/租约配置，工具不会绕过这些原守卫。缺条件只阻塞对应实测，不阻塞已完成的本地实现。正式目标环境升级、真实搜索/模型质量与时延、golden-case及人工出口仍待对应条件。

当前全网搜索仍依赖已配置的 SearXNG 端点；本地索引来自有效爬取快照。真实模型质量、真实全网检索与 golden-case 资格不由合成验证授予。未修改 golden 文件、业务生产数据、存续57432库，未 push 或部署。
