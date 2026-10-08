# Wave22 Build v2：已知需求的精确 Decimal 相等

v1 原工具/测试与所有证据保持。实际服务器需求为每件 `1`、总需求 `2.00000000`、`ea`、空 issues；这是已知两件需求，原字符串 `== '2'` 错误拒绝了保存的固定精度。

v2 仅将此判断替换为严格有限 Decimal 等值，输入须为有界于实际 JSON DTO 的十进制字符串；不转 float、不作容差、不改写任何服务器原值。仍须唯一一条完整 DemandLine、每件精确等于 1、总量精确等于 2、单位 ea、issues 真正为空数组。bool/float/null、非有限、错数量/单位、未知 issues、缺字段/多字段/多行拒绝。没有 source/import/operational draft 时可用同一尚未发送的原观察材料继续；不能借此清除任何已发送 UNKNOWN。

实际运行：同一 v2 候选 38 项无 DB/HTTP 纯检查通过（33 个既有检查加 5 个新检查），0.779 秒；Ruff 与两文件 AST/compile 通过。原始日志与精确命令见 check-result-v2.json。未执行实际 Build/物料/资源写入，未验证生产或专业资格。

Root 应用范围仅 v2/wave22_shared_build.py 和对应测试；公共工具由 Root 单独替换、实际执行与记录。v1 SHA 与 v2 SHA 在 source-manifest-v2.json，不覆盖原 v1。
