# 模型服务商界面管理检查点 · 2026-10-26

按用户要求，模型设置页现在可直接填写 API Key、Base URL 和模型名称，保存多份服务商配置并确认切换。设计记录为[确认稿 P29](../../../design/2026-10-08-pdos-next-design-confirmation.md#p29-在界面添加密钥与切换模型服务商用户-2026-10-26)，操作见[接入手册](../../../runbooks/pdos-next-tenant-model-runtime.md#从页面添加与切换p29)。

## 已完成

- 添加表单直接接受密码字段中的 Key，模型版本可留空沿用模型名称；协议、输出方式、流式和计费资料放在可展开的高级设置。列表显示当前连接、地址、模型、掩码和计费资料状态。切换确认紧邻列表，编辑区在确认时保留输入并隐藏；刷新后读取服务器当前选择。
- 每份连接有独立的租户/连接/凭据绑定；同协议、同端点的两份 Key 也各自解析。连接 ID 与完整模型键由服务器核对，运行不能静默借用另一份密钥。已登记端点保留服务器服务商身份，精确模型可沿用原价格卡；其余连接可填写计量，未填写不会被伪装为具备调用条件。
- Key 经专用管理员接口进入 KMS 或 macOS Keychain，不经过 COMMON 命令、不进入确认快照、回执和普通元数据文件，不写 localStorage/sessionStorage。Keychain 写入通过 Security.framework 传内存，不将值放进进程参数。非秘密连接元数据沿用原服务器文件，通过文件锁、0600 临时文件和原子替换保存，包含创建人、时间与私有请求指纹；无新增数据库表或迁移。
- 保存连接不启用模型；实际启用/切换复用原 T1 `model.configuration.save` 事务与回执。没有改变权限、T0/T2、实际材料出站、技能资格或原 MiniMax 开发不限额范围。保存或切换均不调用 LLM。
- 请求结果未知时使用同一请求恢复；KMS 创建丢失响应先读回原名称/版本，文件写入中断返回 503，页面保留原请求而不重新分配编号。改内容重用已完成请求被拒绝；新增连接不会覆盖旧 Key。

## 验证与实际环境

共 **288 项**通过：

| 范围 | 证据 |
|---|---|
| 180 项纯后端 | [backend-final.txt](backend-final.txt)：原协议/配置回归、独立 Key、租户与路由绑定、幂等、旧确认请求语义保全、原文件保全、价格与服务商身份、SDK 创建及未知结果只读对账、Keychain 合成适配 |
| 13 项实际 PG/API | [postgres-tests.txt](postgres-tests.txt)：添加两份 Key、确认切换/切回、默认 Worker 路由、原请求恢复、存储中断 503、非管理员/伪身份拒绝、确认原子性及尾部回滚 |
| 8 项表单 | [frontend-render.txt](frontend-render.txt)：密码输入、掩码、协议和配置表单的实际渲染及原限制 |
| 87 项 BFF | [bff-tests.txt](bff-tests.txt)：专用路径、同源/cookie、Key 留在 POST 正文、拒绝 URL 参数及超大请求，并回归原代理 |

[受影响类型检查](typecheck-affected.txt)、[最终源码全范围 tsc](typecheck-final.txt)、[Ruff](ruff.txt)、[ESLint](eslint.txt)及定向 diff 检查通过。全范围 tsc 沿用上一轮仅排除 `.next/types/* 2.ts` 重复缓存副本的临时配置；首次检查另遇到本轮未改的 `run-continuation.ts` unknown 字段错误，最新源码已有类型守卫后复核通过，初始输出保留在 [typecheck.txt](typecheck.txt)。没有将其他会话的该文件修改归入本轮交付。未重跑全站构建。

数据库操作复用已核对的独立测试环境：[64245/pdos_test](database-target.json)，匹配容器与 environment_guard，真实 head `s0_0822`；保留此前必要备份，无迁移或降级。KMS 网络在自动化检查中使用合成 SDK/内存替身；真实本机 [Keychain 创建、读取、同请求重放](native-keychain.json)通过，临时项已删除。

实际预览为 57859 → API 57858 → 已标记 57358/pdos_test。API/Worker 已按原启动参数[优雅重载](preview-reload.json)，健康检查 200。浏览器使用 web-access/CUA，在已有合成身份下直接填写合成 Key，成功保存 → 确认启用 → 刷新后仍为当前 → 确认切回 MiniMax。截图见[切换成功](switched-provider.png)、[390px 列表](mobile-list.png)、[390px 暗色表单](mobile-editor-dark.png)和[最终入口](model-connections.png)。未用合成内容冒充真实服务商响应。

已[核对并清理本次测试连接及其两项 Keychain 项](preview-cleanup.json)，当前为 MiniMax-M3 v3 配置，原凭据引用保留；两次切换的不可变配置历史与回执保留。自测试连接创建起，实际账本新增模型调用为 0。清理脚本首次把账本工具列误写为 `kind`，只读检查报错后按实际 `tool` 列修正；之前未删除或改写任何条目。主题与临时 viewport 已恢复。

[接口契约导出](contract-check.json)只更新本轮路由及关联 schema，离线导出禁止连接数据库；COMMON 配置 payload 没有 API Key 字段。源码范围与哈希见 [source-manifest.json](source-manifest.json)，总计及命令口径见 [verification-summary.json](verification-summary.json)。云写入参数和所需权限依据 [KMS CreateSecret 官方文档](https://help.aliyun.com/en/kms/key-management-service/developer-reference/api-kms-2016-01-20-createsecret)。

## 剩余边界

本轮界面添加/切换闭环无剩余实现阻塞。尚未进行真实云 KMS 创建、任意第三方模型连通性或质量验收；对应服务需要实际密钥、云权限、有效价格/计量和适用资格。服务器配置文件须位于安全可写目录，并由 API/Worker 共读；未接入云环境的权限条件不由页面虚构。没有生产部署、push、云资源授权或阶段人工验收。
