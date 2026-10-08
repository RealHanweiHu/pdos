# 登录即本人工作 · 2026-10-04

用户明确“千人千面”是登录即自己的页面。此次修改截图所在的原 `web/`；没有改变 `pdos-next/` 的授权模型或执行队列。

内部账号本地登录直接进入 `/my-work`，首页解析与钉钉原首页回调也进入同一本人工作台。已验证账号自动组织姓名、岗位相关入口、侧栏和项目初始任务；本人队列仍由原服务器责任与权限生成，实际紧急事项决定执行/验证场景。产品经理的本人研究与定义队列前置并直接可见。桌面、手机取消工作视角选择器，旧浏览器偏好不参与首页决策，详情页的通用工作路径移除。兼任的实际待办、原具名动作、完整计数、分页、草稿与深链保持；管理岗位的项目工作项与资料保留在主导航。本人首页可直接打开既有小Pai。

当前自动映射：产品经理→产品工作；项目经理→项目推进；工程师→工程设计；品质→测试与品质；Owner→管理工作；Admin→系统管理。内部成员都先看到本人的工作，客户和供应商继续进入已授权项目。页面组织不授予专业任命或业务批准权。

## 验证

- 9份受影响前端测试文件、147项不同用例通过：首批83项见[组件检查](components.log)；新增8项登录与11项项目任务、2项立项前队列通过见[分组回归](login-project-regression.log)；项目导航修复后的43项见[最终项目回归](project-regression-final-v2.log)；首页队列前置后的26项见[最终本人工作检查](my-work-final.log)。分组初验的6项失败及随后1项旧默认断言失败保留在日志，最终受影响文件已恢复通过，不将失败计为通过。
- [前端类型](typecheck-final.log)、[受影响规范](lint.log)、[项目规范](project-lint.log)及[最终首页规范](home-lint-final.log)通过。[最终独立生产构建](build-candidate.log)通过；1065份冻结源完成构建，本轮修改范围与当前工作树[核对无漂移](frozen-source-check.json)，[构建源摘要](build-source-sha256.json)与[本轮文件摘要](source-sha256.json)可追溯。
- Playwright 在独立生产构建中实际执行页面，API由本轮合成夹具拦截，未读取或写入业务库；服务的后端地址固定为关闭端口 `127.0.0.1:1`。合成本地账号登录直接落 `/my-work`，六类内部账号分别显示本人姓名、岗位入口和自己的待办，客户落 `/projects`；旧视角偏好不能覆盖。产品、工程、品质的1440px/320px、产品亮暗、手机导航Escape关闭与焦点恢复、小Pai直接打开通过，见[浏览器结果](browser-results.json)、[合成登录](browser-login.log)、[各岗位](browser-roles-v2.log)、[桌面与双主题](browser-desktop-and-navigation.log)及[最终导航](browser-navigation-final.log)。

[产品首页亮色](product-desktop-light.png) · [产品首页暗色](product-desktop-dark.png) · [320px产品首页](product-mobile-light.png) · [工程首页](engineer-desktop-light.png) · [品质首页](quality-desktop-light.png)

测试清单命令一度把清单输出写入本轮测试文件，已将该输出保存为[test-inventory.json](test-inventory.json)，从冻结副本恢复测试文件并核对原摘要；本轮源核对无漂移。浏览器脚本的标题定位与结果/引用解析错误已定向修正，原日志保留；这些夹具错误不作为业务页面失败或通过证据。

## 剩余与边界

收尾时检测到本轮未修改的 `src/app/api/conversations/[[...conversationPath]]/route.ts` 新增reply/SSE相关路由；保留该共享变化，不将其计入本轮构建或浏览器证据。本轮首页、身份路由、壳与测试文件均与冻结源一致。

真实人员、市场空间/项目与兼任专业映射仍按原队列办理。细分工程、PIE和供应职责的自动导航需要真实映射；已有相关待办按原责任保留。此次浏览器使用合成API，不宣称真实身份联验、模型资格或完整千人业务验收，不改变原N/P/Q及65项状态。未运行repo数据库测试、升级业务库、执行真实AI、外发或push；9/27恢复边界保持。

本轮临时3031服务与专用Playwright会话在验证后关闭；冻结前端副本路径见[构建工作区](build-workspace.txt)。原预览服务与数据库未操作。
