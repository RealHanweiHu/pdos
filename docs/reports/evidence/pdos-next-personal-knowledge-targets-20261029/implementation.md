# F 个人回答目标品类与补充请求恢复（冻结副本）

已在本副本完成实现与适当静态/纯测试；**没有改 live、连接 PostgreSQL、执行迁移、调用真实模型/embedding/外发**。主代理负责实际集成、真实 head 分配及公共 PG/页面验证。

## 集成内容

`integration-manifest.json` 精确列出 13 个文件；`smallpatch.diff` 相对于 `base-files/` 生成。不复制整个副本，不覆盖主代理已修正的 `tests/enterprise_search/test_assistant_pg.py`、`tests/knowledge_pg/test_assistant_knowledge.py`、`agent_kernel/run_feedback.py` 或生命周期 PG 文件。前述原生 helper 的本副本副本仅供测试，不是交付文件。

个人已完成回答现在也显示知识操作。用户必须从真实 `v1/categories` 读集明确选择目标品类；即使只有一项也不会自动选择。目标路由只提供选择，服务端 `category_scope(write=True)` 核对实际写权；`capture` 仍读取原 Run、已执行 ledger 和实际 fixed proof。只有原 Run.category 为目标或 NULL 才能整理，实际来源/绑定资料必须属于目标品类。跨品类时明确引导重新在对应品类查询，不默默删来源，不改 Run.category，不伪造 Artifact。

若来源属于其他型号而原 Run 没有相同实际型号，经验候选草稿提前提示从资料所属的真实型号或项目重新查询。没有推测/补写 Run.product，没有改变原生 direct_basis 和产品权限；私有/客户原件仍执行原去标识规则。个人来源分享也绑定显式目标，`search_scope.origin_category_id` 保留原始个人/品类范围。

“请补充资料/分享本次反馈”在 transport 前把原 request_key、固定 GapInput、本人、Run/root、目标品类与原接收人存入 localStorage。journal 不保存问题、回答或原件正文。刷新仅请求 `POST /experience/gaps/recover`，该端点显式使用 `reading=True` 只读 RR Session，按实际本人+品类+request_key 读取并核对完整原请求 request_sha256；既不调用 submit，也不写数据。采用 POST 是为了用原 GapInput 校验现表未明文保存的 preview_digest，不新增数据库字段。恢复 404 不触发 append；只有“重试原补充请求”明确按钮发送相同 body/key。错误回执、损坏/跨身份 journal、不可用持久存储均保留或阻止依赖写入，不自动造新 key。

## 必须由主代理分配的迁移

不修改已经冻结/应用的 839。`supplemental/personal-target-functions.json` 提供两个函数的 exact previous/proposed：

- `assert_knowledge_assistant_fact()` 允许实际 personal origin.category 为 NULL，同时保留来源、具名本人、原回执、共同事务和接收人原子守卫。
- `knowledge_answer_sources_known(uuid,jsonb)` 对 personal Run 的真实 read_sources 仍按 tenant/实际 Artifact ID/revision 核对，不把 NULL 原 category 当成 Artifact.category。

previous 函数体已与冻结 `migrations/schema_s0_0839.py` 的实际 SQL 子串逐字核对。本包没有数据库 schema 编号。主代理按真实 head 分配新迁移、照原生 ordinary_owner/require_functions 核对函数和角色后应用；`personal-target-up.draft.sql` 仅供生成/审阅，不能当已经执行的迁移。down 草案先拒绝已有 personal origin 的 Review/Gap 历史，再精确恢复两个前驱函数；没有删历史。

## 验证与边界

- `tests/knowledge`：68 项实际纯测试通过（包含新 5 项，不能再把早期 25 项子集合计）。数据库四类 URL 在这些运行中全部移除。
- 前端 5 文件组合：56 项通过，覆盖实际个人目标选择、原 Run DTO、响应丢失、刷新只读恢复、错回执、同 key 明确重试、重复点击、损坏/跨身份及存储不可用，以及原知识候选/T2与续接相容。
- TypeScript `tsc --noEmit --incremental false` 与定向 ESLint、后端 Ruff 通过。
- `tests/knowledge_pg/test_assistant_personal_targets.py`：3 项仅收集，**未执行 PG**。场景分别是个人品类资料保留原 Run=NULL 保存、恢复原 Gap 零 append，以及个人回答引用型号原件时真实型号引导。主代理在新迁移应用到已核对的显式 pdos_test 后执行。
- 未做实际浏览器、构建、Temporal、迁移往返/非空 down、生产或真实模型验收；由主代理按当前闭环影响统一验证。
- 页面 journal 不知道上版仅存在于内存的旧 request_key，也不为其编造恢复记录；本变更只从实际已经持久化的原请求恢复。
- 原生 Artifact 正文/分类保护没有被改变，本包不会用直接改不可变分类来制造测试通过。

## 主代理推荐顺序

1. 读 manifest/hash，核对 touched base 是否与 live 一致；若主会话有并行差量，按 smallpatch 精确整合。
2. 只集成 manifest 中的 13 个文件；生成并在核对备份后的隔离库应用新迁移。不要覆盖 839 或复制本副本中的历史目录。
3. 执行新增 3 项 PG，并按影响与已通过的 F 原 8 项、生命周期 5 项去重汇总；任何失败按实际原因修复。
4. 在实际个人页核对显式目标、品类权拒绝与可操作引导、补充/反馈分享丢响应后的刷新恢复。只有这些公共检查完成后才能把实现记为该候选实际通过。
