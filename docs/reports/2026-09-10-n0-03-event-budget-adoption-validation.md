# N0-03 事件预算创建与Agent工厂接线验证

2026-09-10。新事件运行已能在创建事务内固定获批预算；独立Agent工厂已能通过真实受限账号装配计量、预留、唯一派发、结算与trace。迁移0070安装创建触发器，固定DC-07三档profile与摘要，未给worker或Agent增加预算表写权限。默认模式仍legacy，本次没有真实采用或生产操作。

dispatcher显式读取独立Agent配置，在每个派发事务设置或清空事务局部profile。运行、预算和cursor共同提交或回滚；数据库按实际创建时刻确定绝对期限，不等到模型首次调用才启动期限。已存在运行不因重放、合并、seal或进程档位变化而重新获得额度。Agent只核对服务端已有绑定，不能自行补旧运行额度。

共同模型准入新增绑定保护：已有预算的运行不能被legacy工厂无预算执行。该限制覆盖事件与已有应用绑定，保持当前租户draining和双向在途互斥保护。配置不一致、计量包损坏、旧运行未绑定均拒绝请求，不回退模式。详见[运行手册](../runbooks/event-budget-adoption.md)。

## 验证

| 范围 | 不同测试通过数 |
|---|---:|
| 新增事件预算、真实dispatcher与Agent工厂、降级保护 | 11 |
| 真实worker/Agent数据库安全 | 9 |
| 既有受限预算预留完整链 | 20 |
| 获批配置与运行工厂静态配置 | 22 |
| dispatcher/schema、新旧准入、应用预算和Chat回归 | 40 |
| 生产模板、凭据分离及发布纪律本地验证 | 25 |
| 合计 | 127 |

三档预算均由真实worker触发创建，与获批profile逐字段和摘要一致；运行仍处debouncing时即已有冻结预算且无调用journal。后续seal和另一档位进程重放不改变记录。模拟连接池遗留配置后，legacy派发仍不分配预算；错误数据库profile和创建后的业务异常均令运行、预算与cursor原子回滚。worker与Agent均没有三个预算表INSERT权限或触发器函数直接EXECUTE权限。

完整链使用真实worker派发、真实`configured_agent_runtime`及`pdos_agent`租约执行，HTTP使用合成transport和计量发布包。成功运行仅一次provider请求，run/trace/call身份一致，journal三条，实际token为10、最终持有0；无Finding或业务写入。数据库冻结work_package但Agent选择short时返回`BUDGET_PROFILE_CONFLICT`；旧未绑定运行返回`BUDGET_RUN_UNBOUND`；legacy接管已绑定运行返回`MODEL_CALL_BUDGET_REQUIRED`，均零provider请求。计量发布包损坏时工厂启动失败，运行保持queued。

有预算历史时0070拒绝降级且保留head与触发器；空历史schema往返与既有调用历史保护通过。旧混合准入测试曾硬编码0067 head，已改成断言失败降级后保持测试前head；没有放宽历史保护。档位冲突测试最初被更早的计量窗口检查拦截，随后改为先冻结较大档位、以可计量的short配置执行，直接验证冻结档位冲突。

Ruff/格式10文件与Mypy4实现文件通过；共同合同4产物与运行合同5产物已刷新并通过一致性校验，获批draft.3原件保持。共享库仅`127.0.0.1:57432/pdos_test`，head为0070；会修改角色密码的测试全部在独立57433临时pdos_test，测试结束后删除容器。共享库角色密码未修改。没有真实模型调用、golden写入、git push或生产操作；Compose改动仅为默认关闭的配置传递。

机器摘要见[证据](evidence/2026-09-10-n0-03-event-budget-adoption.json)。

## 未完成

N0-03仍部分完成。事件运行的创建时预算及独立工厂装配已接通；应用主动运行仍在首个合格模型调用时冻结，关联run的实际共账接线、活动时间租约、checkpoint恢复和工具循环继续。嵌入服务不在本片范围内。

真实计量资格与可信发布、租户切换、旧进程排空和真实部署尚未完成。旧未绑定运行不自动迁移或重新派发；需要后续恢复合同在原历史上裁决。原P/Q/Sprint出口与生产delivery=false不变。
