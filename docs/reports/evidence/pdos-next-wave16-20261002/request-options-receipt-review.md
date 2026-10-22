# Wave16 当前请求候选的直接保存回执桥

本次 B 仅新增 `server/tests/quality_followup_root/test_request_options.py` 及本证据，没有修改公共 integration/views、包标记、业务文件或唯一清单。主线负责公共修复与真实 DB/HTTP 验证。

## 接线事实与最小修复

`verification_launch.service._record` 在开测时同事务保存下一 FormalRequest、Run 和 LaunchFact；共同 `apply` 返回 Run，因此 Receipt 主体为 `test_run`。结果导入/复核/处置同样由 `verification_results.service._record` 保存 Request/Run/ResultAction，而共同 Receipt 主体仍是 Run。合法的当前 FormalRequest 因此可能没有以自身版行 ID/revision 为主体的直接 `verification_request` Receipt。

`quality_followup_views._option/_receipt` 目前只支持直接精确共同保存回执。原 host 枚举全部当前 Formal 版，会把上述合法配对子对象送入该桥，触发 `INTEGRATION_REQUIRED`，使整个读取失败。

主线的最小修复已经落盘：在原 tenant/product/project、可读受众与精确 Current 联结范围内，候选先通过 `Receipt EXISTS` 筛选，再排序和 `LIMIT 20`。筛选保留精确 tenant/product/subject_type/subject_id/subject_revision/operation；`result.id` 与真实版行 UUID 文本一致，`result.revision` 使用 JSONB 与 `to_jsonb(real_revision)` 相等，不能把字符串版本作为数字通过。实际来源、保存人的专业依据、具名回执归属和末端重核仍由 view 核对，不通过候选枚举授资格。

宿主以 `PAIRED_FORMAL_OWNER_PROOF_NOT_CONFIGURED` 明示尚未接通配对 Formal owner 证明。没有回退 Current，没有拿原失败请求的旧版冒充新的复验分支，没有伪造 Receipt。具有直接保存回执的当前新请求可以作为本次固定输出候选。

后续配对桥可沿 LaunchFact 的 `next_request_version_id/revision`、`run_version_id/revision` 或 ResultAction 的 `next_request_version_id/revision`、`next_run_version_id/revision` 核对同事务对象及精确 Run Receipt。Run 的 `request_version_id` 固定起源已接收版，不能替代当前新 Formal 版；共同 Receipt 与领域事实的 intent 算法也不同，不能直接拿二者哈希相等作为关联。本次未实现该桥。

## 实际完成的检查

仅执行新文件的无数据库纯检查：真实 SQLAlchemy Select 使用 PostgreSQL 方言编译；只读 fake session 捕获查询并返回预先保存的版行，不评估 SQL、不伪造资格或回执。测试验证范围及 Current 精确联结、Receipt EXISTS 位于排序/限制之前、实际 JSON id/revision 条件、固定 OutputRef 使用不可变版行而非 logical request ID、空选集不补旧版、越范围在查询前拒绝，以及真实 `configure_output_options` 保留显式缺项。

最终结果：`7 passed in 0.72s`；单文件 Ruff 与 AST 检查通过。第一次 Ruff 发现一处行长，已仅调整测试字符串排版，最终纯检查重新通过。没有执行 PG、HTTP、建库或公共测试；这些结果不能替代主线真实读取验收。

主线可从 `pdos-next/server` 复用：

```sh
.venv/bin/python -m pytest --noconftest tests/quality_followup_root/test_request_options.py -q
```

## 本次核对摘要

- 新测试：`d80b0f0e41de2175350a3b847b7ce4668b9c41e56ccb129dab5c4c91e391af61`
- 实际公共 integration（只读依赖）：`2c722d0fa94e02fd5d0e1d7ebeec1e52a782015457cb58e4ed5efbf3fce32e5f`
- 实际公共 views（只读依赖）：`2848c9cb6eed6824d973c7a99d62ee756b9c92b7cfb74ae4eb8f63fb147ab0a3`

以上只标明这次纯检查所读文件范围，不声称全候选、全部旧轨或真实配对 owner 桥已完成。
