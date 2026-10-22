# S4 空范围检查修复与两专业页面批准（2026-10-17）

已修复批次、产线明确为空时政策检查被过滤、汇总误报 READY 的缺陷。新候选实际读取并保留工程与制造各一项具名政策检查，两位合成人员通过实际页面分别确认 T2；工程成功响应丢失后，刷新零命令提交，显式重放仍返回同一份决定。S4 保持未验收。

两个范围维度都明确为空时，仍比较其余范围并保留相应检查；空值不扩展为全部。政策读取依据版本从内部 read-v1 改为 read-v2，使旧依据必须复核，原 Fact、固定包及决定均不改写。本次没有 schema 迁移。

- [最终候选](candidate.json)：`trfrp7t8`，归属为 8 个后端/测试文件；[静态检查与精确摘要](static-02.json)通过。其他待提交 M2/M3/UI/外部交付文件只作为已记录上下文，排除本次交付。
- [受影响纯检查](pure-02.json)／[日志](pure-02.log)：136 passed，包括空批次/产线的 satisfied、unknown、blocked 保留，以及所需原件缺失保留 unknown。[独立拼装](delivery-pure-02.json)／[日志](delivery-pure-02.log)以 HEAD `dab6b64` 加 8 个精确归属文件移除其他未提交上下文，136 passed，零数据库连接；两组结果不累加计数。
- [实际页面与 PostgreSQL 联验02](finite-API-02.json)／[日志](finite-API-02.log)：1 passed，335.08 秒包含有限页面等待，不是性能验收。新固定包保存前，断言工程 `engineering.fixed_document`、制造 `manufacturing.fixed_publication` 各有且仅有一项 satisfied/applicable 检查；[预览前实际读取](read-fixed-before-preview.json)显示零决定、零确认。
- 工程本人预览后一次确认，[实际后端 200 响应被丢弃](browser-response-loss-02.log)；[此时实际读取](read-engineering-saved-response-lost.json)已有一份工程决定和一个已消费空期限证明。[刷新观察](browser-refresh-02.log)命令 POST 为零，只显示显式恢复入口。本人点击重放后，[完整工程决定相等](read-engineering-explicit-replay.json)，未新建工程决定或工程证明。该读取与制造预览并行，因此其中已出现一个未消费制造证明，不能据此声称整库证明数不变。
- 制造由另一具名人预览并一次确认。[两份实际决定](read-two-independent-decisions.json)、[制造页面](manufacturing-after-decisions.snapshot.log)与[截图](two-independent-decisions-light.png)保留；两人分别匹配实际专业 Authority 与单一 signer，两个证明均 consumed、expires_at=null，每份共同 Receipt/Audit/Outbox 均由 fixture 实际核对。工程恢复页面见[原提交核对结果](engineering-after-decisions.snapshot.log)。外部接收、生效仍为 false，客户承认为 null。
- 页面完成后同一 fixture 继续政策撤回及旧政策重放：原两版包、两份决定保留，读取需复核，旧回执不使 Current 回退。[收尾实际核对](cleanup-02.json)确认政策 active v1 / withdrawn v2、固定包 v1/v2、两位本人两份已消费空期限证明。API 已退出，专属 Next 与两个测试浏览器已关闭、cookie 清除、私有 bearer 删除，数据库与既有备份保留。
- [前端复用依据](frontend-build-reuse.json)：发布实际运行输入与先前已构建候选逐字一致；本次没有前端改动，不重复构建或全尺寸/全主题回归。截图已检查，可见两项实际规则和分别记录的决定。浏览器原有 favicon 404 及刻意丢弃响应造成的错误不作业务失败。

失败如实保留：[首次候选](candidate-pdos-release-decision-browser-qj8wjfoq.json)、[预览前读取](read-before-preview.json)显示空 checks 却汇总 READY；当时尚无批准/确认，立即停止。因没有提交两份决定而触发的 fixture 末尾断言失败见[日志](finite-API.log)，[中止记录](aborted-before-T2.json)保留。前一轮 release-policy 的 actual-decisions-02 仅断言汇总 READY，不能证明政策规则被实际执行；此次新增逐项断言和真实页面证据纠正该覆盖缺口，不改写旧原始日志。

所有实际数据库操作先核对 `127.0.0.1:64245/pdos_test`、marker `f9048729-3f2a-4494-af75-56e1db7d743d`、head `s0_0782`。未删库、回退历史或覆盖备份。本轮浏览器分支没有重复前一 API 分支的制造尾部失败注入，不宣称新增覆盖该场景；也不宣称整仓回归、正式资源资格、生产放行或阶段验收通过。

下一步继续受控交付 manifest、外部编号/版本映射、接收与生效分立的实际 owner/存储/API。其纯合同与存储声明正在独立施工，尚未启用外发或作为已可用业务能力交付。S3 一天观察及独立评效、S1 真实模型/资格与正式阶段验收保留；性能验收暂缓。真实模型、KMS、外发、push、部署及生产操作为零。
