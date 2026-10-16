# pdos-next 租户模型宿主配置

默认 API 和 Worker 通过同一份服务器元数据文件取得租户凭据引用、服务商身份和价格卡。模型密钥保存在阿里云 KMS 通用凭据中，文件只保存引用。此接线实现冻结 v1.1 §06、§07.5；不会授予模型资格、签约批准或 T2 执行权。

## 配置与启用顺序

1. 为 API、Worker 设置相同的 `PDOS_TENANT_RUNTIME_CONFIG` **绝对路径**。参考 [元数据示例](../../pdos-next/config/tenant-runtime.example.json)，在服务器私有目录保存实际文件，通过原子替换更新。未设置时维持 AI 未配置状态；不存在、格式错误、超过 2 MiB 或相对路径均显示配置不可用。显式注入的测试端口优先于默认宿主。
2. 使用已获授权的 KMS 通用文本凭据。`secret_arn` 必须是完整的账号/地域 ARN；同一文件的凭据地域必须与 `kms.region` 一致。`reference` 是管理员分配并保持稳定的 UUID，每个“租户 × 协议”只有一个当前槽位。值仅包含服务商要求的 API key，不包含 JSON 包装。不要把密钥粘贴进元数据、模型配置页面、源码、日志或本手册。
3. 为进程提供阿里云官方凭据链支持的访问身份。部署在 ECS 时可使用实例 RAM 角色，授予所需凭据的 `kms:ListSecretVersionIds`、`kms:GetSecretValue` 权限；跨账号访问还需相应资源授权。SDK 默认凭据链也可消费已获授权的开发身份。该文件不保存云 AccessKey，也不自行创建角色、授权或云资源。参考 [官方凭据链](https://help.aliyun.com/en/sdk/developer-reference/v2-manage-python-access-credentials)。
4. `kms.endpoint` 支持与地域精确对应的共享公网 `kms.<region>.aliyuncs.com` 或共享 VPC `kms-vpc.<region>.aliyuncs.com`，均通过 HTTPS。专属实例网关和自定义 CA 尚未接入，不要填入此示例冒充支持。部署应按实际网络选取地址，见 [官方客户端初始化说明](https://www.alibabacloud.com/help/en/kms/key-management-service/developer-reference/initialize-the-client-1)。
5. 在 `models` 为每个实际“租户 × 协议 × base_url × model × model_version”登记唯一记录。`provider` 必须与应用中实际服务商数据协议的标识完全一致；它与模型版本是不同概念。OpenAI 兼容与 Anthropic 原生协议均由既有网关实现。
6. 价格卡填入当前已核对的 USD 单价、来源、带时区的核对/失效时间，以及该模型已核对的文本 token/计费上界。输入、输出、缓存读取、缓存创建和按次费用分别计量；`covers_all_fees`、`output_cap_covers_all_billing` 只能在实际核对后设为 true。示例故意过期且未覆盖费用，复制示例不会获得模型调用能力。单价变更按每次调用保存价格快照，历史费用不回写。
7. 租户管理员通过既有模型配置入口预览并一次确认保存协议、地址、模型和版本，绑定当时的凭据版本；只改服务器文件不会自动完成该确认。另需按现行流程登记适用数据类别的有效服务商协议、启用技能、建立实际预算并完成适用资格审阅。配置文件中的名称和费率不是资格或签约材料。

同一文件可含多个租户和两种协议；服务器只从已鉴权的 Run 范围选择租户，不接收模型传入的租户或服务商身份。API 与 Worker 进程都需要对应的文件和云身份。管理接口只返回脱敏状态，不返回 KMS ARN、引用或密钥。

## 轮换、预算与失败恢复

凭据状态读取使用 [ListSecretVersionIds](https://www.alibabacloud.com/help/en/kms/key-management-service/developer-reference/api-kms-2016-01-20-listsecretversionids) 的版本元数据，不解密密钥。实际模型调用前复核当前版本，再使用 [GetSecretValue](https://www.alibabacloud.com/help/en/kms/key-management-service/developer-reference/api-kms-2016-01-20-getsecretvalue) 同时指定 `VersionId` 与 `ACSCurrent`，并核对返回名称、版本、阶段和通用文本类型。KMS 由官方 SDK 签名，有限连接/读取超时且不开 SDK 自动重试；SDK 原始异常不对外传播。

当前绑定包含租户、协议、凭据引用、完整 ARN、网关和实际 KMS 版本。轮换 `ACSCurrent` 或改指其他 ARN/网关后，旧模型配置显示“需重新绑定”，旧绑定不能解密新值；管理员须重新预览确认，并按变更后的实际模型/技能资格规则处理。运行已经开始后，服务商身份和模型路由不能静默替换。配置与版本每次读取，不缓存密钥材料。

每个 Run 的 token 上限由服务器当前选中的活动预算输入/输出额度之和确定（受数据库整数上界约束）；钱包继续跨 Run 原子限制总金额、调用数及输入/输出量。无活动预算不能绕过现行费用检查。保守预留失败时运行保留已完成结果，费用未知时继续按既有未知结算规则保留占账，不自动重发不确定调用。

排查顺序：元数据路径/格式 → 进程身份与 KMS 网络/权限 → 管理页凭据状态及当前版本绑定 → 完整模型键 → 价格有效期与计费覆盖 → 当前协议/技能/资格/预算。只读取必要元数据和脱敏状态，不打印凭据或私有正文。修复外部条件后通过既有受理/恢复入口继续，未知结果先核对原回执。

## 已验证范围

[本地接线证据](../reports/evidence/pdos-next-m3-20261016/tenant-host/result.md)覆盖默认宿主、实际鉴权 API/lifespan、Temporal、独立 Worker 进程、LangGraph/PostgreSQL、费用账本和 T1 提案保存。KMS 与模型网络使用合成传输，未读取真实密钥、创建云资源、进行真实模型调用或改变 golden-case。真实 KMS 连通性、实际服务商协议/单价、模型质量与资格和生产启用仍需对应授权及材料。
