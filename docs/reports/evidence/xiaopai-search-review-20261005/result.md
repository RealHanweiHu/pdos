# 小Pai搜索能力核对

本轮确认用户修改的原工程搜索实现，没有修改业务代码或启用真实采集。结论：研究页面与讨论研究工具已有站内爬虫和本地检索能力，小Pai普通连续会话尚未调用这条搜索路径。

已有能力是“已登记来源 → 同站链接、RSS或sitemap → 公开页面快照 → 本地全文索引 → 标题、URL与片段”。检索可按租户、市场空间、产品线、语言和时间筛选；空索引时选择已配置的SearXNG。结果仍是线索，不能直接冒充被引用的业务事实。

## 已确认的缺口

1. `conversation_reply.py:326` 只调用回复模型，输入是历史和服务器当前参考资料；没有搜索决策、工具调用或搜索结果追加。`xiaopai_reply_v1.json` 也仍限定读取与回复。本轮搜索接线位于 `product_research.py:1149` 与 `discussion_research_tools.py:216`。
2. `research_search.py:184` 用 `plainto_tsquery` 要求分出的词同时匹配。实际合成资料中，“无刷电机 峰值压力”命中1篇，“帮我搜索无刷电机的峰值压力”返回无结果；会话搜索还需要提炼查询词。
3. `research_search.py:149` 的可用性只检查索引行存在，未排除已被替代的快照。本轮只保留一个已被替代文档后，仍选择本地检索且显示configured；查询才过滤该文档并返回无结果。
4. `research_search.py` 的类说明与协议名标为BM25，但实际排序为PostgreSQL `ts_rank`；该函数按匹配词频排名，当前实现没有BM25参数或其语料统计。应准确命名，或实现对应算法。[PostgreSQL排名说明](https://www.postgresql.org/docs/current/textsearch-controls.html#TEXTSEARCH-RANKING)

检索范围也须明确：`resolve_search_provider` 在存在本地文档时直接选择本地；本地无命中不会再调用SearXNG。它是本地优先的单一来源选择，尚未提供全网发现或查询时的混合回退。

## 验证与运行状态

本轮[67项基础测试](xiaopai-search-confirm-pure-20261005.log)、[21项数据库/API测试](xiaopai-search-confirm-api-20261005.log)、[1项补充复现](xiaopai-search-confirm-probe-20261005.log)及[25项前端测试](xiaopai-search-confirm-web-20261005.log)通过；合成网页覆盖爬取、robots、租约恢复、快照、搜索API、失效排除和原搜索行为。限制的实际结果见[复现输出](xiaopai-search-probe-20261005.json)，测试脚本与源码摘要见同目录及[核对摘要](review.json)。首次把含数据库fixture的11项fetch测试当纯测试运行，被显式TEST_DATABASE_URL护栏拒绝；随后在独立库中全部通过，没有回退`.env`。

从 `server/.env` 加载的本轮配置快照显示：爬虫关闭、订阅采集关闭、外部搜索端点未配置。这不证明其他进程的环境或数据库是否已有索引；本轮未读取存续业务库。3035仍是上一轮冻结的合成会话预览，不能作为新增搜索已生效的证据。

测试只用本轮新建的 `pdos-xiaopai-search-confirm-20261005-f1c9`、`127.0.0.1:62380/pdos_test` 与显式TEST_DATABASE_URL，验证后已清理。原64185/57450、受保护57432及其他环境均未做数据库操作。未调用真实模型、启用出站爬虫、部署或push。若要达到会话里“搜索后带来源回答”的能力，需将查询提炼、搜索、快照读取与引用回执接入普通会话，随后再验证真实来源与模型资格。
