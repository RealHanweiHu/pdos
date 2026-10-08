# Wave18 Root 事实接线定向审阅

范围：Root 新 `fact_service.py`、`capa_fact_owner.py`、`capa_rule_import.py`、`capa_rule_publisher.py` 及 common 的两个新操作/消费/保存尾部。A 只新增 `server/tests/capa_effectiveness/test_fact_integration.py` 和本报告/证据；另依 Root 明确授权，将 writer 新 Current 的 `anchor_snapshot` 深复制补齐。其余冻结源码未由 A 修改。没有数据库、HTTP、浏览器或公共测试。

## 确定缺陷与窄修

1. 原 `actual == wanted` 会将 raw JSON 中 `true` 与整数 `1`、浮点 `1.0` 与整数 `1` 等同。观察外层区间/事件时钟用 `isoformat`，record 用 Pydantic JSON 时钟，同一微秒的合法 Z/offset 会被拒。初轮日志保留 `13 passed / 3 failed`，三项准确命中 bool/int 与两个 offset 路径。Root 新 `same_original_material` 用完整 canonical JSON `allow_nan=False`；仅四个已知实际钟路径转 aware UTC instant，原 raw JSON 类型/值、IANA、scope、Rule full ref 与其他字段不转换。新增测试实际调用比较和解析函数；重复 JSON 键、额外字段、原值/原发生钟/区间改变、naive、差一微秒均不能通过。
2. 观察旧路径检查 Artifact 文本与安全 basis，不能据此声称已解析上传仪器原件 bytes。Root 明确 `original_id is None` 的受控登记 native 范围；uploaded 当前报 `FACT_OBSERVATION_SOURCE_OWNER_REQUIRED`，不拿派生文本当原件。Rule publisher 同样拒 uploaded，仍需显式 native 登记/出处与 host synthetic issuer。真实仪器适配是独立剩余端口。
3. 原 runtime stamp 只有 publisher 对象/旧 issuer.epoch，registry 撤销或内部 callback 替换可在最后来源 IO 后漏检。Root 已加入实际 rule issuer registry identity/scope/version/epoch、publisher/read/current、review/paired/applicability callbacks 与相关依赖身份。新纯反例保持独立 ResultBridge stamp 不变，只撤 registry/替内部函数，实际 `runtime_stamp` 必须变化。
4. writer 初版 Current 只复制 `models.BINDING`，遗漏 `_Bound.anchor_snapshot NOT NULL`。Root 授权 A 仅补 `deepcopy(row.anchor_snapshot)`，真实模型 NOT NULL 列与原完整锚深复制断言已加入原 owned 测试。59 项通过；新 delta `fact-write-anchor-snapshot-delta-v2.json` 保留旧 manifest 和失败/修订日志。
5. 当前保存会 stage Fact + Current。Current 的立即 SQL guard 必须先看到同 UOW immutable Fact。Root 在 Rule host 与 public Obs/Review common 尾部显式 `flush([row/subject])`，随后 full flush；不在 writer 的最后证明与 `s.add` 之间插 IO。新测试真实调用 common.execute / publish_rule，三个 kind 都要求第一次 flush 只含实际 Fact，再全组 flush。数据库触发器/延期原子组与事务回滚仍由 Root PG 验证，禁连接测试不证明 SQL 成功。

## 可接受接口与守卫

- `fact_service.configure(engine,owner)` 固定实际模块 semantic 与 ConsumptionHost 映射；无运行配置明确 `INTEGRATION_REQUIRED`。Rule 无公共 PAYLOADS/T1/T2 条目；`publish_rule` 必须传该 runtime 实际 publisher identity，不能从客户 issuer 字符串替代。未配置 publisher/review owner 默认 503，未产生假资格或七门禁完整性。
- Obs T1 / Review T2 `prepare_preview → preview_prepared` 与 `prepare_write_review → bind_consumption → common persistent false→true → record_consumption → apply_prepared_write` 使用同一 actual Session/UOW。record 的第一个实质动作是实际 `capture_after_transition`，其后才 `_phase`；新测试禁 execute/scalar/scalars/flush 并调用真实共同 consumer，先捕获再 phase 核。preview 没有消费 marker。Rule 完整写入没有 Confirmation/T2 proof。
- 材料使用原 13 键全文 review、原 full anchor、actual Current CAS 与完整读集。writer 的 scope/owner/visibility 与 Current 是服务器绑定，客户没有 FactBase/provenance/参与者/issuer/资格字段。原 Cmd/key/源读集不被重写。保存只产生既有 Fact 和相应系列 Current，不再 Receipt/commit/占用；Root 共同尾部 append 原子组。
- `ActualFactOwner._series` 真实有界 `limit2/populate_existing/no_autoflush`。同号旧请求重新核实际 Current/Rule/executor，只允许历史 parent 描述进入 replay；新写旧 parent 必须 VERSION_CONFLICT，不能重置 Current 或绕开 previous。此纯检查核真实 SQL statement/函数行为，行与 full reader 是显式替身，不冒充真实 DB registry。
- DefinitionReference 的 quote 是精确 substring 定位；`refs_from_exact` 生成整行 UTF8 SHA 的 SourceRef。测试实际转换且比较整行/子串摘要，并验证空白变化撤销原位置。已知 clock 正常化不碰 Source position 哈希、原文 raw 字段或原 Command。
- Rule publisher 固定明确 scope、trusted registry identity、synthetic nature、原完整 candidate anchor、严格整行 JSON 与固定 valid_until。不是 public 自授入口，`production_qualified=false` 不升级真实生产资格。Review 缺完整真实 paired/applicability/participants owner 仍阻断，不从 `unknown` 推适用/通过。

## 剩余真实接线范围

本报告没有证明 PostgreSQL FK/RLS、原子 commit、Rule 出版专业资格、上传仪器原件、实际完整观察覆盖、真实独立人或七 owner。`ActualFactOwner` 的 authority/policy/source/anchor 与完整 current 末端重核、最早未来 activation/有效期、同 Session body+实际 Receipt/Audit/Outbox/RequestKey 组由 Root 实际环境继续验。未知记录可保留，但不能把空 missing_fields/SourceRef 存在当 complete；是否完整须可信 Rule/观察/专业 owner 与后续 gate 实际核对。

## 检查与证据

最终新接缝测试 `29 passed in 1.51s`，只执行 `--noconftest tests/capa_effectiveness/test_fact_integration.py`，真实 ORM Session/UOW/persistent Confirmation history 与实际 common hook，SQL/source/qualified owner 明确替身；SQLite 连接钩子主动失败。Ruff/format、新文件 AST 与内存编译通过。初轮 3 功能失败、二轮 2 测试 alias 替身缺失均保留，二轮只补实际 fact_service 导入的 confirmation_for alias，不改生产语义。

Root 可用命令（工作目录 `pdos-next/server`）：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=.:tests .venv/bin/python -m pytest --noconftest tests/capa_effectiveness/test_fact_integration.py -q`。Pytest 对明确目标目录的默认 prepend 可解析既有 helper；真实 `test_common_execute_validation.py` 在 `tests/capa_effectiveness/`，本轮没有执行该公共范围。29 与原 59 的覆盖范围不同，不相加为 PG 或全树通过。

文件 SHA、Root 观察字节与退出码绑定见 `root-integration-review-manifest-v1.json`。Root 宿主仍可能继续施工，观察 SHA 不表示整个后端冻结；后续 Root 应以实际新候选统一验证。
