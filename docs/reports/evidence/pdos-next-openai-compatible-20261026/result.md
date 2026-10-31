# 基础 LLM OpenAI 兼容接入检查点 · 2026-10-26

用户要求基础大模型支持任意 OpenAI 协议 LLM API，不再限定 MiniMax。已按[确认稿 P28](../../../design/2026-10-08-pdos-next-design-confirmation.md#p28-基础模型开放-openai-兼容-api-接入用户-2026-10-26)同步实现与现行架构。

## 可用能力

- 「设置 → 小Pai → 模型配置」支持自定义 OpenAI 兼容 Chat Completions 基础 URL、模型 ID、版本及输出 token 参数；服务器宿主继续按完整租户/模型键绑定服务商、密钥引用和价格卡。原接入层没有品牌白名单，此次补齐实际兼容选项与现行范围。
- 新配置默认工具调用输出；增加 JSON Schema、JSON 对象、JSON 文本选项，不再强制所有接口支持严格 `response_format: json_schema`。动态 schema 仅放上下文末尾，不修改冻结 system prefix。业务工具仍使用原生工具调用，最终结果继续由运行图/领域 schema 校验。
- 流式可关闭，关闭时不发送 `stream_options`；实际用量仍必需，缺失用量按结果未知保守处理，不自动换模式重发。支持标准响应中 `tool_calls: null` 和 `prompt_tokens_details: null`。
- 通用工具输出保留原生工具续接及最终输出确认；端点或响应方式变化后旧续接失效，响应方式进入资格标识。新增默认字段不改变旧配置摘要与原路由摘要；已有 MiniMax 专属适配及 Anthropic 原生适配保留。
- 配置仍经原 T1 预览、一次确认、回执/审计/Outbox 同事务保存。密钥不进入页面、源码或日志；未更换现有模型、授予资格、修改预算政策或增加真实资料出站。MiniMax 本地不限额保持原已批准范围。

## 验证

- [164 项纯后端检查](protocol-tests.txt)通过：自定义端点及模型、两种 token 参数、五种响应选项、原生工具/结果续接、非流式与流式、用量缺失守卫、旧配置绑定、原 MiniMax 与 Anthropic 兼容、模型配置与宿主。
- [6 项实际 PostgreSQL/API 事务检查](postgres-tests.txt)通过：三组配置选项预览/确认保存/读回/运行路由、原请求恢复、密钥轮换、非管理员拒绝、尾部失败整体回滚及直接 DML 拒绝。每次先核对[隔离目标](database-target.json)：64245/pdos_test，标记匹配，实际 head `s0_0822`；复用已确认隔离环境与已有备份，无迁移、无降级、未操作历史原工程数据库。
- [7 项前端配置检查](frontend-tests.txt)、[Ruff](ruff.txt)、[受影响 ESLint](eslint.txt)通过。接口[导出契约](contract-check.txt)与实际 SavePayload 一致，新字段均可省略。
- [源码类型检查](typecheck.txt)通过。首次常规 `pnpm typecheck` 被既有 `.next/types/* 2.ts` 重复生成声明阻断；使用临时配置继承原全部源码范围，仅排除该缓存副本后 `tsc --noEmit` 返回 0，未删除或改写缓存。临时配置见[验证摘要](verification-summary.json)。未重跑全站构建或全站浏览器矩阵。
- [本地预览重载](preview-reload.json)：先核对 57358/pdos_test 的容器标记、head 与实际启用租户，确认该租户无活动 Run，再按原参数优雅重启 API 和 Worker；API `/health` 200。最初把克隆库内其他历史夹具租户纳入运行统计，检查守卫拒绝操作；缩至 Worker 服务器明确启用租户后核对通过。最初只读统计误用 `status` 列，依据实际 `state` 列修正；此前均未重启或写数据。原模型配置及历史记录保留，最终实际只读结果见 [live-configuration-read.json](live-configuration-read.json)。

累计 177 项检查通过；源码指纹见 [source-manifest.json](source-manifest.json)。协议字段参考 [OpenAI Docs · Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。

## 剩余边界

通用接入实现与本地检查完成；本轮无新增真实模型调用。尚未对每个第三方服务商做真实连通性/质量评估，新增服务商仍需其实际端点、KMS/Keychain 密钥绑定、有效价格卡及适用资格与授权。文本模式用于省去格式扩展，并不替文本模型补造原生工具能力；协议兼容不等于所有模型都能完成全部业务。未进行生产部署、push 或阶段人工验收。
