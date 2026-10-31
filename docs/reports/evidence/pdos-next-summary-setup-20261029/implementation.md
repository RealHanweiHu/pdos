# 本人确定性摘要订阅：独立第二增量，待主代理集成

门禁冻结包保持不变。第二增量的共享文件与门禁包没有交集，全部以 `manifest.json` 中记录的 live SHA-256 为基线。`tree/` 仅含 9 个共享候选与 4 个新增文件，不能整目录覆盖 live。

## 最终行为

- 新摘要选择模板、频率和本人项目后点“预览摘要订阅”：先沿原 `ai.automation.draft.save` 保存实际草稿，再读取服务器返回的真实规则/版本，用原 `ai.automation.activate` 准备预览，最后由本人一次确认激活。
- 预览展示实际模板/分组、关注项目数量、频率、首次时点、时区、本地资源限额和真实小Pai服务身份。原完整声明折叠。保存、预览均不激活；刷新只读，不重发；丢失响应保留原命令、幂等键与确认材料。
- 新确定性摘要声明 `skill_keys=[]`、`validation_budget_id=null`、四项模型预算全 0。没有任意技能占位、钱包创建、模型资格授予或服务身份选择。
- 通用 Run 已支持空钱包，不改列或公用 RunSchema。兼容正整数 token_limit 的存量列约束，摘要固定为 1，但 Python/SQL 均禁止任何模型或通用工具调用，实际持有/消耗 token 必须为 0。
- 原普通规则仍要求实际钱包、固定技能与正模型用量上限，保留原模型执行路径。已保存带钱包摘要与其自定义分组/频率/技能/钱包不被静默改写；本人明确点击转换后才改为无模型预算摘要。
- 修正旧自定义摘要的时区失焦会默默改成每周一的问题。现有自定义触发/频率保持原样，明确选择新日历才替换，仍可在高级配置编辑原设置。

## 服务器与 SQL 边界

模式从实际已发布 Spec 的 personal_summary 与原 native Grant/Attempt 推导，没有客户端可提交的 mode 字段。原具名 T1、唯一小Pai、本人身份、品类/型号访问、来源 RLS、暂停/取消、幂等、次数、冷却、级联与摘要条目上限保留。

Activity 已有唯一小Pai注册图内的确定性分支：该分支跳过 BoundHost 和模型网关，本增量不新增 Agent 或任意技能。新合同仅使该既有分支不再依赖无关模型钱包。

`migrations/schema_summary_walletless.py` 单独冻结完整 SQL：

1. 先按 `sql/pins.json` 钉住实际 0794 start / 0793 proof 的原定义；原文均从各版本 SCHEMA_SQL 取，不是 downgrade。
2. 只对原激活版本中的 null-wallet 摘要跳过模型钱包预检，同时强制该实际版本为 personal_summary 对象、空技能、token_limit=1、零模型预算。普通规则完整原钱包预检保留。
3. 原 same-snapshot Grant/Attempt/Run 证明字节保留，仅追加无钱包摘要零用量、零通用调用守卫。
4. 新增 BEFORE INSERT 触发器，从实际已激活 Grant/Attempt/Version 核对摘要运行，拒绝其任何 AgentToolCall 插入。Python generic claim、dispatch、模型网关在进入 route/secret/provider 前同样拒绝。这个拒绝也适用于原确定性摘要，因为它们原本就不应调用通用工具。
5. 降级先取得版本、Run、调用表的排他锁；发现实际无钱包摘要版本历史就拒绝。空历史才撤触发器并恢复两份精确原定义。

SQL 模块使用描述性名称，不需重命名。`sql/alembic_wrapper.py` 是独立短模板，主代理按当时真实 head 的下一单调号填写 revision/down_revision 与版本文件名后放入 migrations/versions/；本代理没有分配占用号或执行迁移。

## 交付与验证

- `shared.patch` 是完整统一补丁；另有 `backend.patch`、`frontend.patch`。原前端 JSX 大部分写在单行，因此 unified diff 展开约 71 KB；`surgical-edits.json` 只保留真实字符增量，约 22 KB，并以 base/candidate 双 SHA-256 防覆盖。
- `apply_surgical.py --root <repo>` 默认只核对全部共享文件。主代理审阅后可显式加 `--apply`，再按 manifest 逐项复制四个新文件。源基线有变化时脚本拒绝，不覆盖 C 的新 hooks。bootstrap 不在交付清单；gateway 只增加模型入口的四行 guard。
- 最终 149 项后端纯测通过，其中新合同/拒绝/SQL 保留检查 28 项；最终 58 项前端检查通过，其中新增 5 项。分段不叠加为虚增总数。
- TypeScript 检查、5 文件 ESLint 与显式 `--config pdos-next/ruff.toml` 的 9 文件 Ruff 通过。真实输出和精确命令见 `validation.json`、`logs/`。
- 新 PG 草案 8 项仅收集通过，未执行。另一次误选现有 test_gateway.py 的 7 个实际 PG 用例，因未提供 TEST_DATABASE_URL 在 fixture 连接之前中止；这 7 项仍由主代理在已核对隔离环境执行。没有 DB 连接、真实模型、embedding、外发或 live 源码写入。
- SQL pg_get_functiondef 钉住、迁移往返/非空降级拒绝、新 PG、C Query 实际入口负例、合同导出、最终集成类型/构建和实际页面仍须由主代理验证。不能据本包宣称完整两份设计或正式阶段验收完成。

三处原后端 imports 的 Ruff 排序随本增量修正；不改业务语义。`verify/` 是验证快照，包含门禁候选作为后层，仅供核对，不可复制到 live。
