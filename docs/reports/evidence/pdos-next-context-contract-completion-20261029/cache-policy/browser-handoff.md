# 主会话浏览器复用建议

本分支未启动 API/Web、未创建登录或操作浏览器。可复用已核对的 53502 隔离 fixture 和本地预览登录模式，使用新的合成租户/管理员，真实模型保持关闭；不需要 Temporal worker 或真实模型连接。

- 基础对象与登录：既有 `tests/conftest.py::setup`；管理员身份沿 `tests/agent_kernel/test_management_api.py::promote` 的合成 TenantAdministrator fixture。协议由原 `POST /v1/categories/{category_id}/provider-agreements` 登记，不直接插入协议表。
- 可沿既有 `docs/reports/evidence/pdos-next-summary-dingtalk-20261029/browser-fixture-browser_fixture.py` 的 loopback API、私有登录目录与 ready 公共摘要模式复用，但无需启动其摘要/钉钉业务。若加写边界，只放行协议登记及 `/recover`，其余 API 写入可拒绝；模型运行端口继续关闭。
- 页面入口：设置 → 集成与治理 → 服务商协议。`PlatformSettings` 内的页签是组件状态，应实际点击“集成与治理”和“服务商协议”，不靠不存在的 URL 子页签参数。目标区域 accessible name 为“服务商数据协议”。
- 原生 API：GET `/v1/categories/{category_id}/provider-agreements`（可加 provider 过滤）、POST 同路由、POST 同路由 `/recover`。前端 `categoryTransport` 仍把 `v1/provider-agreements` 映射到这些原路由。预览在页面内，登记由“本人批准登记”按钮触发。

最小场景可用一个新合成 provider 标识，不配置真实路线：

1. 进入表单，确认“协议明确允许提示缓存”默认未勾选；填写合成协议、允许类别和有效日期，勾选后点“核对协议并预览”。预览必须显示“可控提示缓存：允许”，此时回执和协议数量不增加。
2. 点“本人批准登记”，读取真实回执，列表显示允许；刷新仍显示允许。读后续版表单保留勾选。
3. 续版取消勾选并走同一预览/本人批准，列表显示关闭，版本只增加一次；刷新保持。留存自由文本不改变该选择。
4. peer 登录仅可读同一字段，登记表单禁用。旧 `NULL` 协议列表显示“未取得明确允许（关闭）”，续版不默认开启。

截图可用正常桌面及一个窄屏/暗色检查新选项、预览与列表；本增量只有一个配置项，无需重跑无关业务链。两个布尔版本均是独立合成管理员具名决定，不能用这些截图声称真实协议已配置或真实服务商缓存已关闭。网关是否实际去掉 Anthropic `cache_control` 另由原生合成传输测试证明。
