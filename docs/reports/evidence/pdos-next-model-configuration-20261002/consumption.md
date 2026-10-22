# 只读消费与漂移复核

消费 hash 见 consumed-initial.json / consumed-final.json；初次摘要在实现前期读取后固定，交付前重算，不把这些公共资产计入本包候选。包内候选仅四个授权源码/测试目录。

| 只读接口 | 本包使用方式 |
|---|---|
| providers/types.py ProviderRoute | 复用协议、HTTP/HTTPS目标边界、显式端点、限额与 digest；metadata 验证使用仅验证标记，不返回运行路由；运行凭据只能由 SecretPort 注入 |
| providers/client.py ProviderClient | 读取协议/无重试规则，无复制/修改客户端、无构造网络调用 |
| model_gateway/ports.py CallPermit/BudgetPort | 不构造真实 permit；Runtime currentness 适配原回调，预算就绪不替代 reserve |
| model_gateway/claim.py ClaimGateway | require_current 保留网络前后复查，不改变 system prefix、重试与未知结果对账 |
| models.py Base/Row/Qualification/Confirmation | 自己目录映射继承 Base/Row；provider_version 长度兼容 Qualification；保存计划公共 preview 可恢复至主线 common snapshot，secret refs 不放 snapshot |
| service.py check_qualification/preview路径 | 不迁移旧资格，不改权限；common Preview/Confirmation/Receipt/Audit/Outbox 仍需主线注册和原子接线 |
| errors.py DomainError | 固定安全错误，from None 阻断底层敏感异常链 |
| ui/button.tsx、lib/utils.ts | 设置组件直接复用 Button 与已有主题 tokens；未写 global CSS |
| tsconfig/package/pyproject、Next本地指南 | 只用现有依赖；组件是 client boundary；nonincremental/noEmit 独立 TS 范围，未运行 typegen/next/build |
| 指定设计、UI基线、政策与AGENTS | 版本化配置与用途资格分开；服务器事实；人工具名管理；独占目录边界 |

交付前 `drift.json` 仅发现唯一清单 tasks/ai-native-integrated-todo.md 由协调/主线更新：主线供应第五波已经汇合，成本/品质/安全仍续接；本包接口与授权边界未变化。已定向重读该队列。消费的 ProviderRoute、Client、网关、公共模型/资格守卫和 Button 等源码摘要均未漂移，不需改写本包或重跑共同验证。本会话没有修改唯一清单。
