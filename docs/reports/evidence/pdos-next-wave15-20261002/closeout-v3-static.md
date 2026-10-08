# Wave15 v3 收口工具静态交付

仅修改 [wave15_closeout.py](../../../../pdos-next/tools/wave15_closeout.py) 并新增本文；没有运行工具 `main`、`selection()`、`demo()`、数据库、HTTP、pytest 或浏览器。主线的两项 graph PG 复验仍在执行，本文不宣布其成功，不授真实专业资格、生产启用或人工 Exit。

工具当前 SHA256：`25dc4c26486905a136daa4665597b4673c3df3729de5b57a12b82a9422076ef3`。初版工具 SHA256 `698788020c40f23f2e57bd0377dde80f31ba9b42c09884fe7a4a4a8a1cefefd0` 及 [原静态记录](closeout-static.md) 保留不变（该记录 SHA256 `0d08104c4067830c5624732700d3e114e34548d709da0220370bb1cc7b58d91b`）。旧 manifest/delta/selection/result/log 无覆盖、改名或重写。

## 后端顺序证据链

工具保留 backend v1/v2/v3 各303路径的完整 manifest。只要求最新版本当前源码匹配；旧版按其固定 expected hashes 与逐版差集核对，不将旧版自然不匹配当前源码说成损坏。v3 必须有 v2，文件集合不得增删，每个实际 SHA 差异必须对应唯一 path、完整 before/after SHA 和非空 reason。

- v1：固定 `pg-selection.json` 的13组/13函数/14参数病例，完整保留 `pg-result.json` 及各组日志。所有原组必须有退出结果、精确 node 覆盖和终结摘要；成功与失败都须真实收尾。不能以晚来的成功记录掩盖中断/缺日志/原用例未结束。
- v2：唯一归并 node 的真实 `merge-history-recheck-selection.json` / `-result.json` / `.log`，只绑定 backend-v2。原v1 pg02失败保留，成功替代明确标 `passed_with_exact_v2_replacement`。
- v3：只允许原pg11/pg12精确两函数；每项独立 selection/result/log 必须绑定 backend-v3及其 manifest SHA。两项均完整成功后，才一起替代两条旧失败；其中一项 pending 不使另一项提前变 effective。v2未就绪也不能由v3绕过。标记 `passed_with_exact_v3_replacement`，保留原结果、日志及替代版本。

当前源记录名：`backend-candidate-v3-source.json`；主线已记录 SHA `8f5e7542818773af2d0f341af40896550c2bfb74be246eaa49698f43eba23833`。`backend-candidate-v3-delta.json` 应在两节点实际完成后一次排他写入，不修改 v2 delta。精确合同：

```json
{
  "previous_manifest": "backend-candidate-v2-source.json",
  "current_manifest": "backend-candidate-v3-source.json",
  "previous_manifest_sha256": "<v2 manifest SHA>",
  "current_manifest_sha256": "<v3 manifest SHA>",
  "changes": [{"path": "<完整差集路径>", "before_sha256": "<v2 SHA>", "after_sha256": "<v3 SHA>", "reason": "<具体修改原因>"}],
  "rechecks": [
    {"nodes": ["<pg11精确函数>"], "selection_file": "graph-history-recheck-selection-pg11.json", "selection_sha256": "<SHA>", "result_file": "graph-history-recheck-result-pg11.json", "result_sha256": "<SHA>", "log_file": "graph-history-recheck-pg11.log", "log_sha256": "<SHA>"},
    {"nodes": ["<pg12精确函数>"], "selection_file": "graph-history-recheck-selection-pg12.json", "selection_sha256": "<SHA>", "result_file": "graph-history-recheck-result-pg12.json", "result_sha256": "<SHA>", "log_file": "graph-history-recheck-pg12.log", "log_sha256": "<SHA>"}
  ]
}
```

每份 selection 是 `{nodes:[NODE],candidate:"backend-candidate-v3-source.json",candidate_sha256:SHA}`；result 增真实 `exit_code/seconds`，相同 node/candidate/SHA。路径仅限本证据目录内安全 basename、不得复用一个记录冒充两组；v3逐项三证据 SHA 必填。日志病例、pass总数、终结分类总数必须一致，完整 failed 不被解释为 pending 或通过。结果缺失时保留 pending，矛盾或已失败证据直接拒绝。

## 前端 v3 与旧35项边界

保留 web v1/v2/v3 各138路径。v1→v2只允许原 result-label component 差异，并核原 `ui-result-label-fix.json`/v2 build。v2→v3只允许 helper/test两个精确路径，核 `ui-event-time-precision-fix.json.previous_hashes/files` 与前后 manifest；旧 component 保持 v2 SHA。

`web-v3-build-result.json` 须含 `candidate_manifest/candidate_manifest_sha256`、`helper_log_file/helper_log_sha256`、`precision_delta_file/precision_delta_sha256`、`files:138/source_stable:true` 及通过的 lint/build（如记录 typecheck，也必须通过且不重复）。`ui-helper-v3-checks.log` 须逐字对应精度修正证据中 C 实际37项的 raw_output，核 SHA及37/37、零失败/取消/跳过。旧 `ui-helper-checks.log` 的35项只保留历史证据，不当作修改后helper通过。

当前 web-v3 manifest SHA：`a48c1a528a714eac73660d58b487f0559baa61ead7b6241e533dace4af1f907f`。静态兼容读取已确认主线生成的 v3 build metadata与C真实37日志相符；没有由本任务执行 typecheck、lint、build 或helper检查。旧81 backend pure明确标v1范围，24 BFF与UI范围分别呈现，绝不相加成全仓联合。

## 本次局部验证与调用

Ruff check/format check、AST parse/compile通过。仅执行从AST提取的文本/元数据校验函数与自有临时文件：顺序成功链；错candidate SHA拒绝；缺终结摘要使两graph均pending；完整失败拒绝；v2缺失不能绕过；路径越界拒绝；病例与摘要分类不符拒绝。只读解析原13组/14病例的结束记录与v2成功归并日志，不重跑它们。

主线仍用原 `demo --issue <logicalUUID> --change <logicalUUID>` / `selection --issue ... --change ...` 两模式。62513/marker/head23、私有seed、只读事务、真实原件门禁、旧保存事实/占用核对与最终排他输出逻辑均保留。缺证据退出pending，失败明确报告；已有最终文件绝不覆盖。

最终结果范围必须表述为 **v1完整选择 + v2归并受影响复验 + v3图受影响复验 + web-v3实际helper/构建**。这不等于v3整树联合、全仓回归、真实整改有效性、生产资格或人工 Exit。实际收口执行及新graph结果仍由主线完成。
