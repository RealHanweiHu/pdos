# C / E / F 实际原生浏览器记录

2026-10-29 14:24–14:38 UTC，实际 Web `http://127.0.0.1:50780`，root fixture API `http://127.0.0.1:50795`。fresh `web-verified.json` 已确认浏览器所属本人；使用独立 Playwright CLI 会话 `cef-native-cui-20261029` 加载 root 的 storage.json，未复制或打印 Cookie。操作只走原生页面表单与页面导航，没有手工 API、provider probe、新聊天或摘要手动运行。root 的 MemoryKms / 合成来源及拒绝真实 provider 的 fixture 维持原授权边界。

这份记录证明实际 UI 行为。浏览器步骤完成后，root 创建 finish；原生 fixture 实际 exit 0、native_ui_checks_passed=true。非秘密的最终 DB/回执计数见 [原生 fixture 摘录](native-fixture-public-summary.json)，登录对应关系见 [web-verified](web-verified.json) 与 [ready 非秘密子集](ready-public.json)。本代理未创建 finish，未写 fixture result.json。G 的实际用例证据独立记录，本次没有真实钉钉操作。

## C 独立 Embedding

1. 设置 → 小Pai与模型 → 模型配置 → 企业资料 Embedding → 新增独立连接。
2. 填入 root 的 `.invalid` 合成 endpoint、独立模型 ID/版本和合成 Key；展开价格与计量，填写已授权合成价格、每字节 token 上界和额外封装上界，再安全保存。UI 显示“独立连接已安全保存，当前聊天模型保持原选择”，并自动带入公开连接 ID。没有点击模型切换或探测。
3. 维度 2、预算 1 USD；仅内部资料勾选，客户原件与后台启用均未勾选。点击核对配置并预览；[实际预览](c-profile-preview.png)列出 custom.invalid、独立模型、2 维、内部、客户原件不包含、独立凭据已绑定、停用保存和预算 1。点击“本人一次确认保存”一次。
4. 页面刷新后重新进入模型配置，[读回](c-profile-after-refresh.png)独立 profile 第 1 版已停用、2 维、凭据已绑定；预算 1，已计费 0、占用 0、无后台批次及 0 条调用记录。页面默认关键词说明保留。

公开连接 ID：`46aaf053-b2a7-523a-a7c7-ec4640870df2`。未把原始 Key、密钥引用或 storage 状态写入证据文件。截图包含真实当前 UI 的 sticky header；当前版本及预算结果可读。[刷新后的完整快照](c-profile-after-refresh.yml)。

## F 原个人回答保存知识与补充请求

1. 小Pai → 已有会话“以前漏气怎么处理？”，读取原完成回答“参考固定记录：更换密封圈。”，展开真实固定来源“浏览器核实：漏气处理记录 · v1 · line:1”。没有发送新消息。
2. 在“知识沉淀与补充”明确选汽车充气泵，选择“存为公司知识”；负责人为实际 Synthetic owner，填写“仅用于本地合成漏气案例讨论”、复核日期 2026-11-05，保留原回答和 1 项已核来源，点击“保存知识”。实际 UI 直接显示[知识已保存](f-answer-saved.png)，没有另弹 COMMON 确认框；这里如实记录 Human 整理表单与保存，不声称出现额外弹框。
3. 通过“打开知识”进入普通知识页并刷新，点“核实答案”，展开[已保存 v1](f-knowledge-after-refresh.png)：原问题、答案内容、适用范围和复核日期仍可读。[完整快照](f-knowledge-after-refresh.yml)。
4. 从原生会话列表重新打开同一原回答，再次明确选择目标品类；“请补充资料”先显示实际品类和实际负责人，点击“提交补充请求”。页面显示[已提交给品类负责人](f-gap-submitted.png)。
5. 随后刷新页面并查看普通收件箱/我的工作，未找到该补充请求的持久 UI 列表；没有据此重复提交、没有用 API 代替 UI 读取。root 的原生 fixture 最终已核验实际 gap 1 条及其正确归属。本段不宣称补充请求在刷新后的普通 UI 中已重读。

原个人 Session `fd7585d9-03a3-41ed-921a-472775187b04`、Run `2797c883-220f-4999-a34c-c60b09d98d63`；目标品类 `e3534751-fd75-4f57-b1fc-077ba2ebb5c6`。

## E 零技能、零钱包摘要订阅

1. 设置 → 小Pai与模型 → 自动化规则。原生“规则工作”选择“本人结构摘要（不调用模型）”，不选择通用模型工作。选“我的工作 · 四问三组”、每个工作日、09:00 America/Los_Angeles；经“读取本人可见项目”选真实“浏览器本人摘要项目”。没有启用技能、开钱包或补模型预算。
2. 填写规则名“浏览器零技能零钱包摘要”，点击“预览摘要订阅”。UI 先保存 draft v1，并展示[固定版本预览](e-summary-preview.png)：三组、1 个本人关注项目、工作日、每次 100 条/最多 52 次；明确“确定性摘要不调用模型，不使用模型预算”，实际服务身份由服务器准备。点击“确认此次规则状态变更”一次。
3. 页面刷新，重新打开自动化规则，[读回已启用当前 v2 和活动服务授权](e-summary-after-refresh.png)，已受理 0 次。展开[已发布固定声明及版本历史](e-summary-declarations-history.png)：skill_keys=[]、validation_budget_id=null、费用/输入/输出/call_limit 均 0；实际 followed_project_ids 为 root 的真实项目；draft v1 与 activate v2 的原生 Human 回执均在历史中。[完整快照](e-summary-declarations-history.yml)。
4. 本次未点击手动运行，没有产生可声称的摘要实际执行结果。该项 UI 验证范围是原生创建/预览/一次确认启用与刷新读回。

规则 `85a14a6f-14d6-470f-a8be-4e542b8113de`，活动固定版本 `ffadab63-f51f-4117-8541-45ba9c0f4e93`；draft 回执 `928f96ab-b6f2-4ddd-a850-48e0157021e2`，activate 回执 `85f1bef5-03ef-4ac7-8985-de83d962f2b0`。

最后当前页面 console 检查为 0 errors / 0 warnings；不把刷新后的 console 清空等同于全部历史页面没有日志。CLI 过程中一次选择值不匹配、一次目标快照外的旧 ref、一次误选截图 ref 均未形成业务写入；正式证据仅保留正确截图。其余操作没有发现阻断 C/E 表单或 F 保存的明确产品错误。F 补充请求刷新读回的 UI 证据限制已单独报告 root。

## Root 原生 fixture 最终核验

root 在 UI 完成后统一创建 finish，实际测试 exit 0、native_ui_checks_passed=true。已核对：知识 1 / Human review 1 / gap 1；摘要 draft→active 共 2 版本、服务 Grant 1；managed connection 1 / KMS write 1 / embedding profile 1。原个人 Run 与回答保持，Artifact 仍 1；无新增 generic Run、无模型钱包或技能 enablement、无 EmbeddingCall；浏览器 model/embedding provider attempts 与真实 provider 调用均 0。没有手动摘要执行，summary_runs_count=0。上述数字来自 root 生成的 result.json，公开摘录附原文件 SHA256；未复制 storage、Cookie、Key、DSN 或整份原始凭据资料。
