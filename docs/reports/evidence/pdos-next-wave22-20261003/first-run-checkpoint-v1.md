# 第二十二波：首轮独立 Run 合成检查点

新共享 Product/Project 的基础、有限三人职责和 Build/两件 A 已实际保存。原未提交窗口提案及已保存但过期的 planned v1 分开保留；过期 Run 的 Start、测试占用与样件使用仍为零。新的独立正式请求、未来窗口承诺、实际开测、原件扫描/解析、完整原值导入及独立结果计算已经保存。

原值为 **11.0000 mm**，固定判据为 **9.5～10.5 mm**、23 C/dry；实际投影判定 fail。来源完整闭包 **14 份**，实际两条资源占用及一条 A1 使用；本案 Reviewer 写入 0，专业 RunReview/Disposition、CAPA 有效性及关闭均未办理。本报告仅验证本地合成业务，不代表实物测试或真实资格。

[独立数据库回读 v2](test-fresh-computed-actual-readback-v2.json)确认 72 笔唯一保存组：70 笔业务/宿主命令各有一个 RequestKey、Audit、Outbox；实际后台扫描/解析两笔按现有 worker 合同 RequestKey 为零、Audit/Outbox 各一个。最初统一要求 RequestKey=1 的脚本假设被实际记录否定，诊断日志与不完整 v1 留存，v2 为采用的核验。原始报告字节及扫描器证明见[实际扫描/解析](test-fresh-actual-scan-parse-readback-v1.json)。

内部 checkpoint 随完整原件和恢复材料超过 2 MB，首次确认在发 HTTP 前被旧内部读取上限拒绝；仅内部 checkpoint 限额对齐为 8 MiB，并在写前检查。通用私有材料仍为 2 MB、原报告仍 200 KB，600/文件所有人/常规文件/非符号链接守卫保持；同一原确认、原正文、原请求键成功保存。实际 43 项 Fresh、123 项 Retest 禁连接检查一起 166 项通过，不与原波检查相加。[修复应用](control-bound-repair-application-v1.json)与[16 文件控制目录 v4](control-candidate-source-v4.json)为对应证据。

[首轮封存](test-fresh-first-closed-checkpoint-v1.json)固定实际 checkpoint SHA；[保留检查 v4](retained-case-exclusion-v4.json)在下一运行源码改动前确认列明 24 张旧表和 6 类 CAPA 排除本案新 Product 后、9 份旧私有文件及 544 份列明核心源保持。随后独立接入 preview-only Plan 重复读取修复及持久根锚修复，源增量另见[受控应用](preview-anchor-controlled-application-v1.json)，不能用旧 544 份源证据宣称新候选冻结。

下一步：本案实际问题分流、CAPA/具名根因及本人完成、独立 A2 正式请求和复测、完整观察与独立 T2 Review。调查分类不推定正式变更履行；真实资格、完整八 facet、正式实施、有效性/分别关闭、G0～G5 与原人工出口仍未完成。并行候选仅在明确独占目录建设，公共接线与运行验证由主线统一办理。
