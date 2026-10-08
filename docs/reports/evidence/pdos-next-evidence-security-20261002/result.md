# 原件扫描与生命周期 · 独立首版交付（2026-10-02）

已在本包独占目录完成可调用的扫描/安全模块与原件生命周期规则、受控 port、不可用适配器、必要负例和主线接入说明。没有修改公共模型/迁移/命令/API/原件流程或清单，没有建立第二份原件事实所有者。真实接线与联合验收由主线完成，G/N/P/Q 状态未自行勾选。

## 可交付能力

| 包 | 已交付 |
|---|---|
| `pdos_next.evidence_security` | 精确 `ObjectRef`/scope/ACL/受众读集与当前 scanner 配置 port；有界 `ScanRequest/ScanReceipt`；`ObjectStoreScannerAdapter` 的私有字节读取、类型/完整性/尺寸/解压预算和可注入本地 transport；扫描状态与当前解析 gate。 |
| `pdos_next.original_lifecycle` | 权威引用/上传日志/生命周期/授权消费 DTO 与 port；固定 `OrphanCandidate/RetentionDecision`；预览、人员一次确认、共同事务 staging；可恢复隔离/恢复单次许可与执行前保护复核；幂等、未知结果观察对账、未执行取消及恢复需要。 |

扫描器未提供时返回 `unavailable`，类型/预算或成功解析均不冒充 clean；infected/rejected 隔离，unknown/unavailable/timeout 保留失败与隔离要求。旧 clean 在字节/版本/规则/政策/ACL/受众或有效期变化后失效。timeout/取消丢弃迟到结果并保持有界名额，真实底层 I/O 与 OS 安全边界另待运行环境。

孤立对象只来自完整权威事实：失败/废弃上传、未注册、无引用/正式历史、无 hold、解析不在进行或已形成派生物、保留期与失败宽限均届满。引用未知、人工 hold、注册原件、时间/保留/状态未知均阻止回收。确认、许可和实际效果前重验版本、政策及当前权限；许可后的保护变化/时钟回拨不能绕过检查。

生命周期真实 transport 缺失时返回 UNKNOWN，保留 pending 保护并对账。`NOT_APPLIED` 要求持久的正向无效果证明，当前原件还在或回复丢失不足以证明失败；曾应用后恢复也不能误报未应用。恢复保留精确字节与引用/hold/历史，并且不恢复 clean 或扩大受众。本包只有 purge 资格计算，没有物理删除实现或删除许可。

## 固定候选与验证

源码/测试/接口摘要见 [candidate-manifest.json](candidate-manifest.json)、[消费接口](consumed-interfaces.json) 与 [交付前漂移复核](interface-drift.json)。每个文件保留 SHA-256；只冻结本包，不把并行主线工作树视作完整候选。生命周期子候选核对代理交付摘要一致。

| 必要检查 | 结果 | 原始输出 |
|---|---|---|
| 扫描规则、读取/transport/gate port、类型/版本/超限/不可用/超时/未知/权限负例 | **80 passed** | [pytest](scanning-pytest.log) |
| 生命周期保护、共同事务回滚/幂等、确认竞态、许可前后保护/ABA/时钟、单次效果/未知/恢复与安全负例 | **75 passed** | [pytest](lifecycle-pytest.log) |
| 两包各自静态检查 | **通过** | [扫描 lint](scanning-lint.log)、[生命周期 lint](lifecycle-lint.log) |
| 独立只读复核及修正 | 已处理具体问题 | [review.md](review.md) |

两套检查分别隔离根 DB fixture、禁止网络/数据库/子进程，使用 fake scanner、无害合成字节和明确自建临时/内存 store。生命周期并发是内存共用 fence/CAS 模拟，没有 PostgreSQL 联验。检查数不能相加为业务联合验收，既没有真实扫描器 clean 资格，也没有生产存储回收资格。通过的固定候选未无条件重跑完整验收。

## 剩余主线接口与恢复条件

具体字段、原子性、调用顺序和集中病例见 [integration.md](integration.md)，生命周期详细合同见 [模块接线说明](../../../../pdos-next/server/pdos_next/original_lifecycle/integration.md)。

- 主线实现持久 `ScanReceiptStorePort/ScanGuardPort`、上传意图/失败日志与完整存储 inventory、`LifecycleStorePort/ReferenceGuardPort/LifecycleAuthorityPort`。缺日志或引用覆盖时必须保持未知，不能依据缺一行推断孤立。
- 主线统一实体/迁移/命令和 Outbox/Inbox/worker 接线，在上传与 `originals.parse_uploaded` 的解析前、派生 Artifact 写入前设置同事务当前门禁；接当前派生资料失效传播与恢复提示。
- 真正的 reversible 存储 adapter 需共享保护 gate、存储侧单次 marker/journal、当前权限/政策与字节完整性核验及自身 I/O 超时。正式 purge 仍需单独具名批准和未知结果/恢复协议。本包没有激活物理操作。
- 真实本地扫描服务/规则版本、OS 沙箱、S3 客户端与持久存储、数据库/HTTP/worker 重启/浏览器整链未验证；OCR 与完整恶意样本验证不在本包首版范围。缺环境只阻塞这些接入验证，不影响已交付纯模块。

本轮没有读取 `.env/.local` 凭据、连接/迁移 DB、操作现有原件/桶、真实模型调用、业务出站、启动/停止共享服务、安装依赖、修改共享 `.next` 或执行 git 提交/push。分派未包含独立前端目录，本包没有新增页面或 fixture 业务界面，主线可把安全状态/预览原因接到既有确认入口。
