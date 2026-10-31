# 相似历史剩余页面：前端检查点

已补齐 Change 固定版本详情侧栏，以及新建 Issue/Change 表单的标题防重复提示。直接应用的 15 个前端输入、原/新 SHA 见[输入清单](frontend-inputs.json)，完整窄差异见[patch](frontend-completion.patch)。服务端接口与迁移由主会话及另一代理负责，本报告不声明 HTTP/数据库或浏览器已通过。

Change 在项目专业记录的“变更”列表详情及原失败调查/变更办理面板中，使用所选真实 `change_id` 和固定 `version_id` 读取。卡片复用原结构化事实、未知项、原对象链接与小Pai比较预填；预填标为待重读的对象元数据，不成为引用或执行权限。Change 不展示问题归并，BFF 同时拒绝 `merge_prepared`。保存后真实详情的“不相关”和打开反馈沿原六字段、同请求恢复与撤权隐藏行为办理。

标题输入以 400ms 防抖调用只读 GET，空白与超过 240 字符的标题不请求、不静默截断；切换标题、类型或项目立即隐藏旧卡，迟到响应不能替换当前范围。最多五张卡，保留部分覆盖/未记录提示。未保存表单只有原对象链接，没有反馈、归并或小Pai启动操作；标题提示不阻止原生创建，也不改写其预览、确认或来源读集。

三条新增 BFF 为 Change GET、Change feedback POST、标题 GET；标题请求只接受 `kind/title/project_id?`，固定详情只接受 `version_id`。全部使用当前会话 cookie 与 no-store，不转发浏览器自报身份、上游私有头或跳转。空/未知范围由原服务器 RLS 判定，不新增授权。

最终同候选定向验证：

- [44 项前端检查](frontend-tests-final.txt)通过：原卡片 7、标题组件 5、lib/BFF 10、实际专业记录入口 6、原 AppShell/Pai 16 项；各文件只计一次。
- [完整 TypeScript 检查](frontend-typecheck-final.txt)通过：`tsc --noEmit --incremental false`。
- [11 个生产 TS/TSX 文件 ESLint](frontend-eslint-final.txt)通过，无警告。首次同步渲染 helper 被 React compiler 判定可能在 render 执行含 ref 的事件闭包，已改为标准 JSX 子组件，未添加豁免。原失败见[首轮 lint](frontend-eslint-run1.txt)。

[首轮组件检查](frontend-tests-run1.txt)的唯一失败来自 VM 测试与宿主 Error 类型不一致；仅为夹具注入同一 Error 构造器后，[第二轮](frontend-tests-run2.txt)44 项通过。随后 JSX 调整后的最终 44 项再次通过；不把这几轮相加。

待主会话集中验证：真实 Change 固定历史详情与反馈刷新；原 Issue 归并仍进原 T1；实际 Issue/Change 新建标题的只读提示和空/超限状态；Change 小Pai预填只打开编辑、不创建 Run。构建、真实 HTTP/浏览器及服务端权限/性能验证仍待执行。本轮未访问数据库、启动服务、构建、调用模型或向网络发送请求，合成 BFF 测试使用本地 fetch 替身。
