# 产品经理闭环 · 内部规格书浏览器下载与PDF分页

2026-09-29检查点，0404工作树，接续[导出内容与恢复验证](export-recovery.md)。仅补内部规格输出的实际浏览器与PDF视觉检查，原N项、SHADOW与人工出口不变。

## 发现与修复

实际下载的PDF出现只有一行“不适用说明”的孤页。原因是长审核记录与章节标题的分页约束连在一起，将后续内容整体推到下一页。PDF正文改为按最多4行分段，再保留既有长文本分块；不改来源、规格字段、模板合同或已保存文件。

同一已发布合成定义重新生成后由11页降到9页。用PDFium渲染并逐页检查全部9页：中文可读，正文、页码、签核记录无截断或重叠，原孤页消除。图像见[第1–2页](../../../../output/playwright/pm-export-browser-0404/pair-01.png)、[第3–4页](../../../../output/playwright/pm-export-browser-0404/pair-03.png)、[第5–6页](../../../../output/playwright/pm-export-browser-0404/pair-05.png)、[第7–8页](../../../../output/playwright/pm-export-browser-0404/pair-07.png)、[第9页](../../../../output/playwright/pm-export-browser-0404/pair-09.png)。本机Poppler缺少Adobe-GB1中文字映射而产生空白渲染，改用PDFium复核；该工具问题未计作产品内容丢失。

## 浏览器与文件核对

- 使用已保留的57433合成业务链，产品定义 `39860b64-afd6-4723-90e8-07273112fe8b`，修订2/内容9。页面查找版本→选择PDF→预览原规格（110kPa、±5kPa、25℃、105–115kPa）→人工勾选核对→保存→下载本次已保存文件。
- 修复后回执 `2a08a17b-d06a-47b0-b892-4fa969955f70`，实际文件18733字节、9页。页面重新加载后，重新选择该定义，通过“查看已生成文件”下载历史原件，字节与首次下载完全一致。[历史页面截图](../../../../output/playwright/pm-export-browser-0404/history-ui.png)、[首次下载](../../../../output/playwright/pm-export-browser-0404/download-final.log)、[刷新后下载](../../../../output/playwright/pm-export-browser-0404/history-download.log)。
- 两次生成文件分别与数据库保存记录的SHA256及字节数一致，两个来源快照完全相同。去除各自导出回执、精确页脚与空白后，分页前后全文一致，缩减页数没有删去规格或签核内容。[完整对账](../../../../output/playwright/pm-export-browser-0404/receipt-and-content-verification.json)。旧11页文件仍按原记录保留。
- [浏览器控制台](../../../../output/playwright/pm-export-browser-0404/browser-console.log)未记录错误或警告。专业评审、发布、确认及证据均为合成测试动作，不代表真实角色签核。

## 验证范围与收尾

- [完整前端构建](../../../../output/playwright/pm-export-browser-0404/build.log)通过；分页修复后前端未再改变。后端[8项多格式长文本/回执回归](../../../../output/playwright/pm-export-browser-0404/format-tests.log)、[ruff](../../../../output/playwright/pm-export-browser-0404/ruff.log)、[受影响类型检查](../../../../output/playwright/pm-export-browser-0404/mypy.log)通过。前轮10项接口/文件及14项前端/代理证据按原候选保留，不宣称本轮全部重跑或完成联合门禁。[本轮源摘要](export-browser-source-sha256.json)。
- 本轮API显式使用57433/pdos_test，执行前核对0404；禁用应用.env加载，使用本地合成文件存储。未在该样本库执行清空fixture，仅通过产品页面生成两份合成内部PDF，SQL仅只读核对。57432未操作。
- 自建8124 API、3104前端及pmexport浏览器已关闭；57433业务样本和生成文件继续保留。[收尾记录](../../../../output/playwright/pm-export-browser-0404/cleanup.json)。没有生产操作、模型调用、业务外发、git push或golden-case写入。

本轮仅完成PDF视觉与实际下载检查，未声称Word/Excel/PowerPoint均已完成视觉验收，也不是全产品冻结候选联合验收。真实研究服务与公开主题/网址、逐能力真实评测和资格、RFQ四类名称、真实角色试用及人工Exit仍待补。
