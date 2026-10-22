# 研究搜索爬虫化 + 本地索引（类 ChatGPT 自建索引路线）· 2026-10-04 检查点

依据用户指令"我也做成爬虫的形式。可以参考last30days, agent reach. 以及chatgpt, claude等自建索引"及批准的实施计划执行。本文件为本闭环的必要证据摘要；原始输出见下方命令记录。

## 交付范围（主工程 server/app + web，pdos-next 未动）

| 组件 | 位置 | 说明 |
|---|---|---|
| 迁移 0420–0422 | `server/migrations/versions/042{0,1,2}_*.py` | `research_crawl_frontier`（含 uq tenant+source+url_key、租约/退避约束）、`research_crawl_runs`（running 部分唯一索引）、`research_robots_cache`、`research_index_documents`（PK tenant+snapshot，doc_tsv tsvector + GIN）。head 0419→0422 单调分配。 |
| 页面提取/robots/分词 | `server/app/domain/research_index.py` | stdlib HTMLParser 提 title/正文/链接（去 script/style）；RSS/Atom/sitemap loc 解析；robots 组解析（最长前缀胜、crawl-delay、sitemap）；jieba 离线分词喂 `to_tsvector('simple')`；`ResearchIndexService.project/rebuild` 派生投影，可整体重建。 |
| 本地检索 provider | `server/app/ai/research_search.py` | `LocalIndexSearchProvider`（key=local-index, local-bm25-v1）：BM25（plainto_tsquery+ts_rank），tenant/space/line(time_range/language) 过滤，superseded 快照退出，命中仍逐条过 `ReachPolicy` 防御复检，`SearchResult` 合同与 SearXNG 一致，fail-closed（空索引=not_configured≠no_results）。 |
| provider 选择 | `server/app/domain/research_search.py::resolve_search_provider` | 本地索引可用优先，否则 SearXNG（若配置），否则 fail-closed；provider_key 如实入 `research_searches`。 |
| 爬虫 worker | `server/app/domain/research_crawler.py` + `scripts/run_research_crawler.py` | 订阅+来源基址种子化→同 origin 链接/sitemap/feed 发现（depth 上限、frontier 上限）→ `collect_page` 同链采集（untrusted_external 快照、digest 去重）→ 投影入索引。租约 90s、过期恢复 timed_out、5 次退避隔离、per-host 每小时 12 次、robots.txt 24h 缓存并对 PDOS-Research 生效；`_audit_snapshot` 对 frontier 脱敏 lease_token。env 门 `PDOS_RESEARCH_CRAWLER_ENABLED`（默认关）。 |
| 重建脚本 | `scripts/rebuild_research_index.py` | 全量删除重投影，幂等。 |
| AI 工具路径 | `app/ai/discussion_research_tools.py` | search 分支改用同一 resolver（租户级）；工具名/合同/预算不变。 |
| gb18030 回退 | `app/ai/reach_transport.py::decode_body` | 声明编码→utf-8→gb18030 严格解码；失败仍 fail-closed。 |
| 前端 | `research-collection.tsx`/`research-search.tsx` | `/sources` 新增 `search_provider` 透传，检索来源徽标（本地索引=查询不出站说明）；optional prop 不破坏既有组件测试。 |
| 唯一新依赖 | `jieba>=0.42,<1`（纯 Python、离线、MIT） | 非栈级变更。 |

## 验证（独立临时库 127.0.0.1:57450/pdos_test，显式 TEST_DATABASE_URL）

- 纯测试 11 项：`tests/test_research_text_extraction.py`（解码回退/提取/robots/分词/feed/sitemap）。
- 集成 3 项：`tests/test_research_crawl_local_index.py`——①种子→爬取→快照→索引→本地搜索 API（provider_key=local-index、命中/片段、/sources 徽标、supersede 后退出检索）；②robots 禁止路径 skip 且缓存复用（robots 仅取 1 次）；③租约中断→过期恢复 timed_out→退避→完成。
- 既有回归 75 项全过：reach policy/fetch、search provider、订阅恢复、产品研究入口 API。
- 迁移往返：0422→0419→0422 通过；新表 schema 与 alembic 一致。
- 静态：ruff 全部改动文件 0 错；mypy 新增/改动核心文件 0 错（其余为本轮未改文件的既有基线）；tsc/eslint 前端受影响文件 0 错；组件测试 25 项过。

## 本轮修复的实现缺陷（测试暴露）

1. frontier 租约过期行（status=running）永远不会被候选查询选中——恢复查询与复查逻辑已修。
2. `INSERT..ON CONFLICT DO NOTHING` 的 rowcount=-1 导致 links_added 负值违反约束——改用 `RETURNING` 计数。
3. 审计敏感键扫描拒绝 frontier 的 `lease_token` 字段——`_audit_snapshot` 增加 kind 分支只落布尔状态。

## 边界（未授予/未宣称）

- 搜索层零凭据、零第三方出站；不接 Exa/Brave/Tavily/Jina Reader（agent-reach 的出站路径仅作后备不启用）；本地索引查询不出站。
- 发现范围仅限已登记来源 origin 站内（订阅+基址种子）；robots.txt 为新增遵守义务；真实外网整链、真实搜索资格仍属 N1-02 原验收条件，合成通过不关闭原 N/P/Q 勾选。
- 爬虫 worker 错误路径零 LLM；快照不可变触发器（0054）未触碰；向量检索留二期。
- 测试容器 `pdos-crawl-test-20261004`（127.0.0.1:57450）本轮保留供复验，未触碰 57432/57433/57434/62513 等存续环境；后续检查点统一收尾。

## 复现命令

```bash
# server/
TEST_DATABASE_URL='postgresql://postgres:***@127.0.0.1:57450/pdos_test' \
  uv run pytest tests/test_research_text_extraction.py tests/test_research_crawl_local_index.py \
  tests/test_agent_reach_policy.py tests/test_agent_reach_fetch.py tests/test_research_search_provider.py \
  tests/test_research_subscription_recovery_api.py tests/test_product_research_entry_api.py -q
# web/
npx vitest run src/components/product-work/research-search.test.tsx src/components/product-work/research-collection.test.tsx
```

## 2026-10-05 追加：Tavily 网络搜索接入（用户提供密钥并明确授权）

- `TavilySearchProvider`（key=tavily, search-tavily-v1）：固定 host `api.tavily.com` 的 httpx2 POST，密钥走 `Authorization: Bearer` 头（不落 URL/日志），命中仍逐条过 ReachPolicy；401/403/429/5xx 与无效 JSON 均保持服务失败语义（非零命中）。
- 链序：本地索引 → Tavily → SearXNG → fail-closed；`/sources` 的 `search_available/search_provider` 与前端徽标同步；AI search 工具同一 resolver，工具名不变。
- 密钥仅存根目录 `.env`（gitignore 已核），`.env.example` 留空键；查询词会出站到 api.tavily.com（本次用户授权的边界变化）。
- 测试：`tests/test_research_search_tavily.py` 9 项纯测（含链序/密钥空/过滤/失败语义）；共享 fixture 清空搜索凭据防测试进程携带真实 key 出站；`test_product_research_entry_api` 桩补新字段。搜索相关回归 102 项全过；ruff/mypy 0 错。
- 真实冒烟：加载 .env 密钥调用成功（HTTP 200，返回 12 候选）；本机因代理 fake-ip（所有域名解析至 198.18.0.0/15）命中全被 SSRF 防护拒绝——防护按设计工作，非集成缺陷；无 fake-ip 的环境不受影响。
- 提醒：该密钥曾在聊天中出现，建议在 Tavily 控制台轮换。
