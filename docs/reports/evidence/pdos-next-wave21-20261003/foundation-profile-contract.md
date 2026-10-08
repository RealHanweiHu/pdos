# Wave21 三类多范围 synthetic 启动 profile 合同（隔离暂存）

本段只在 `pdos-next/.local/wave21-foundation-staged/` 实现；正式 server 源码、测试、启动配置和数据库均未修改。暂存包是 310 个 Python 源文件的实体副本，无 symlink。主线封存 Wave20 后只可按清单的基线/最终 SHA 应用三源码与三新纯测试，不能整包覆盖。

三个模块均导出 `configure_local_profiles(engine, profiles) -> tuple[实际 opaque issuer, ...]`，返回顺序等于名单顺序。输入必须是明确、非空的 JSON `list`，最多 20 项，不收 tuple/隐式默认配置。

| family | list 每项准确字段 | issuer scope |
|---|---|---|
| operational | tenant_id、product_id、issuer_key、issuer_version、decisions | tenant/product；实际 Build/config/purpose/window 位于有限 decision binding |
| test_resource | 同上 | tenant/product；完整 TestPlanBinding/实际样件方法/窗口位于有限 decision binding |
| quality | tenant_id、product_id、project_id、issuer_key、issuer_version | tenant/product/project |

同 family 内 scope/key 均不可重复。issuer key/version 是服务器明确配置的 1..100 字符原值，不 trim、不允许空白包围。每项及整个名单的全部 UUID、字段集、有限 ledger、typed decision/resource/binding、JSON、重复与既有配置冲突先校验；非法晚项也不会注册早项。Operational/test ledger 分别保持 100/200 项上限；允许空 ledger，但不存在默认 named decision 或正向资格。

旧 `configure_local_profile(engine, profile)` 字段集、默认 issuer key/v1 和显式重配置语义保留；成功时另外记录可信启动配置材料。新 plural 调用只有完整 canonical JSON 相同且 domain registry 仍指向原 opaque issuer 才复用原对象/epoch/callback。旧 single 的显式重配置仍会推进原 epoch；本段没有把这一既有操作改成隐式幂等。

三处启动材料记录分别在 engine 的 `_pdos_operational_bootstrap_profiles`、`_pdos_test_resource_bootstrap_profiles`、`_pdos_quality_bootstrap_profiles`，只保存 canonical 配置及真实 issuer identity。它们不存 Session、调用者、HostGate、phase proof 或来源/授权正结果。缺少可信配置材料、旧 issuer 已撤回/替换、同 key 的 scope/version/decision 材料变化均拒绝 plural，不按“scope 相同”乐观复用；plural 不承担旧 issuer 更新。

新 scope 使用独立 key，名单外不会自动注册。配置调用仍先核真实 `verify_test_target`，实际 domain issuer 检查 exact tenant/product(/project)；有限 verifier 仍逐值核完整 binding/resource/具名 decision 与 exclusive expiry。callback 返回 ledger 核对结果不等于完整 resource readiness、current source ACL、实际专业资格或生产授权。

主线 API 应对同 family 的 single/plural 参数互斥，plural 明确包含需要保留的全部 old scope，不能猜 caller/model scope。本段不改 API、专业/rule/completion 配置、不发布新操作、不改 DB/迁移，也不配置真实资格。现有真实来源/安全/当前事实/占用检查全部留在 domain host。

## 检查范围

六个暂存文件：67 项 owned `--noconftest` 纯检查通过（最终 0.95 秒），Ruff、format check、cold import、in-memory AST 均退出 0。测试使用真实 typed DTO 和 opaque domain issuer/registry，只有 marker 验证、无绑定 Session/engine 边界为明确替身；没有连接数据库、读取真实原件、办理业务资格或加载应用。覆盖旧 single→plural 的 identity/epoch 复用、完整绑定/产品范围、期限、撤回/替换、非法名单末项零注册、20 项上限、原输入变化不影响 pinned ledger。

第一纯检查 67 项通过但含 TestPlanBinding 类收集警告，最终仅将导入改为别名清理；原始日志保留。中间导入排序 lint 失败（3 项）及修复日志亦保留，不作为最终通过。最早工具 lint 输出发生截断，未冒充完整原始日志。

正式源码 310 项相对复制基线均保持，暂存包只有三 owned bootstrap 发生变化；正式三新测试目标仍不存在。本段没有 DB/HTTP/browser/公共测试或 build 结论，也尚未应用。
