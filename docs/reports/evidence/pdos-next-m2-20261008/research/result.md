# M2 公共研究实现与验证

2026-10-08。依据冻结目标架构 v1.1 §06.3/§07.5，以及 M3 实施合同 §4.3；本交付只修改 `pdos-next/server/pdos_next/research/`、对应研究测试目录和本证据目录。

`research.search`、`research.read`、`research.fanout` 已实现。搜索服务由服务器显式注入，提供可实际调用的 Searx JSON 适配器；不读取环境搜索密钥，不继承代理或账号凭据，不跟随搜索服务跳转。查询和每一跳网页 URL 的出站政策均使用服务器绑定的 RunScope，在 DNS 与 HTTP 之前执行。

网页读取只接受本轮搜索线索或服务器登记的实际用户消息网址，主循环注册表中没有 `research.read`。读取拒绝私网、保留地址、混合安全/不安全 DNS 答案和通向私网的 IPv6 过渡地址；每次跳转重新校验，并以已验证数值 IP 连接，Host、TLS SNI 及证书校验保留原主机名。没有代理、Cookie 或 Authorization。正文、跳转、字符、时间及并发有明确资源预算；快照只追加，后续分页复用原快照，并发同址读取只做一次实际获取。

正文抽取保存标题和 Markdown，网页脚本不执行、也不进入抽取正文。公开 PDF 交给既有 `DockerParserRunner.parse_async` 的固定哈希镜像，在无网络、无宿主挂载、无凭据且有 CPU/内存/进程预算的容器中解析。`needs_ocr` 保留为 partial；镜像或隔离环境失能保留原始安全错误，没有宿主进程解析降级。同站读取共享 Retry-After 截止时间，HTTP 与搜索服务的原始安全错误、状态、请求号及重试说明保留，凭据形态字段脱敏。

fanout 子任务的工具只有 search/read。参数版本由宿主投影，工具输入中没有参数权威或作用域字段。台账行包含品牌、型号、参数与版本或自由键、值、单位、工况、快照与定位、逐字片段、代码判定的状态及错误。代码只接受该子任务实际读过定位中的逐字子串，并剔除伪造片段、未读快照和未绑定参数版本。覆盖包含实际搜索、实际读取定位、未读网址和正文范围、接受/拒绝行数；模型不能提供覆盖或计数字段。返回独立实际研究 job_id、台账、覆盖、失败和快照元数据，主循环结果从类型上不包含网页全文。输出字典可直接 JSON 持久化。

验证：本候选 **69 项研究测试全部通过（2.84 秒）**，ruff 通过。测试包含真实 loopback 搜索 HTTP、实际 HTTP 管线与固定 IP socket 接线、TLS 原主机与 CA 验证、私网/跳转/DNS 重绑定、出站拒绝先于 DNS、同轮网址权限、正文续读、并发快照复用、25 个研究任务限并发、引用与参数版本核对、未读范围、取消以及原始错误。公开 PDF 用合成文件实际调用现有固定镜像解析通过。没有数据库操作，没有公共外网或模型调用，没有真实业务资料，也没有资格授予或生产验收声明。

证据：[回归日志](final-regression.log)、[lint](lint.log)、[候选文件 SHA-256](candidate-manifest.json)。早期失败日志保留以说明适配过程；本结论只使用上述最终候选。

宿主接线：`research_tools()` 提供稳定工具定义；`ResearchToolHost(service, researcher=..., parameter_versions=...)` 提供异步 `call(scope, name, arguments)`。创建服务时注入实际 search adapter、服务商政策回调与运行作业快照存储；服务器以 `register_user_message(scope, message)` 登记真实用户消息中的 URL。`researcher(task, child)` 是宿主注册的只读研究执行图端口。宿主负责经 Temporal 调用注册图、持久化研究 job/result 与运行回执，以及超过同步预算时返回持久工作 ID；该子系统没有独立业务写入权限。
