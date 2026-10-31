# 完整产品 UI 设计候选 · 交付与验证

**后续修订**：用户已确认小Pai的通用聊天方向，当前实现与增量验证见[小Pai访谈修订](xiaopai-revision/result.md)。下方是初版候选记录，原小Pai弹窗与后台按钮演示已由新工作区取代；旧全页面覆盖不自动作为本次候选的重跑证据。

日期：2026-10-23。入口：[完整体验预览](http://localhost:57859/ui-lab/platform)。[完整设计说明](../../../design/2026-10-23-pdos-full-product-ui-candidate.md)。

## 交付

以使用者当前责任为入口的完整体验设计，覆盖九岗位、17 个页面、45 个页面/子视图状态。全局四入口，项目六个常用视图，小Pai按需打开。支持主题、窄屏、角色和异常状态切换；这些选择器仅属于设计评审工具。

代码范围：`pdos-next/web/src/app/ui-lab/platform/`，其中 `design-data.ts` 为明确标记的合成案例，`platform-preview.tsx` 为可交互原型，`platform.module.css` 为局部样式，`page.tsx` 限制 localhost/127.0.0.1 Host。基线与 v1.1 不变，真实业务页面未替换。

## 验证

- **最终类型检查**：预览范围 `tsc --noEmit --project /tmp/pdos-platform-tsconfig.json` 退出 0；全仓 `tsc --noEmit --incremental false` 最终退出 0。早期检查曾发现另一测试文件类型错误，最终候选复核已不再出现；本轮没有修改该测试文件。
- **Lint**：新增 TS/TSX 文件 eslint 退出 0。没有新增依赖到项目清单；Prettier 仅用于格式化候选文件。
- **HTTP**：[http.json](http.json) 记录本地入口 200，页面含完整体验标题；非本地域名 Host 返回 404。
- **桌面/手机**：1280×720 亮色、390×844 暗色分别遍历 17 页面 / 45 个视图状态。手机阶段页的表格最小宽度问题已修复并重新核对；主内容均无横向溢出，长表格在容器内滚动。最后针对紧凑项目首屏、阶段与门禁、双线影响再次检查手机布局。
- **关键交互**：计划一次确认及原承诺保留、Lot A 四件接收与 Lot B 剩余、工程/制造分别签署并跨角色保留、只读身份入口、外部导航/动态范围、离线禁用、版本比较与草稿保留、读取失败、权限失效、小Pai后台接续与运行范围固定、最终摘要精确范围、Escape 关闭并归还焦点、Ctrl K 搜索。
- **最终首屏**：1280×720 项目“现在”页中，下一轮 Build 及关键承诺四字段均在主视口内；切换页面/项目/角色重置内容滚动位置。
- **控制台**：最后读取 error/warn 日志为空。完整记录在 [browser-checks.json](browser-checks.json)。
- **Impeccable**：完成一次 context.mjs 与一次手动 detector；[detector 结果](impeccable-detector.json)为 `[]`。按技能指示做一次独立只读收尾审阅，[问题与修复](finish-review.md)已记录；未重复运行 detector。

检查日志空文件表示命令无错误输出；退出码另记录于 [verification.json](verification.json)。没有运行数据库、模型、真实签署/发送或阶段验收；未为展示变动增加镜像测试，没有重复跑生产构建或后端全套。

## 截图

- [本人工作 · 亮色](work-light.png)
- [项目现在 · 亮色](project-light.png) / [暗色](project-dark.png)
- [双专业决定](dual-decisions.png) / [手机](dual-decisions-mobile.png)
- [精确接收的最终确认](receipt-confirmation.png)
- [手机本人工作](work-mobile-light.png) / [手机阶段与门禁](stage-mobile-dark.png)
- [小Pai与当前范围](pai-context.png)

## 边界与恢复

全部办理只改变当前标签页 React 状态，刷新重置；未调用真实业务 API、模型或数据库。部分文件/发布/治理入口只展示设计说明。P1 为专业流程主案例，S2/D3 展示项目范围摘要；原型角色选择和隐藏入口不构成生产权限验证。后台工作由预览按钮模拟推进，不代表 Temporal/模型已执行。真实业务接入与阶段验收仍按 v1.1 和唯一清单推进。

这次使用已运行的 57859 本地服务，未重启或改动其实际业务环境。旧 59650 服务未运行；不要再使用该端口的旧预览链接。本入口已通过浏览器实际访问，并作为交付标签保留。

如服务后来停止，可在 `pdos-next/web` 执行以下命令恢复同一本地入口（先确认端口未被占用，不启动重复实例）：

```sh
PDOS_NEXT_PREVIEW_CONFIG=1 npm run dev -- --hostname 127.0.0.1 --port 57859
```

此路由只使用本地合成数据，不需要启用模型或数据库。截图和设计文档在服务停止时仍可查看。
