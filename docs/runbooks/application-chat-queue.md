# Chat 持久队列与后台执行

本地候选 0087–0088 将 Chat 请求从持续连接中移出：提交立即返回 run_id 和 queued；用户可查询、取消，原页面在同一浏览器会话中刷新或离开后返回可继续查询。当前仅接通 Chat；其他应用入口、waiting_input 和无最终模型结果的分步恢复仍按 N0-03 继续。

## 接口与运行方式

- `POST /api/ai/chat/requests`：与原 Chat 相同的 project_id、question、request_id；返回 202。相同用户/内容/请求号复用同一运行，内容冲突返回 409。
- `GET /api/ai/chat/requests/{run_id}`：返回排队、运行或终态及可用结果；只读取，不触发模型。当前用户必须仍有原项目访问权，结果引用重新核验。
- `POST /api/ai/chat/requests/{run_id}/cancel`：取消 queued/running 请求，重复取消和已完成请求保持幂等。对外状态为 cancelled，原运行使用 failed 加 APPLICATION_REQUEST_CANCELLED，未执行请求的 started_at 保持空值。
- 在应用服务的环境中运行 `python -m scripts.run_application_worker`；`--once` 只处理一个候选，`PDOS_APPLICATION_POLL_SECONDS` 默认 1 秒，允许 0.1–5 秒。此为 Owner 应用平面进程，使用应用数据库连接；不增加 pdos_agent/pdos_worker 权限。
- 接入网页时，在 Web BFF 环境设置 `PDOS_AI_CHAT_ASYNC=true`，且必须已经配置有效的 budgeted 应用模式、计量资格和运行中的应用 worker。默认 false 保留现有同步入口；未自动启用生产，也不在资格缺失时暗中退回未计量执行。

## 请求生命周期

创建事务固定用户授权、登录版本、预算 lineage 和绝对截止后提交 queued；不领取执行租约。创建过程的短暂活动段结束，排队期间不累计执行活动时间。后台领取在原 run 的锁内验证原登录、政策、profile 和绝对截止，再发首代租约，随后释放事务锁执行已有 Chat 服务。并发 worker 只有一个取得执行权；不为领取重建请求或预算。

如果执行者在模型结果落盘后退出，监督器标记过期，后台可复用 0086 的原结果接续能力取得下一代租约。最多三代，不重新调用模型。无可靠结果或回执未知时保留明确失能状态，不自动重发。领取之前的失败会停止该请求，避免反复占据队首；已领取请求由原 Chat/租约逻辑收尾，保留可恢复的过期原因。

前端显示“请求已保存，等待处理”或“正在查证项目资料”，可取消。浏览器仅保存原 run_id；读取失败暂停自动查询并提供“重新查询”。已有同步返回仍按原界面呈现。当前浏览器会话以外的会话历史导航由 N3-01 继续建设。

取消不保证供应商能中断已收到的请求；迟到回执仍沿原预算记账，租约已结束时不能覆盖取消状态或发布答案。本次没有调用真实供应商、部署 worker、切换生产入口或变更任何 Exit。
