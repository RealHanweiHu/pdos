# 记忆检索两处余项：D300 情景向量联调与切换、D482 余项 ① 对象标题（2026-11-14）

用户 2026-11-13 要求并行完成记忆系统余项，11-14 说“继续完成其他没有完成的”。本会话做 D300 和 D482 余项 ①。代码在分支 `claude/memory-retrieval-gaps-7ba7bc`，本地提交 `69f81d00`，未推送。

测试环境：本工作区自建的独立临时库（`tools/local_environment.py create`，容器 `pdos-next-test-20261002-f0d55c91`，127.0.0.1:52354/`pdos_test`，状态文件 `.local/runtime.json`），独立检查点库（`tools/workflow_environment.py create-db`，127.0.0.1:62924），原生 Temporal 开发服务（主检出 `.local/tools/temporal` 只读使用，本工作区自己的 SQLite 文件，127.0.0.1:62968）。显式 `TEST_DATABASE_URL`，没有读 `.env`，没有用 57105。嵌入服务全部是进程内的合成服务商，没有任何出站。

## 结果总览

| 项 | 做了什么 | 验证 |
|---|---|---|
| D482 余项 ① | 情景索引加第三种行 `object`：运行关注的具体对象（读过的资料、钉住的来源）的标题；范围对象的标题不收 | 带库测试新增 3 例，改 3 例 |
| D300 第 1 步 | 情景向量后台流程在真实本地 Temporal 上跑通；实际运行里 `memory.search` 关键词与向量融合 | 新增 1 例 Temporal 联调测试 |
| D300 第 2 步 | `memory.search` 有了自己的查询嵌入端口，默认接线；数据库守卫原来只认 `assistant.search`，改为也认 `memory.search` | 同上（不手工注入端口） |
| D300 第 3 步 | 本机没有已配置的真实嵌入运行环境，只做到合成服务商 | 恢复条件见下 |
| D300 第 4 步 | 换模型：新版本建好前继续用旧向量，建好后切换；旧版本停用后不再派发、不再查询 | 带库测试新增 2 例 |

回归：`tests/agent/memory` 93 通过、12 跳过（跳过的是默认不跑的真实模型题），含两条 Temporal 联调；相邻的企业检索查询嵌入（含其 Temporal 整链）、自动化摘要、会话依赖清单、来源工作测试 138 通过。迁移 `s0_0960` 在独立库上降级、升级各两次通过。更大范围的回归没有跑。

## D482 余项 ①：按对象标题能找到

改动：

- `server/pdos_next/agent/memory/index.py`：每条情景写三行。新的 `object` 行收运行关注的具体对象的标题，按种类解析：`artifact`（运行读过的资料）和 `source`（钉住的来源）都经企业检索的来源目录读取，目录在本人身份和行级权限下执行，读不到的（撤权、撤回、删除）查不到，也就不收。标题按索引时的当前版本取。
- 范围对象（品类、产品、提案、项目）的标题不收，原因同 D482：同范围的情景都带它，又没有按稀有度加权，问题里一提范围名就会把整个范围搜出来。
- 分成独立一行而不是并进 `answer` 行，理由：① 卡片能分清命中的是回答还是对象标题；② 已索引的旧情景补一行即可，不用改已写入的只追加行；③ 会话列表搜索照旧只查 `episode` 行。
- `server/pdos_next/agent/memory/recall.py`：三种行一起打分；`matched_in` 新增 `object_title`。卡片只说明命中了对象标题，不返回标题文字。命中后照旧逐条复核。
- 补索引：迁移 `s0_0960` 把“待索引”改为三种行缺任何一种；调度键改为按最新的行种类，以前索引过的情景会再派发一次，只补 `object` 行。

测试（`server/tests/agent/memory/test_memory_recall_pg.py`）：

- `test_a_run_is_found_by_the_title_of_the_material_it_read`（已索引、未索引两条路径）：按资料标题能找到，`matched_in == ["object_title"]`；同范围其他情景的 `object` 行为空；卡片里没有标题原文；会话列表搜索按标题搜不到。
- `test_an_unreadable_object_title_is_not_indexed_and_a_revoked_one_hides_the_episode`：资料在索引前撤回，标题不收（`object` 行为空）；资料在索引后撤回，行里还有标题，但 `memory.search` 的逐条复核把情景挡住，结果为空且不提示存在。
- `test_an_episode_indexed_before_the_answer_row_existed_is_pending_until_it_has_one` 改为两种旧情况：只有原话行的、有原话和回答两行的，都算待索引，补齐后不再待索引。

测试里的“撤权”用的是资料撤回（`status='withdrawn'`）。原因：同事用受众授权分享的资料会让读它的运行成为私有上下文，按 P93 本来就不会被非私有运行召回，测不出复核。`source` 种类走同一段代码，没有单独的测试。

## D300：情景向量

### 第 1 步：真实本地 Temporal 联调

`server/tests/agent/memory/test_memory_vectors_temporal_pg.py`，实测记录 [temporal-measured.jsonl](temporal-measured.jsonl)：

- 后台：派发角色只拿到情景 UUID，启动已注册的 `MemoryEpisodeVectors`，worker 的 `embed_memory_episodes` 活动以本人身份嵌入、写向量和回执。回执：`completed`，服务商 `embedding.invalid`（合成），数据类别 `["owner_session"]`，10 token，20 微美元。再次派发为 0。
- Workflow 历史 11 个事件、7,834 字节；解码后的载荷里有情景 UUID，没有本人原话、没有向量、没有凭据。
- 实际运行：HTTP → Temporal → 小Pai 主图，合成模型调用 `memory.search`，查询词与原话没有任何共同关键词，只能靠向量找到。结果 `channels: ["keyword","vector"]`，`semantic.status: queried`，覆盖 `complete`。派生的查询嵌入调用 1 次、`completed`、10 token，绑定到这次 `memory.search` 调用。运行历史 47 个事件，里面没有查询向量和凭据。合成服务商共被调用 2 次（后台 1 批、查询 1 次）。

关键词索引的 Temporal 联调（`test_memory_index_temporal_pg.py`）同时重跑：每条情景三行，历史 11 个事件、7,531 字节，没有本人原话。

### 第 2 步：“勾选了就能用”需要的接线

原状：`memory.search` 借用企业检索的查询嵌入端口 `RuntimePorts.embedding_query`，生产 `runtime_ports()` 从不设置它，所以勾选“本人会话记录”后一直是“仅关键词”。

改动：

- `server/pdos_next/agent/kernel/bootstrap.py`：`Bootstrap.memory_query_embedding` 给 `memory.search` 单独建一个查询嵌入端口，来源是可信宿主的独立嵌入凭据（`configured_ports`，与 worker 的后台嵌入同一来源）。宿主能绑定独立嵌入连接时就接上。`assistant.search` 的生产默认不变，仍是仅关键词。测试可以用 `RuntimePorts.memory_embedding` 传入自己的端口。
- `server/pdos_next/agent/enterprise_search/embedding_query.py`：`QueryEmbedding` 可指定自己的冻结快照键；`QueryPorts.run_selector` 让选择器在运行自己的事务里读服务器事实。记忆用 `memory_query_profile`，企业检索仍用 `embedding_query_profile`，同一运行的两个使用方互不共用向量空间。
- `server/pdos_next/agent/memory/tool.py`：查询用的空间是本人当前的服务版本（见第 4 步），在本运行第一次 `memory.search` 时冻结。
- 数据库：`kernel_embedding_query_guard`（`s0_0838`）原来只接受 `assistant.search` 作为查询嵌入的父调用，实际运行第一次跑就被它挡下（Python 侧的 `PARENT_TOOLS` 早已列了 `memory.search`）。`s0_0960` 改为两者都接受，模型请求名和输入摘要按父调用自己的工具核对，冻结快照按父调用选键。守卫其余的证明全部保留：实际模型请求、输入摘要、取消纪元、有效的独立配置、预算绑定。**这是一处安全守卫的放宽，请复核。**

接上之后，查询真正出站还要同时满足：有效的嵌入配置勾选了“本人会话记录”（管理员确认），本人在该空间里有向量，独立嵌入凭据和计价可用，P26 允许本运行带着的数据类别。缺任何一项，结果都标“仅关键词”并写明原因。

### 第 3 步：真实嵌入服务

本机没有已配置的真实嵌入运行环境：`.env.example` 没有嵌入相关项；主检出 `.local/` 下的运行元数据里没有嵌入连接；以往真实评测（[pdos-next-real-eval-20261101](../pdos-next-real-eval-20261101/result.md)）也写明“真实 embedding 出站仍未启用”。所以只做到合成服务商为止，没有真实回执、用量和召回对比。上面的数字只证明注册链路接通，不代表检索质量。

恢复条件（登记为 D550）：① 租户运行配置（`PDOS_TENANT_RUNTIME_CONFIG`）里有一个 OpenAI 兼容的嵌入连接，凭据经本地 KMS 绑定；② 该模型的计价卡；③ 你授权把合成的本人原话和查询词发给这个服务商。满足后用本测试的同一流程跑一次，记录回执、用量，并做“仅关键词”对“融合”的召回对比。

### 第 4 步：换嵌入模型时的重嵌与切换（设计 §14.9）

做法：换模型时，管理员在旧配置旁边新建一个也勾选“本人会话记录”的配置，两者同时有效。

- 派发：`memory_pending_vector_references` 改为列出所有有效版本（`s0_0960`），所以重嵌期间新写入的情景两套都写。
- 查询（`vectors.serving`）：新版本保存时本人已有的、符合条件的情景都嵌好以后，新版本才算建好。最新的已建好版本优先；都没建好时，用本人向量最多的那个版本，并标 `coverage: partial`。一次查询只用一套空间，不把两套分数放进同一次融合。关键词检索始终同时进行，所以切换期间不会出现伪零结果。
- 本运行内：空间在第一次 `memory.search` 时冻结。运行中途这套空间被停用，就返回 `query_profile_mismatch`，这次只做关键词检索，不在同一运行里换空间。
- 旧向量退出：旧配置停用或被新修订取代后，不再派发、不再查询。行本身不删：向量表有只追加触发器，物理清理要改它，而 `s0_0940`（会话删除）正在把这个触发器换成删除守卫，清理规则应在集成时并进去（D551）。

测试（`server/tests/agent/memory/test_memory_vectors_pg.py`）：

- `test_old_vectors_serve_until_the_new_model_has_caught_up_then_the_search_switches`：旧空间完整 → 新配置保存（新空间空，仍用旧的，检索有结果）→ 新情景两套都派发 → 新空间建了一半仍用旧的 → 建完切到新的，检索有结果 → 停用旧配置后只派发和查询新的；没来得及嵌入的新情景靠关键词仍能找到。
- `test_a_run_keeps_the_space_it_started_with_and_says_when_that_space_went_away`：没有实际 `memory.search` 调用时不嵌入；冻结快照用的是记忆自己的键；运行中旧空间被停用、新空间出现时，返回 `query_profile_mismatch`，结果仍有关键词命中。

与设计 §14.9 的差别：设计写的是“重嵌完成且检索评测通过后，查询切到新配置”。这里建好即切换，没有评测关口（D552 待你定）。

## 没有做

- 真实嵌入服务联调（D550）。
- 旧向量的物理清理（D551）。
- 切换前的检索评测关口（D552）。
- `source` 种类对象标题的单独测试。
- 把回答摘要或对象标题也送去嵌入：这是新的出站内容，不在本任务内（仍是 D482 余项 ②）。
- 工具定义和提示词没有改。

## 集成须知

- 迁移 `s0_0960` 是占位号，接 `s0_0888`，集成时按真实 head 重排（revision、down_revision、快照文件名一起改）。它按锚点替换了三段已有的函数体：`s0_0888` 的待索引函数、`s0_0866` 的待向量化函数、`s0_0838` 的查询嵌入守卫。别的分支若也改这三处，集成时要合并函数体。
- 共用文件里的改动：`kernel/bootstrap.py`（`RuntimePorts.memory_embedding`、`Bootstrap.memory_query_embedding`、`memory.search` 的接线一行）、`enterprise_search/embedding_query.py`（快照键参数、`run_selector`）、`memory/tool.py`（`semantic_query`）。没有碰 `graph.py`、`domain_adapter.py`、提示词和工具定义。
