# 产品经理闭环：原文选择、原运行入口与派生候选恢复（0413后续候选）

2026-09-30。本轮沿产品经理第一开发主线补齐四处实际办理缺口，源head保持0413/414步，没有新增迁移或验证数据库版本。N1-01～06、N6-04及原N/P/Q仍部分完成。

## 本轮可用能力

1. 私人附件分析须明确选择本会话、当前可读的实际原文片段。前端分页可选第四段及后续段，消息固定原CID、附件ID及ordinals；新消息不再自动取前三段。整份附件未选片段或未覆盖全部已选附件时，保存私人说明并提示补选，不创建分析请求；普通说明可留存机密/受限附件，模型分析仍仅允许已解析、未撤回的内部原件。错CID、未绑定附件、重复或缺失片段在写消息前拒绝；原消息未知响应重试固定全部选择及请求，不能换段。
2. 产品工作台消费小Pai结果链接中的实际run。研究规划与RFQ各自读取真实能力/Line匹配的原运行；RFQ私人原件的真实Finding由原T1候选入口一次确认需求草稿，不改成共享文件。矩阵同时绑定原record_id与run_id，只读取实际解释，不重新生成。新增只读product-ai-run-read仅接受run_id，在同一REPEATABLE READ事务从本人、tenant/Space、agent/version/scope/projectnull原行派生能力与Line，再沿当前身份/范围授权、来源重验与原快照绑定返回原history形状。URL不赋予权限；同范围A→B切换丢弃旧运行的迟到响应，未决写入/确认保持原请求。
3. 新私人来源链接携带经服务器核对的Space/Line及CID/附件/片段；旧冻结链接通过授权GET原会话恢复实际typed scope，保留same-scope守卫。新含私人来源的快照记录scope.v1链接投影；无标记旧快照按原格式复建，原事实未变则旧digest不变。尚未首次派发的旧请求也仅在当前真实legacy摘要精确匹配时续接；内容或权限变化仍拒绝。旧/新同selection历史按链接投影分别缓存当前摘要，不误报陈旧；不改写旧快照或忽略链接哈希，无私人来源的pack结构保持原样。
4. 派生产品首版缺少锁定父定义时，结构化定义候选在入Finding及接受/应用重验时提前拒绝，并导向原“从当前发布父定义派生”人工入口。已具同产品已发布原版的派生修订继续沿原稳定条目及权限守卫。AI不代选父版或执行T2发布；当前最新父版、继承合并及正式发布仍由原领域服务核对。

## 本候选验证

[46份范围源摘要](../../../../output/pm-loop-entry-recovery-0413/source-candidate.json)与[核对摘要](../../../../output/pm-loop-entry-recovery-0413/verification.json)界定本轮证据；本轮20份运行源加受影响测试/支持源，非46份全部新增修改。

- [161项后端纯检查](../../../../output/pm-loop-entry-recovery-0413/backend-pure.xml)通过：实际会话适配、明确片段/重试/错范围及撤回边界、私人附件、矩阵适配、旧/新来源摘要兼容、派生候选与单事务原运行读取。Engine.connect及socket.connect/connect_ex拒绝探针开启，数据库变量移除，无数据库或模型连接。[13文件严格类型](../../../../output/pm-loop-entry-recovery-0413/backend-types.log)、[lint](../../../../output/pm-loop-entry-recovery-0413/backend-lint.log)、[格式](../../../../output/pm-loop-entry-recovery-0413/backend-format.log)通过；follow-imports=silent不代表全后端导入诊断通过。
- [14文件132项不同前端/BFF检查](../../../../output/pm-loop-entry-recovery-0413/frontend-components.json)在本次冻结源通过：原文第四段/后续分页、未知原请求、旧CID原片段恢复、实际RFQ候选一次确认、wrong Line不露候选、research不伪装RFQ、原矩阵run、父URL入口与迟到响应。[21文件lint](../../../../output/pm-loop-entry-recovery-0413/frontend-lint.log)、[完整前端类型](../../../../output/pm-loop-entry-recovery-0413/frontend-types.log)通过。首次父矩阵检查失败来自测试身份模块缺isRecord的全量mock，已改部分mock保留实际工具；[失败原日志](../../../../output/pm-loop-entry-recovery-0413/frontend-workspace-rejected.log)保留，最终父入口13项包含在132项中，不额外叠加计数。
- [1063份独立前端源冻结](../../../../output/pm-loop-entry-recovery-0413/web-build/source-manifest.json)完成[真实Next/Geist生产构建](../../../../output/pm-loop-entry-recovery-0413/web-build/build.log)，不拷贝.env、不模拟字体，后端禁用。本候选26份前端运行/测试源与构建快照及当前源全部匹配；另20份后端/支持源摘要复核一致。
- [12项真实编译后未登录HTTP检查](../../../../output/pm-loop-entry-recovery-0413/web-build/http-checks.json)通过并已停自有前端：含新原运行读取POST的401、非法扩展与GET拒绝及原会话路径；应用响应no-store，未支持PUT405。只用本机随机端口、无cookie/token、未启动业务后端，不是合法登录或业务浏览器证明。
- [源迁移链](../../../../output/pm-loop-entry-recovery-0413/source-head.json)离线确认0413/414步；没有执行升级、往返或数据库schema相容。[23项PG/API仅收集](../../../../output/pm-loop-entry-recovery-0413/backend-pg-collection.log)，含原11会话、8矩阵与[新增4片段用例](../../../../server/tests/test_product_conversation_fragment_api.py)，未运行fixture或正文。新增用例安排在实库经实际XLSX登记/字节上传/解析取得12片段，仅对象存储为内存替身；待验证第四段/分页、整份说明、固定重试/错CID/缺段/撤回/Line撤权及只读接口输入，不伪造资格或run。

## 余项及恢复条件

按唯一清单由协调会话明确分配并核对独立临时pdos_test，再按届时冻结真实head集中执行升级/往返/schema、23项会话/矩阵/片段、PIE恢复、0409/0408/0407及完整PM合法登录HTTP/浏览器整链。本轮不连接、重启或改动57432/57433/57434/57439/57440；57440属于协调的备份后停止环境，未分配本会话。跨会话发送须直接人类明确授权，此前问题仍待回复，未发送；自动goal续接不构成该授权。

真实研究/搜索及允许材料、计量/模型调用授权、八能力独立人工参考及原始调用证明、RFQ四类原名称、具名专业协审、ERP/PLM主数据原件及人工Exit仍待对应条件。未调用真实模型、授予资格、改变SHADOW、推送、部署、外发或通过人工出口，不能据本轮本地验证宣称全闭环或“今天全部完成”。[0413矩阵候选](conversation-matrix-0413.md)与[0412私人会话候选](product-conversations-0412.md)保留历史范围，不拼接为当前完整门禁。
