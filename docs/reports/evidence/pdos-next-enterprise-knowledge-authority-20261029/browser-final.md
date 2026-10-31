# 实际页面检查 · 2026-10-29

本地 API 58261、生产构建 Web 58262，浏览器实际操作。合成账号与 cookie 仅在私有临时目录；API 的 workflow dispatch 禁用，没有调用真实模型。最终前端为 [687 输入快照](frontend-table-render-build-inputs.json)，[29 文件 262 项测试](frontend-table-render-tests.txt)及[生产构建](frontend-table-render-build.txt)通过。

## 偏好

实际保存、刷新恢复、清空本人偏好；欢迎示例按角色变化，点击只预填，常用品类/项目导航正常。1280px 亮暗与 320/390px 暗色、键盘操作已核对。详见[偏好页面证据](../pdos-next-personal-preferences-20261029/browser.md)。最终缩短文案也已在新构建核对：[截图](output/playwright/preferences-final-desktop.png)。

## 相似历史

实际 Issue 页显示真实可读候选与来源对象，打开原对象成功；“不相关”与打开反馈真实写入本人反馈表。“让小Pai看看”只填自然比较问题，未启动运行。320/390px 无页面横向溢出，宽屏双栏、窄屏堆叠。

在原业务 T1 路径完成预览、取消，再次预览并由页面明确确认归并。实际回执 `17cd2462-8dfa-4f82-ba1a-155618b41e2d`，当前 Issue 到 v2，归并后的历史候选消失。业务回执 67→68；模型调用 0→0、Agent Run 0→0；反馈打开 1、不相关 1、归并预填 2，详见[实际数据库核对](browser-similar-authority.json)和[请求状态](browser-similar-requests.txt)。

- [宽屏亮色](output/playwright/similar-history-desktop-light.png)
- [390px 暗色](output/playwright/similar-history-mobile-dark.png)
- [320px 实际 T1 预览](output/playwright/similar-history-t1-preview-320.png)
- [归并后](output/playwright/similar-history-after-merge.png)

## 结构化回答与保存表格

打开真实完成的“以前漏气怎么处理？”会话，案例表将分析与原文依据分开；缺失项保持待确认。点击引用能打开固定版本原文。320px 时页面宽 320、表格视区宽 278/内容宽 576；聚焦后 ArrowRight 将表格横向滚动 40px，页面宽度不变。

实际页面发现并修复两处问题：结构结果未显示表格入口；保存表格中的 `<br>` 被显示为文字。最终构建打开既有 v1，不产生重复保存；换行按普通文本显示。由编辑器追加备注并保存人工 v2，原 AI 内容仍能展开；刷新、重新打开原会话，再次打开表格仍为 v2。

[修订前](browser-task-authority-before.json)/[修订后](browser-task-authority-after.json)实际只增加一条人工版本：v1 正文 SHA-256 不变，v2 正确指向原 root/supersedes。模型账本 5→5（合成 provider），Agent Run 1→1，业务回执 1→1。[浏览器请求状态](browser-task-requests.txt)。

- [320px 案例表](output/playwright/task-result-narrow-light.png)
- [暗色回答及固定来源](output/playwright/task-result-desktop-dark-sources.png)
- [既有 v1 换行修复](output/playwright/task-result-saved-v1-fixed.png)
- [人工 v2 与原 AI 内容](output/playwright/task-result-saved-v2-original.png)
- [刷新后恢复 v2](output/playwright/task-result-v2-after-refresh.png)

本文是本地合成资料的页面与持久化证据，不代替真实模型质量和正式阶段验收。
