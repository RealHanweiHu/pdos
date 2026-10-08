# Wave15 独立合成演练工具：静态交付

本文件记录实施与静态检查，**尚未运行 seed、数据库操作、HTTP、pytest 或浏览器演练**。工具不会授予真实生产资格；后续实际执行、API profile 重载和验收均由主会话统一办理。

工具：[wave15_seed.py](../../../../pdos-next/tools/wave15_seed.py)。SHA-256：`c9afc6cc536f3604a1b2f1d5e4d39feb0673d02b3b178959d5d53f29b914455c`。

## 隔离与保留范围

复用既有 Product 与共同领域算法；新建具名合成人员、仅该 Product 的 Grant/LoginSession、独立私有 Definition/Project/BOM/工程与制造配置、Build、物料池、制造设备、Lot、单模穴 A Sample、请求、Run、测试设备及人员资源身份。所有专业、资源、政策事实经过 marker 核对后的 host-only opaque synthetic issuer 导入，不通过公共载荷声明资格。职责、人员资格与 ProductGrant 分别办理。

新 purpose 为“内部问题调查：独立单模穴A尺寸复测（合成）”。请求范围严格为数量 1、模穴 A、测试项 dimension，判据 9.5–10.5 mm，工况 `23 C, dry`。报告是新 Run 实际开始之后生成并真实上传的合成 JSONL 原件，明确原值 `11.0000` 和所有执行元数据；扫描、解析、原件字节核验、固定 Projection 与 definite fail 门禁保持。原 Run6 的 indeterminate、旧请求的 B/C/数量缺项均不改写。

工具在执行前保存 33 个固定领域表中原有行的完整列摘要；范围按目标 tenant/product 限定，tenant-global 资产及样件 usage sentinel 按目标 tenant 限定。每个阶段成功返回及恢复进入时核对原有行，包括旧物理资源的 occupancy epoch、样件 readiness/usage、Run/Formal 版本与指针。新行允许增加，Product 正常 lifecycle reference epoch 不在该不变比较范围内。该比较只证明原有记录保持，不宣称旧执行当前资格或真实生产可用性。

operational/test-resource 有限 profile 保留全部原 entries 与顺序，只追加新 decision UUID；分别遵守原 100/200 条上限，超界不写文件。现有 quality loader 只支持单 project profile：文件不存在才创建；若已有不同 scope/key，保留原文件、另保存新 profile，并停止，等待主会话提供同时支持两个范围的明确接线。不会覆盖旧 issuer/key。

## 实际执行阶段

所有阶段均需显式传入当前独立 `62513/pdos_test` 的 marker 和 `--ack-synthetic-local`。每次 DB/UOW/HTTP 前复用 `read_state`/`verified` 核对 Docker/container、地址与数据库 marker；不回退 `.env`，不修改 local-environment runtime state。工具没有模型调用、外发、删除、关闭、释放或再消费旧样件的入口。

1. `prepare`：创建独立账号与固定配置、专业事实、准备需求及 operational fact；首次停在 `operational_reload_required`，由主会话重载追加的 operational profile 后原样恢复。接着完成两次真实 T2、Build Start、实际配置/Lot/Sample、purpose 限定 ready、准备/请求/计划与实际方法适用、完整 A 交样/接收；创建独立测试资源后停在 `prepared_reload_required`。主会话重载 test-resource profile 后再次 `prepare`，保存固定 Run Plan 和具名 Promise，停在 `prepared_waiting` 并打印真实 `start_at`。
2. `start`：只接已保存 Promise 的新 Run。按真实服务器 UTC 等待窗口，单次等待最多 30 秒；到点生成真实发生时点的精确事件，共同 T1 原样提交，资源占用与 sample usage 由领域同事务办理。
3. `result`：生成并上传新原件，按服务器实际 security epoch 申请扫描；等待真实报告 gate，按原件 `original_line=1` 捕获。保存完整最终结果与实际结束时点，canonical T0 计算；只有服务器结果明确 `fail` 才进入下一步。
4. `quality`：显式发布新范围的 synthetic 高风险/需独立验证政策，停在 `quality_profile_reload_required` 等主会话重载。恢复后固定真实失败 event/measurement 创建 Issue，完成 triage、具名 containment 与 CAPA 草稿。根因、措施完成、有效性、关闭与放行均不办理。

资源事实创建前可选择 `--lead-minutes 5..30`，默认 10；同一 checkpoint 恢复须沿原值。测试窗口结束为该新资源事实创建后 4 小时，事实/具名资源决定有效至 5 小时；原 Build 的限定制造范围为独立 16 小时。Lead 不是资格或确认 TTL 扩展。Plan/Promise 若办理时未来窗口已过，或实际 Start 时窗口已结束，工具按真实守卫停止，不改变任何已保存时钟、事实、Promise 或身份。恢复应先检查私有 checkpoint/已提交回执，保留未知原请求，主会话另行明确新意图；工具不自动改期或更换 key 重发。

## 私有状态与未知恢复

`.local/wave15-seed.json` 和 `.local/wave15-login.json` 均原子写入、fsync、权限 `0600`。新账号在主 checkpoint 中使用精确键 `actor_id` / `login_token`；login 文件使用 `principal_id` / `login_token`。不输出 token、密码、连接 URL，也不覆盖旧 `preview_token` / `preview_principal_id`。控制台只输出阶段说明、真实 start_at 和恢复所需的 HTTP status/封闭 error code。错误不输出响应全文、SQL、URL 或凭据。

共同命令的 ID/key、完整载荷、服务器 returned prepared command 和回执先保存再继续。预览/提交未知时恢复同一命令，不重新造请求或换 key；过期、漂移、权限/来源失效按领域错误停下。此工具没有第二套确认、回执或独立领域 commit。Host 导入沿现有共同事务 wrapper。确认 TTL 和真实 SQL clock_timestamp 守卫原样保留。

## 已完成静态检查与待验证

- 新工具 scoped Ruff/format 通过，AST 与 `compile` 通过。
- 通过 inert non-main declarations 加载核对 33 个 retained 表均在当前 ORM metadata 注册，且有 id/tenant_id；未创建 engine 或连接数据库。
- 对当前 `ResourceInput`、`FactInput`、`ExecutionPlan`、`TestPlanBinding`、`TestResourceFactInput` 做纯 DTO 构造核对。首个临时构造检查因检查脚本人力资源 ID 不等 executor 被严格 DTO 拒绝；纠正检查输入为同一具名 actor 后通过，工具实际构造本就沿 actor ID。
- 定向核对并修正现有接口细节：handoff reference_samples 的真实 `reference`；Run 的 `plan_sha256`；Workspace originals/实际 security epoch；Promise 的固定未来窗口时点；operational binding 的 typed UTC JSON 规范化。静态检查不等于运行闭环通过。

待主会话实际验证：host/API profile registry 一致、native 文本 provenance、真实扫描/解析 worker、各阶段当前资格/来源/读集、精确幂等恢复、旧行摘要保持、实际占用、definite fail → Issue/CAPA 的 HTTP/浏览器闭环。任何缺端口或 unknown 都停止，不产生替代肯定事实。本交付没有生产启用、AI T0 资格或人工 Exit 结论。
