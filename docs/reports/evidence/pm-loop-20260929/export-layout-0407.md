# 产品经理闭环 · Excel 可见续行与 PPT 版面检查（0407）

2026-09-30，接续[独立影子评测](shadow-evaluation-0407.md)。本轮补 N1-06/N7-01 产品定义导出的版式缺口；数据库仍为0407，无迁移、数据库操作、模型调用或真实业务出站。

## 实际问题与修复

原 Excel 按2000个字符拆单元格，没有约束实际行数。110行的来源原值大部分进入同一个单元格；LibreOffice 渲染时文字落到页面之外。普通 PDF 文本抽取仍能读到部分不可见文字，因此不能据此声称版面完整。[修复前第六页](../../../../output/pm-export-layout-0407/before/xlsx-render/boundaries-sixth.png)及[页面可见范围核对](../../../../output/pm-export-layout-0407/visible-lines.json)确认：110行中只有52行完整可见。

现在按换行和中文/全角宽度估算可见行，每个单元格最多12个估算行，并显式设置行高。长章节标题完整移入正文，左栏保留短标签及续行编号；每页重复表头。原文字符、顺序、空白和固定记录保留，公式样式输入仍为字符串，无公式或自动超链接。修复位于 `server/app/exports/definition_documents.py`，也作用于复用该渲染器的内部/客户报告；字段、受众和批准规则保持原合同。

## 当前候选证据

- [输入与模式](../../../../output/pm-export-layout-0407/input-manifest.json)：直接使用当前生产渲染器及已留存的合成已发布定义快照，并加入长中文、多行和公式样式边界材料。不是新保存的API导出回执或真实业务材料。
- [11项受影响检查](../../../../output/pm-export-layout-0407/unit-tests-final.log)通过，覆盖四格式、内部/客户、长来源、原值不执行、换行密集记录及长标题；[lint](../../../../output/pm-export-layout-0407/ruff.log)与[渲染器类型检查](../../../../output/pm-export-layout-0407/mypy.log)通过。开发首轮的新增测试误选起始行，修正测试选择后通过，原失败日志保留。
- [内容与版面核对](../../../../output/pm-export-layout-0407/content-and-layout-verification.json)：Excel完整定义的22段原值可精确拼回，14个导出引用编号在可见页面中找到；最大行高216pt，无公式或超链接。修复后的110行全部可见。完整定义16页与边界材料11页已逐页查看渲染图；可下载[合成定义工作簿](../../../../output/pm-export-layout-0407/after/definition.xlsx)。
- PPT完整定义43页、边界材料21页均已查看渲染图，长标题/续页及页脚未发现裁切或重叠；两份[结构检查](../../../../output/pm-export-layout-0407/ppt-structure-before-installed.log)、[边界结构检查](../../../../output/pm-export-layout-0407/ppt-boundaries-structure.log)通过。修复前后所有PPT包内部分完全一致，复用同一渲染结果，没有改动PPT生成分支。
- [2798份源摘要](../../../../output/pm-export-layout-0407/candidate-source-sha256.json)匹配；相对上一候选仅渲染器与其测试文件变化，见[候选变化](../../../../output/pm-export-layout-0407/candidate-transition.json)。本轮11项验证不与旧179项影子评测覆盖合并成一次全量通过。

以上版面使用 LibreOffice 和本机字体替代进行渲染，未验证原生 Excel/PowerPoint 程序；未将转换后的PDF保存成业务导出。旧Word/PDF证据及原导出文件继续作为对应历史候选，本轮前端与业务接口未改，不重跑旧浏览器或数据库测试。QA依赖仅安装到本轮输出目录，收尾删除该临时依赖目录，保留安装记录与结果。

## 剩余与下一步

真实研究仍需允许的主题/材料和搜索服务；真实模型执行需有效计量配置、当前调用授权，以及八能力独立人工参考集和原服务商调用证明。RFQ四类原名称、真实专业协审/角色试用和人工Exit仍待补。八项能力保持SHADOW，N1-01～06/N6-04及完整N7-01出口没有关闭，目标尚未全部完成。
