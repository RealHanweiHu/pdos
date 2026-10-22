# 独立只读复核与修正

审阅范围仅为本包扫描源码/负例及生命周期 port 的明确安全合同；没有 DB、网络、真实文件/恶意样本或共享服务操作。

本包已修正并加入扫描负例：

- `ScanGuardPort.is_current` 仅严格 True 可放行，非空未知值、1、None 等不能充当授权；权威配置 port 变化使旧请求/clean 失效。
- StorageFailure 未验证的 code 归一为固定白名单，非字符串/私有诊断不落入回执。
- ZIP 原始文件名含 NUL 与库截断后名字不同直接拒绝，不能利用截断隐藏宏/嵌入内容路径；central-directory entry 数在 ZipFile 分配列表前检查，实际解压逐块计费。
- transport 超时/调用方取消不等待不合作任务结束，不采纳迟到 clean；名额直到真实任务结束才释放，异常/自取消/同步伪装 port 不泄漏名额。独立纯内存取消探针与包内对应检查均未发现丢失名额。

生命周期定向复核要求并已交由所属包修正：确认后固定 lifecycle revision 不可被 ABA 修改绕过；EffectReceipt 只收机器错误码；permit 提交后的人工 hold/引用/保留/权限变化须使许可失效，受控物理 adapter 保持同一 gate 到实际效果。接入时仍需真实 DB/CAS/存储适配器的并发验证，纯内存检查不能替代它。

最终定向探针发现并修正了许可时间边界：服务器时钟早于 `EffectPermit.issued_at` 时，`validate_effect` 必须先拒绝，负例要求实际物理调用数为 0；不能先移动原件、再由回执时间校验发现问题。

保留限制：非阻塞 async transport 可受 Python 任务预算约束；阻塞事件循环、底层不可终止 I/O 及 OS 安全隔离仍依赖受控运行环境。S3 自身必须设 I/O 超时；scanner rules 的真实资格与实际完整扫描不由 fake/unit 检查证明。PDF 包络/ZIP 检查不是恶意文件扫描，也不保证可解析。
