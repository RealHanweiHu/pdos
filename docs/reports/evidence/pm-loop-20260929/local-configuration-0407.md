# 产品经理闭环 · 本地启动配置连通（0407）

2026-09-30，接续[导出版面收口](export-layout-0407.md)。沿N0-03必要运行依赖核对产品经理入口，修复本地启动未向模型网关提供根目录配置的问题；无迁移、数据库操作或真实调用。

## 问题与实现

`make dev` 原先在 `server/` 启动 API，但没有加载根目录 `.env` 到进程环境。认证设置自行读取文件，模型目录、预算和计量配置则读取进程环境，因而出现“文件有配置、网关没有配置”的不一致。[只读原状态](../../../../output/pm-local-configuration-0407/configuration-preflight.json)确认：根目录文件有两个服务商，当前裸进程目录只有零个。新增启动参数断言在原入口[三项复现](../../../../output/pm-local-configuration-0407/reproduction.log)中均失败。

现在 API 与提醒进程使用 `uv run --env-file ../.env`，从已固定的服务目录读取同一根目录文件；直接启动API的说明也同步更新。使用相对文件名避免当前启动工具拆开带空格的绝对路径。已有进程变量优先，dotenv仍按数据解析，含`$`的字面值使用单引号保留。模型参数没有传入网页启动入口，测试与迁移命令也未增加 dotenv 回退。

[实际配置核对](../../../../output/pm-local-configuration-0407/configuration-after.json)使用该启动方式、离线且不同步依赖，仅构造模型目录和读取配置：进程已识别原有两个服务商。搜索服务仍未配置，应用预算仍legacy，未采用计量配置。没有启用能力、授予资格、打开API端口或请求服务商。

## 验证与边界

- [49项受影响检查](../../../../output/pm-local-configuration-0407/affected-tests-final.log)通过：三个进程分别结束时关闭其余进程；目录含空格与`&`时仍绑定根目录文件；实际uv离线子进程读取合成模型/预算/计量配置；进程模型参数覆盖文件值；字面值不执行；预算配置不静默回退；测试数据库必须显式配置、存续57432受保护。测试数据库与网络访问在护栏单测中禁止，未连接真实数据库。
- [lint](../../../../output/pm-local-configuration-0407/ruff-final.log)、[格式](../../../../output/pm-local-configuration-0407/format-final.log)、[测试文件类型](../../../../output/pm-local-configuration-0407/mypy-final.log)、[启动脚本语法](../../../../output/pm-local-configuration-0407/shell-syntax-final.log)通过。开发期间发现启动工具的路径拆分、未引用带空格值及双引号dotenv插值差异，已按实际解析规则修正；开发日志保留。
- [2800份当前源](../../../../output/pm-local-configuration-0407/candidate-source-sha256.json)核对；相对上一冻结集只改变启动测试，另将本轮启动脚本及服务说明纳入，见[候选变化](../../../../output/pm-local-configuration-0407/candidate-transition.json)。API应用、前端、提示词、模型资格、可信样例、预算政策和迁移源未改；不把之前179项影子评测及11项导出检查合并宣称当前全量出口通过。

真实实测仍需允许的研究主题/材料与搜索服务、有效计量发布和当前调用授权、八能力独立人工参考集及原服务商证明；RFQ四类原名称、真实角色协审及人工Exit保持待补。能力继续SHADOW，原N项仍部分完成，目标未完成。未修改`.env`或资格文件，也没有git push、部署、生产操作或业务出站。
