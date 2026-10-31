# 项目讨论回看：原生浏览器结果

主会话使用 752 输入的组合生产前端及 fresh 本人会话完成检查，[浏览器 fixture run2](pg-browser-run2.xml)通过。[ready](browser-ready-public.json)的本人、项目与随机本地 API 和[实际 Web 身份核对](browser-web-verified.json)一致；[最终结果](browser-result.json)为 `native_ui_checks_passed=true`。专用浏览器、Web/API 已由主会话清理。

[项目页截图](browser-project-history.png)显示实际项目活动的原 Run 身份，以及右侧本人当前项目的两条讨论。活动入口沿原 Run 读取，最终 HTTP 记录包括被取消 Run、其 events、带实际 `project_id` 的会话列表和 Session 内运行页。返回的当前项目历史恰为 ready 中两个本人 Session，分别保持原 `queued` / `cancelled` 状态；peer Session 与同品类另一项目 Session 均未混入。原 goal 保留，两个 Run 的结果均为空，没有生成或补造答案。此检查证明原记录可回看，不将取消/排队状态说成已完成结果。

最终结果记录 **24 张受保护表**的前后计数相同、原记录行摘要相同。包括 Session/Run 各 6、Run events 2、ToolCall 0、业务回执与审计各 8、Outbox 10；新增 Run、Receipt、ToolCall 均为 0。边界共放行 59 次 GET，无其他方法或拒绝请求；实际 ApiPorts 的 Temporal port 未配置。导航、回看、运行轮询与历史读取没有创建业务记录或启动新 Run。

[浏览器 run1](pg-browser-run1.xml)在 fixture 对原 app 路由 closure 的枚举假设处失败，未进入页面验证；改为显式原生 `create_app`/ApiPorts 后才完成本次 run2，原失败保留。该浏览器结果与独立权限/分页 [PG run2](pg-run2.xml)分别计数，不相加成一次整组。未调用真实模型、Embedding 或外部渠道；真实资料质量验收仍独立保留。
