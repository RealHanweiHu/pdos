# G 钉钉整合候选：四层 → 当前 live

单一入口：`integration-manifest.json`。仅按其中 files 的相对路径应用，**禁止整目录覆盖**。本目录其余当前 server/web 副本、依赖/.next 链接只用于验证；原四个 frozen 包未修改。本候选未修改 live，未访问 DB/Temporal/真实模型/embedding/钉钉/出站，未构建、提交 git 或分配迁移号。root 通知实际 head 为 s0_0842；正式号由 root 再核实际 head 后决定。

## 可用代码范围

原 candidate1 → ACL delta → 官方协议/设置 UI → Delivery lifecycle，逐 manifest/SHA 核对，合成完整 46 文件（35 新、11 改）。同一小Pai实际 native Run → 原 Temporal XiaopaiWork → 注册 LangGraph；G completion 只编排引用和投递，不增第二 Agent/旁路模型。本人 OAuth nonce 绑定、管理员撤销、原凭据 KMS 引用、单聊/群@默认私发、本人明确预览确认群分享、全答案客户 taint 禁正文、每实际投递 P26 journal、unknown 仅查原回执均保留。

官方协议端口默认不可用：必须显式注入 runtime，测试只有 MockTransport/SyntheticKms。完整官方群成员原子版本不可得，官方引文分享禁用；无 processQueryKey 的丢响应保持 unknown，不自动重发。Delivery 是实际正文 consuming 副本，已按实际多品类固定 footprint 复用唯一 F resolver 接入原件 retention gate/clock/graph；另外五表前后都是 NON_CONSUMING。

## 当前 live 公共 hook 重基线

- API 保留 C embedding + F routes/原 create_app 参数，只在原 kernel router 后加 G 注册。
- models 保留现有 embedding_models、knowledge.assistant_models，末尾追加 G model 注册。
- worker.main 同时保留 embedding_ports 和新增 dingtalk_runtime；原 C embedding workflows/activities/ProjectionSender(embedding=True)/client cleanup 完整保留。G discovery 只在 runtime 显式注入时运行，注册 Completion 和 deliver/cancel 活动。
- Host/execution/persistence/AppShell 与原 G base 精确相同，按冻结小 hunk 加 guard/本人深链；不动其他核心图。
- Settings 保留现有 embedding 配置，偏好区增加本人 DingTalkSettings；BFF 保留原全部路由和范围判定。G 路由入口使用局部动态 import，只有明确 channel 路径进入独立 closed adapter，实际 allowlist/身份/源/DTO 仍由同一个 dingtalkRequest 核验；原路由无需加载新端口。
- 自动三方输出在检查阶段发现上下文不完整，已弃用；五个 drifted 公共文件均从保存的**当前 live base**逐唯一精确 anchor 添加局部 hook。最终 patch、strict SHA replay 与实际旧 BFF 全组证明当前交付，不使用那份中间输出。两处实际文本冲突是 models 的末尾新增 import 和 worker.main 签名，均保留 C/F 后合并。

新增整合差量：SQL 静态 literal ASCII 分块，最大 Python 行 96（无整文件 E501 豁免）；新增完整未编号 base SQL 常量模块；downgrade 的 ACCESS EXCLUSIVE 六表非空拒绝；原表列 ACL 精确撤销修复；3 个静态检查与2个实际共享 BFF 接线测试；4个 G 新测试文件 import-only Ruff 整理。原 SQL 字符串只有 DOWN 的必要列权限清理增量，lifecycle 四组字符串逐字不变。

## DDL、目录与历史边界

- [DDL.md](DDL.md)：admin / ordinary_owner 精确顺序、9+2 函数 owner/ACL、六表最终 owner、非空保护、降级依赖顺序与 wrapper。
- [TABLES.md](TABLES.md) + `lifecycle-columns.json`：六表完整逐列/type/nullability/分类；Delivery 接线前后始终 consuming，其余五表 NON_CONSUMING。
- `sql/combined-up.draft.sql` / `combined-down.draft.sql` 是完整人读 SQL。真正执行请按 DDL.md/wrapper 的角色切换及非空 guard，不盲执行。
- `migrations/candidates/dingtalk.py`（BASE_SQL/TRANSFER_TABLES_SQL/EMPTY_HISTORY_SQL/BASE_DOWN_SQL）+ `dingtalk_lifecycle.py`（原2 m3精确 before/after及14 up/8 down）可供 root 编入实际 schema；不是已安装版本。
- `review/alembic-wrapper.py.template` 无 revision/down_revision。六表最终 owner=pdos_next_owner；九 G helper owner=NOLOGIN maintenance；两个新 lifecycle trigger owner=pdos_next_owner。owner 固有表权限不能被四列 GRANT 描述成正文隔离；实际 metadata-only 查询不选 payload，maintenance/runtime 不获业务正文。
- 旧 m3 pin 来自当前 schema839::NATIVE_FUNCTIONS，逐字核对，841不改它们。真实 PG require_functions 仍必需，不用静态结果冒充。

## 精确重放

1. 阅读本 manifest、DDL.md、PG-PLAN.md；不要同时应用原四层（它们已折叠在本包）。
2. `python3 replay.py --target <repo>` 仅核目标全部 old SHA 和 staged SHA，不写。
3. root 明确选择应用后：`python3 replay.py --target <repo> --apply`。先核完全部46项再写逐文件，新增文件必须不存在，旧文件必须精确命中 base；任何漂移即停止，不猜合并。`integration.patch` 提供等价纯文本 review；strict scratch replay/patch dry-run 均记录 evidence。
4. root 自行分配迁移正式号/实际 down_revision，按 wrapper 验证管理身份和839原函数 pin、备份/执行/往返；不能仅 copy ORM 就宣称数据库接通。
5. 统一执行 PG-PLAN.md 的13项，随后真实浏览器设置/本人深链/撤绑/预览/unknown UI。实际业务/外发资格与真人验收保留。

## 本次同候选验证

- 后端 **89 unique pure passed**：G 74（原71+新3）+原 kernel graph15，7.11s，见 `evidence/backend-final.txt`。数据库环境变量去除；没有混入 PG skip 或 collect 计数。
- 前端 **298 passed**：G19（原17+实际共享 BFF2）与受影响旧路由/深链279，见 `evidence/frontend-final.txt`。节点使用明确合成传输/组件调度，不称浏览器。
- 36 交付 Python AST + Ruff，通过，`evidence/ruff-final.txt`。SQL候选 literal ASCII/最大行96、10列GRANT与5动态record表实际列集合静态核对通过；不是 PL/pgSQL 实际编译证明。
- 整套 stage web `tsc --noEmit --incremental false` exit0，见 `evidence/tsc-run2.txt`；10交付前端目标 ESLint exit0，见 `evidence/eslint-final.txt`。未运行 typegen/build。
- 13 PG/Temporal **仅 collect，未运行**，精确名单 `pg-temporal-nodeids.json` / PG-PLAN.md。迁移往返、非空拒绝、真实ACL、跨租户/并发保留、实际浏览器仍待 root。

## 注入与无出站运行

API：在传给 create_app 的同一 engine 上显式 `dingtalk.runtime.configure(engine, runtime)`；不注入则设置 GET 诚实 configured=false，绑定/发送不可用。Worker：`main(..., embedding_ports=<原端口>, dingtalk_runtime=runtime)`；原模型仍只经注册图，不从 channel 调模型。

runtime：`ChannelRuntime(kms, OfficialAdapter(httpx.Client(transport=httpx.MockTransport(handler)), callback_uri), public_base_url)`；KMS implements current_version/value→SecretStr，测试使用合成值。官方适配不自动创建 HTTP client/读取凭据，default 无配置。callback_uri 固定同源 `https://<PDOS>/?area=settings&dingtalk_callback=1`，public_base_url 同一 HTTPS root。真实部署仍需实际平台登记和 OAuth query 日志脱敏，组件只清理地址栏且不持久 code。官方协议依据及无socket测试实现见原 protocol/UI 冻结 README（manifest固定SHA）。

未完成：root实际DB/Temporal/浏览器、真实账号/凭据/出站、真实平台全群引文协议、生产启用。无 processQueryKey 的 unknown 保持不可自动对账，不伪造投递成功。
