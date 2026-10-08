# PDOS Next 租户模型配置独立包 · 2026-10-02

独立模块闭环已实现：租户绑定不可变配置版本 → 当前管理员保存计划/公共预览 → 同 Session CAS 适配 → masked 读模型 → 双协议运行选择/当前性拒绝路径。设置组件只把填写内容提交父层共同预览，不自行确认、保存、消费回执。配置已保存或 enabled=true 均不授予真实模型资格、出站、预算或 AI 写权限。

固定候选 SHA-256：`63bc4b8889c135dd69110ffa5b5dbb5341674e872ae871903b7e7f4e6df8c891`，14 个包内源码/测试/局部配置文件逐文件摘要见 [candidate.json](candidate.json)。检查脚本和本说明位于授权证据目录，未纳入业务候选。

| 检查 | 结果 | 原始输出 |
|---|---|---|
| 隔离 pytest，显式合成 ports/输入、禁插件/bytecode/cache、confcutdir 本包 | 76 passed | [pytest.log](pytest.log) |
| 局部 Ruff | pass | [ruff.log](ruff.log) |
| nonincremental/noEmit 局部 TypeScript | pass | [typescript.log](typescript.log) |
| 局部 ESLint | pass | [eslint.log](eslint.log) |
| 组件 SSR/契约行为，安装的 TS 编译器纯内存加载，无构建 | 7 passed | [component.log](component.log) |

命令、cwd 和真实 exit_code 见 [checks.json](checks.json)，复现入口 [run_checks.py](run_checks.py)。末次只重跑受到后端恢复预览/敏感异常保护改动影响的 Ruff/pytest；前端源码未变，原检查保留。所有检查退出码为0。后端用例覆盖双协议目标政策、跨租户/actor、非管理员/撤销、可信字段/secret字段注入、限额/协议错误、过期/漂移、真实事实缺失/非bool、预算/取消/资格拒绝、密钥轮换/错误解析、敏感 traceback不泄漏、共同公共预览可重建且拒绝漂移、Session head锁/CAS/tenant-filter/flush契约及不可变对象。

已实现的版本绑定包含 tenant、配置 id/revision、公共 metadata、启停状态及 opaque secret reference/version 摘要；provider_version 与现有 ProviderRoute.digest 相配。secret 轮换或配置变化失效旧 route/permit binding；无 fallback。RuntimeFacts 必须与服务器 Run/query 全维度和当前配置 binding_digest 相同，仅全部事实齐备时返回 `authorizer_check`，真正 CallPermit 继续由主线签发和复查。

未完成：公共 migration/模型注册/RLS/DB不可变权限、租户管理员与真实 secret manager、用途/工具版本资格数据接线、current egress/预算/cancel port、共同命令/API/BFF/父页面及实际浏览器入口。恢复条件与具体事务/接口需求见 [integration.md](integration.md)。这些属于主线独占接线责任；本包没有通过数据库、HTTP、浏览器、真实模型或 G/N/P/Q 联合验收，也没有写 golden-case/授真实 T0/改 canonical 分级。

环境边界：未连接任何数据库；未读取 .env/.local/机器密钥或真实凭据；未启停共享服务、安装依赖、写共享 .next、构建全站、调用真实模型或外发材料；未操作原件、云/生产、git commit/push。业务源码/测试和证据写入限定于指定目录。执行偏差：初次局部 Ruff 未加 --no-cache，可能更新已有根目录/服务端 .ruff_cache；最终检查已加 --no-cache 并通过。未删除或清理公共缓存，避免干扰并行工作；不能宣称本次零公共工具缓存写入。

消费摘要与定向复核见 [consumption.md](consumption.md) 和 [drift.json](drift.json)：交付复核仅唯一清单发生主线状态更新，相关源码接口无漂移。本包独立完成并保留人工与真实资格边界，未将局部通过声明为 G0 全完成。
