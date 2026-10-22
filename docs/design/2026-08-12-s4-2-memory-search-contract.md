# S4-2 Memory + 向量检索 v1 契约

日期：2026-08-12  
状态：冻结，作为 canonical S4-2 的实现合同

## 1. 不可变信任边界

- Memory 状态机固定为 `draft → verified → archived`，不允许逆向迁移。
- `draft` 来自人工录入、已关闭 CAPA 或已接受并应用的 `knowledge_draft` Finding；它不是组织事实。
- 只有 `verified` 可进入 Knowledge Search、Agent `search_memory` 与 `/ai/chat` 引用上下文。
- `archived` 只保留审计与历史查询，不进入检索或 AI context。
- 创建草稿与验证必须由不同用户完成；Owner/Admin 不得跳过该四眼规则。
- Memory 全部项目级绑定；tenant/project/status 由服务端身份与 URL 上下文绑定，模型参数、请求正文和引用内容都不作为政策事实。

## 2. 数据模型

`cehub_memory.memories`：

- tenant/project 复合边界；title/content/applicability/tags；状态与创建/验证/归档人时间；
- 可选 `source_finding_id` 或 `source_ncr_id`，两者互斥；来源必须与 Memory 属于同一 tenant/project；
- `source_refs` 只保存有界、可验证的实体/事件引用，不保存对象存储键或原文；
- `content_sha256` 绑定 title/content/applicability/tags，verified 后内容不可原地修改。

`cehub_memory.memory_embeddings`：

- 每条 embedding 记录 provider/model/dimensions/content_sha256/向量/创建时间；
- 向量列使用 pgvector；API、Event、Audit、日志与前端均不得返回原始向量；
- 同一 Memory 可保留多个模型版本，检索只使用当前配置模型且 hash 与当前内容一致的向量；模型切换后须显式 re-embed，旧向量只作审计留存。

## 3. 人工动作与状态门禁

1. 内部成员可创建/编辑 draft；已关闭 NCR 可被人工整理为 draft。
2. 已接受的 `knowledge_draft` Finding 经第二个人工 Apply 创建 draft Memory，并把 Finding 的 applied entity 指向该 Memory。
3. 具 `memory.verify` 权限且不是草稿创建者的内部用户请求验证；服务端先对冻结内容调用 embedding API，再在单事务中复核 hash、写 embedding、迁移为 verified、写 Event+Audit。
4. embedding 不可用、响应非法、维度不符或内容并发变化时 fail-close，Memory 保持 draft。
5. verified 只能 archive；archive 后所有检索入口立即不可见。重嵌入不改变业务状态。

## 4. Embedding 协议

- v1 只支持 OpenAI-compatible `POST /embeddings` 形态，provider/model/base URL/key/dimensions 从服务端私有配置读取。
- provider client 必须执行 HTTPS/localhost 约束、响应形状与有限数值校验、维度精确校验、超时与有界输入；凭据及全文不得写日志。
- 业务表保存 provider/model/dimensions，避免把“当前模型”伪装成历史政策事实。
- 无配置时列表/历史仍可用，验证、重嵌入与语义搜索返回明确不可用，不降级为“零结果”。

## 5. API 与 RBAC

- `GET/POST /api/projects/{project_id}/memories`
- `PATCH /api/projects/{project_id}/memories/{memory_id}`（draft only）
- `POST /api/projects/{project_id}/memories/from-ncr/{ncr_id}`
- `POST /api/projects/{project_id}/memories/{memory_id}/verify`
- `POST /api/projects/{project_id}/memories/{memory_id}/archive`
- `POST /api/projects/{project_id}/memories/{memory_id}/reembed`
- `POST /api/knowledge/search`（verified only）

权限：Owner/Admin 拥有全部 Memory 动作；Project Manager/Quality 可 view/draft/verify/archive；Engineer 可 view/draft；Supplier/Customer 零 Memory 面。对象权限仍要求项目成员，Owner/Admin 沿用既有租户级治理语义。四眼由服务层与数据库约束双重执行。

## 6. 检索与引用合同

- 查询文本 1–500 字节边界，limit 1–20；服务端生成 query embedding。
- SQL 同时过滤 tenant、project、`status='verified'`、当前 provider/model/dimensions 与 content hash，再用 cosine distance 排序。
- Knowledge Search 返回 Memory 安全摘要、相似度、来源引用与站内 href，不返回向量、原始文档、对象存储键或其他项目存在性。
- Agent `search_memory` 只读当前 run 绑定项目的 verified projection；越界 project_id 继续显式拒绝。
- `/ai/chat` 将命中的 verified Memory 作为可点击 citation；模型引用不存在/越界/已归档 Memory 时整次回答 fail-close 为 insufficient evidence。

## 7. 事件与验收

新增版本化事件：`MEMORY_DRAFT_CREATED`、`MEMORY_VERIFIED`、`MEMORY_ARCHIVED`、`MEMORY_EMBEDDED`。所有业务写与 Audit 同事务。

硬验收：

- draft/archived 在 Search、Agent 与 Chat 三入口均为 0；verified 可命中且引用可点击；
- tenant/project/status/model/hash 五层过滤叠加正确；跨租户/跨项目不泄露存在性；
- embedding 失败、维度异常、内容并发变化均不产生 verified Memory；
- `pdos_agent` 对 Memory 业务表零写，只能读取 server-bound verified projection；
- 一条已关闭 CAPA 转为 draft、经另一人验证、被 `/ai/chat` 引用命中。
