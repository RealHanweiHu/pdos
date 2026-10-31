# 品类创建与资料维护预览 · 2026-10-23

按用户要求完善 `/ui-lab/platform?view=category&role=product`，采用既有 Impeccable/Linear 简洁方向。仅改本地设计预览，未访问数据库、调用模型或写入正式业务。

## 可用能力

- 新建品类：名称重名校验、主要场景、空资料与空型号；新建品类可用于提案与小Pai上下文。
- 竞品库：新增、修订、撤回、查看撤回和恢复；来源、宣传/实测/推断、报价与税运口径；当前有效记录同步到矩阵。
- 用户声音：维护摘要、场景、来源、样本量与适用边界。
- 规格字典：新增参数、稳定键唯一与只读、追加参数版本；旧提案引用固定版本。未给定方法或条件保留未知。
- 统一侧边编辑面板与折叠历史；离线允许查阅、禁止维护。

## 验证

27项不同交互/布局检查最终通过，完整记录见 [browser-checks.json](browser-checks.json)。其中3项初始断言因精确文案不匹配误报（样本量显示为「6 份」、小Pai按钮文本、提案品类处于组合文字），重新使用实际可见文本和完整快照复核通过；原断言与对应复核均保留。浏览器操作中也修正了 tab/button、撤回后带状态名称、标签及重名匹配等定位问题，未将失败操作计为通过。

验证链包含创建自行车充气泵 → 新增/修订/撤回/恢复竞品 → 新增用户声音 → 新增/修订参数 → 新品类提案；另将汽车品类 PAR-08 从 v2 修订为 v3，确认已批准 P1 提案仍引用 v2。桌面明暗及390px手机列表/面板检查通过。最终重名提示修改后的复查通过。

最终 `pnpm exec eslint src/app/ui-lab/platform` 与 `pnpm exec tsc --noEmit` 均退出0；测试与交付标签页未见 warn/error，见 [browser-logs.json](browser-logs.json)。未进行无关全构建或后端测试。

截图：[品类新建](new-category.png)、[竞品列表](competitor-list.png)、[竞品维护](competitor-editor.png)、[用户声音](voice-editor.png)、[规格字典](parameter-list.png)、[暗色](parameter-dark.png)、[手机](parameter-mobile.png)、[手机维护](parameter-mobile-editor.png)。跨页证据：[新品类提案](new-category-proposal.txt)、[小Pai上下文](new-category-pai.txt)。

## 边界与下一步

全部为合成状态，刷新重置；未接入真实品类权限、资料持久化或领域命令。用户可预览确认交互方向，正式接入另按冻结架构实施。本次没有新增阶段批准或声称阶段验收完成。
