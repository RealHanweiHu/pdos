# Wave9 本地可逆访问隔离运行时

冻结时间：2026-10-02 15:21 UTC。范围仅为新 `object_lifecycle_runtime`、自身纯文件测试与本目录 `runtime-*` 证据；未操作数据库、旧包、公共服务、生产或真实文件。

## 接口与主线职责

```python
from pdos_next.object_lifecycle_runtime import LocalReversibleLifecycleAdapter
from pdos_next.original_lifecycle.types import LifecycleScope

runtime = LocalReversibleLifecycleAdapter(
    journal_store, gate, io_timeout_seconds=5
)
receipt = runtime.apply_once(stored_effect_permit)
observed = runtime.observe(stored_effect_permit)

# 当前数据库授权/保护锁必须由主线持有，直到真实字节读取完成。
runtime.ensure_readable(exact_object_ref)

# 仅主线确认已登记的旧原件且 inspect 明确 JOURNAL_NOT_FOUND 时使用。
runtime.ensure_legacy_readable(
    exact_legacy_object_ref,
    LifecycleScope(registered_row.tenant_id, registered_row.product_id),
)
```

`gate(permit, observation=False)` 是服务器受控 contextmanager。主线在进入时锁定 Product/对象保护状态，办理当前具名授权、引用/保留/fence 与 `LifecycleService.validate_effect`；观察使用当前观察授权。这个 gate 必须跨整个有界存储过程，子进程 kill/reap 后才退出。适配器不产生权限、生命周期资格、数据库回执或自己的事务。

两种 `ensure_*` 都不调用 effect gate、不返回字节，只承担持久隔离门禁与完整性核对；主线仍须持有当前 DB 授权和对象锁直到原件实际读取完成。关闭生命周期功能后，可保留同适配器作为只读门禁，给它的 effect gate 应拒绝 apply/observe。

旧原件桥接仅接受精确 ObjectRef 和主线从已登记 DB 原件取得的 LifecycleScope。文件系统没有旧原件的租户/产品证据，因此不能从用户传参推导 scope、登记状态或孤儿资格。桥接要求：上传日志确实不存在；本对象没有任何生命周期记录或残留全局绑定；LocalPrivateObjectStore 按原 key 实读并核对 hash/size。存在完整或损坏 journal 不选择桥接；有历史，即使已恢复为 active，也不选择桥接。它不创建上传 journal 或注册事实。

## 实际持久效果

所有原件字节保留。运行时仅在受控私有根的 `lifecycle-runtime-v1/` 下写访问标记和效果日志，无 purge 接口。隔离改变当前访问标记为 quarantined；恢复改变为 active，不修改扫描结果、来源撤回、受众、保留、登记或专业资格。

跨进程 flock 使用对象锁和操作锁；完整 EffectPermit、scope/ref、lease、action、policy/basis 均进入不可变绑定。先 fsync attempt，再写全局操作绑定，再写不可变事件、原子替换当前 marker 并 fsync，核对原字节后写不可变 terminal。返回已知结果需要连续事件、当前 marker、attempt、全局绑定、terminal 与原件完整性相互吻合。精确已完成重放不改任何效果文件；跨对象、lease 或操作的重放拒绝。

缺 marker 不能推出 NOT_APPLIED。无证明、未完成 attempt、缺失/损坏/冲突日志或原件损坏都返回 UNKNOWN，普通访问拒绝，也不重新执行未知效果。只有该运行时明确持久记录“受控尝试未改变 marker”的 terminal 才能返回 NOT_APPLIED。

恢复完成后，观察旧隔离仍可返回历史 APPLIED/quarantined，并使用原 terminal 的稳定 proof；这不表示当前访问仍隔离。当前 head 必须能由完整后续恢复链证明；冲突则 UNKNOWN。`observe` 重新获得当前观察授权并核对字节，观察时间是当前时间；主线已终结操作应读取其既有业务回执，不能把新观察时间当旧回执覆盖写入。

## 有界处理和恢复边界

父进程只调用固定服务器 Python 模块，输入上限 32 KiB，输出增量读取上限 8 KiB，错误仅返回安全代码，不回显原件内容。截止时间覆盖启动、读取和等待；正常超时 kill/reap 自己的进程后释放 gate。实际临时进程检查验证了超时终止。子进程限制 CPU、文件描述符、core，并在平台支持时限制地址空间；Darwin 不支持可靠 RLIMIT_AS，因此这是可信元数据进程，不是文档解析 OS 安全沙箱。内核无法中断的异常文件系统 I/O 仍不应被声称为绝对硬时限。

元数据 JSON 单条上限 64 KiB，目录记录数上限 2100、连续事件及尝试有额外上限。私有目录、文件类型/所有者/权限、链接、记录摘要、scope/ref 均核对。过期 permit 不开始效果，并在实际 marker 转换前再次核对期限。

crash 在 terminal 之前留下不确定状态时不会自动修复/重放；当前读门禁拒绝，待主线人工核对。terminal 已持久但回复丢失时可通过当前观察授权找回确切 APPLIED。全对象日志丢失但全局绑定仍在时拒绝访问和重做。摘要不是存储管理员防篡改签名；同时毁掉全部私有历史、重写字节和 metadata 的可信根失陷不在此证明范围。DB 单调 fence、权限与引用保护由主线独立负责。

## 本包验证

本包最终候选 39 项全部通过，8.20 秒；Ruff check 与 format 均通过。仅临时合成真实文件、实际子进程和假授权 gate，无 DB 或业务资格。覆盖隔离/恢复字节保留、历史证明、并发一次写入、六个 crash 点、超时 kill/reap、过期、当前 gate 拒绝、协议绑定、marker/terminal/event/原件损坏、链接、整个对象日志失踪，以及三项旧原件桥接检查。共同数据库/HTTP/浏览器与真实注册来源的权限证明由主线继续办理，不能把本包纯验证当正式 Exit 或生产启用。
