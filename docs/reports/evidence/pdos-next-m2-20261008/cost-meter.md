# M2 费用预约实现与验证

真实模型调用 0 次，实际服务商价格尚未核验，USD 10 尚未授予。以下测试使用明确标记的合成价格卡和独立临时 pdos_test。

`agent_validation_budgets` 是服务器绑定的验证钱包。多个 Run 和同一 Run 的隔离子任务以同一钱包 ID 共享费用、调用次数、输入和输出限制。`create_run` 将 ID 固定进意图摘要与不可变绑定；HTTP/模型参数无预算、价格、资格或权限字段。AI 数据库角色对钱包及业务表无直接写权限。真实宿主必须固定批准的同一个钱包，模型不能换钱包；代码不会自动开新钱包。

调用前以 run → call → wallet 的锁序原子预约。当前价格卡绑定服务商、准确模型、配置版本、USD、有效期与价格来源；原生请求的完整 JSON UTF8 字节包含 system、历史、工具定义、工具输入和输出 schema。已核对的 token/UTF8 比率与 framing 上界由价格卡提供。只接受文本 content；多媒体、未知文本计费、全部输出收费上界或附加费口径缺失时，发送前停止。

输入按 uncached/cache-read/cache-creation 三项分别结算，预约取三项最大费率，输出使用配置的最大收费输出，固定费用也预约；Decimal 计算后向上取整为 micro-USD。全局费额、输入、输出或次数不足时不发送。Graph 返回 partial 并保留已核对工具结果，不用额外模型调用解释错误。

成功和有已知 usage 的错误按实际费用结算，缓存 breakdown 和 request-id 保留在持久结果供重放；重放不重复收费。已知无 usage 的拒绝仍保留价格卡固定费用。输出截断/拒绝及 429/5xx 的已收到 request-id 保留用于对账。超过预约口径的响应、发送后的 SSE 撤权、未知网络结果、取消和 Worker 崩溃均释放活动槽，并把全额费用及 token 预约保留为估算已花费。started 调用直接结束对账会先按 unknown 结算，同事务终结 failed；已有未知估算不因最终关闭或晚到结果退款或重复收费。

数据库更新已终态调用仍受不可变守卫保护；0708 在原调用转换中 BEFORE 原子结算，避免 AFTER 二次回写。0709 对超预约记录明确拒绝，0710 统一失败、取消和恢复的锁序，避免 call → run 的死锁窗口。已安装的 0707–0709 保留，新修复通过新增迁移落实。

0711 补齐撤权后的可见技术失败。仅受控 pdos_next_dispatch 可调用，SQL 重核实际 tenant/category/owner/writer 绑定与真正权限失效，健康 Run 和既有终态不可结束，跨范围返回 false；只释放既有 started 槽并记 failed/error，未知费用全额保留，业务表/Audit/Outbox 不变化。应用、AI、auth 角色无执行权限。实测包括发送中撤权与 Activity 开始前撤权，避免 workflow 已结束但 AgentRun 仍显示 running。

0712–0715 补齐整次撤回的技术端：先结算既有 started 调用再写 Run 撤回标记，未知发送成本按完整预约保留；原执行终态和历史不可变，epoch 阻断后续执行。末尾 finish 或公共 Outbox 注入失败时，同一 UOW 的业务撤回、费用/Run 标记、确认消费与 Human 回执均回滚。

证据：`cost-meter-final-review.log`、`cost-meter-text-bounds.log`、`model-replay-usage.log`、`revoked-terminal.log`、`public-run-revert.log` 及最终 `kernel-final.log`。覆盖缺失/过期/错模型价格 0 HTTP、纯文本收费依据缺失、多媒体拒绝、缓存 Decimal、单钱包多 Run 上限、并发预约、输入/输出/次数/USD 上限、实际成功/错误结算、取消、晚到结果、Worker 丢失、直接 final 对账、超预约 usage、SSE 撤权与锁序竞争；迁移往返见 `migrations-down-0011.log` / `migrations-up-0715.log`，12 张自持表和公共 Receipt FK 元数据一致。

钱包对其预约是硬限制。未知分词、隐藏收费或错误的服务商价格卡不能由本地估算消除；真实使用前必须核对准确模型的收费上界并取得授权。当前证据不等于真实费用资格、T0 资格或 M2 正式退出。
