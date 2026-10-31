# 品类编辑与小Pai创建 · 2026-10-23

用户要求继续简洁风格，品类本身可修改名称和主要场景，并能通过小Pai新建。

品类标题旁增加轻量编辑按钮，复用两字段侧边表单，含取消、未修改禁用和重名校验；保存保留稳定ID与资料关联，同步列表、提案显示和当前小Pai上下文名称。新建面板支持「与小Pai一起创建」，独立对话也可发起；候选可直接编辑或通过对话补充，缺失信息不补造，核对共享内容去标识后一次确认创建并进入品类。历史候选、取消、重名、离线、角色限制和创建回执均保留。

验证：26项浏览器交互/布局检查通过，详见 [browser-checks.json](browser-checks.json)；覆盖改名同步和资料保留、小Pai两入口/补充/确认/取消/回执、离线与无权限角色、390px手机编辑和创建。桌面及明暗截图保留，浏览器无 warn/error，见 [browser-logs.json](browser-logs.json)。最终 `pnpm exec tsc --noEmit` 和 `pnpm exec eslint src/app/ui-lab/platform` 均退出0。初次规则解析把「一个」误作名称，修正后用空候选浏览器检查通过；初次 lint 提示会话排序函数的 Date.now 纯度，改为纯状态内单调活动序号后通过。

截图：[编辑品类](edit-category.png)、[新建入口](create-entry.png)、[小Pai候选](pai-category-candidate.png)、[创建结果](pai-created-category.png)、[暗色](pai-dark.png)、[手机候选](pai-mobile.png)、[手机编辑](edit-mobile.png)。

边界：全部为本地合成预览，刷新重置；对话规则仅演示交互，无真实模型、研究、业务写入或权限授予。本次不宣称正式持久化或阶段验收完成，待用户预览确认设计。
