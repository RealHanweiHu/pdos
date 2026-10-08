# PDOS Next · G0 首轮实施与验证

日期：2026-10-02。用户请求：按新的完整目标设计完成执行方案，并开始执行。

**结果：方案完成，独立新工程已启动，来源事实窄路径可实际办理。G0 仍为部分完成，G1～G5 尚未实现。** 活动状态见[唯一清单](../../../../tasks/ai-native-integrated-todo.md#pdos-next-queue)，交付分解见[执行方案](../../../design/2026-10-02-pdos-next-execution-plan.md)。

## 可用入口与结果

本地预览 [http://127.0.0.1:3028](http://127.0.0.1:3028)，API8898。进入本机合成会话后可建立真实 Product 范围、粘贴/导入 UTF-8 txt/md 原文，定位精确行引用并登记 Claim；未知项保持未知，私人来源不能扩大受众。可保存 WorkRequest、查看原工作/来源版本与模型失能、一次确认取消；事实撤回保留原文和历史，并阻止覆盖人工修改/下游消费。

业务事实、ActionReceipt、Audit、Outbox 同事务。稳定请求键相同载荷重放，同键不同载荷冲突；服务器意图指纹防止换 key 绕过同源重复意图。身份来自服务端会话/Run，独立 AI writer 与 human owner 分开。合成能力通过 LangGraph 短步骤和同一领域服务验证，测试注入不会成为运行环境资格。

## 候选与隔离

候选文件摘要见[manifest.json](manifest.json)。本轮新工程、契约和源码在 `pdos-next/`；独立迁移链真实 head `next_0002`，不接入旧 0416 历史。设计 Markdown 是用户提供的原文件副本；66 个操作、65 个事件和48 个验收场景从合订本重建，JSON 带来源及 SHA256，专用 payload/OpenAPI 由实际代码导出，未收到原 contracts 包。

数据库：自建 `pdos-next-test-20261002-916f950f`，`127.0.0.1:62513/pdos_test`，marker `916f950f-2d2b-405d-b809-c15db75dc20c`。实例 ID/容器标签、绑定地址、实际 DB 和唯一 marker 在每次测试/迁移/服务操作前核对；只用显式 TEST_DATABASE_URL，不加载 `.env`。应用是非超级用户/非 BYPASSRLS/非表所有者，认证角色只读会话，`pdos_agent` 对业务表零直接写权限；资格表对应用保持只读。凭据仅在忽略的 `.local/runtime.json`，不进入证据或客户端。

存续 57432、已有 57439/57441 预览、旧库、旧业务源码和用户未提交修改均未操作。只在旧计划加新方案指针、在唯一清单加入新工程队列；原 N/P/Q 勾选、批准和 9/27 恢复历史保留。没有推送、生产部署、云资源或业务材料外发。

## 验证结果

| 检查 | 结果及证据 | 可证明的边界 |
|---|---|---|
| 合订本/目录覆盖 | 66 操作、65 事件、AT-01～48 各有阶段归属；5 个窄操作 payload 与实际 OpenAPI 导出 | 结构/来源覆盖，不代表66个命令已实现或48场景通过 |
| 独立 PG/API | **34 passed**，见[最终原始日志](postgres-tests.log) | 原文/哈希、精确引用、同事务/故障回滚、并发去重、同键冲突、租户/私人ACL、身份伪造、源版本/撤回、资格版本/用途/到期、取消/权限/资格运行中撤销、补偿保护、RLS/池复位/权限、ORM与迁移相容 |
| 迁移 | 初始 schema up/down/up；资格锁迁移 forward/back/forward，通过 | [初始往返](migration-roundtrip.log)、[资格锁往返](qualification-migration.log)；未做全系统恢复重放 |
| 前端 | 类型、ESLint、Next.js生产构建通过 | [最终原始日志](frontend-final.log)，本轮4个实际路由；只适用新工程候选 |
| 实际浏览器 | 原文登记、事实/真实回执、实质撤回、原文/历史保留、草稿刷新、WorkRequest失能/刷新、准确来源版本、未知标记、键盘办理和确认返回 | [浏览器记录](browser-observations.json)，实际操作只使用合成资料 |
| HTTP/BFF | 未登录API/BFF均401；跨Origin403，合法本机Origin200；会话HttpOnly；浏览器提交的2份来源、active/reverted事实及MODEL_UNAVAILABLE工作状态在权威接口核对一致 | [真实HTTP记录](http-final.json)，没有重放写入或另建演练数据 |
| 响应式/主题 | 1440×1000两栏与320×900单栏，双主题，手机原文/确认可读；两尺寸document宽度无横向溢出 | [桌面亮](desktop-light-final.jpg)、[桌面暗](desktop-dark-final.jpg)、[手机暗](mobile-dark-final.jpg)、[手机亮](mobile-light-final.jpg)、[手机确认](mobile-confirmation.jpg) |

适用 AT 子范围：AT-01 的无项目来源记录；AT-31 的合成资格/独立writer/真实受控DB写入；AT-36 的客户端伪造批准/载荷拒绝；AT-38～42 的授权/幂等/取消/补偿；AT-44 的同工作API实例恢复；AT-45 的默认模型失能和人工可用；AT-46 的来源撤回停止后续命令；AT-48 的合成与真实资格区分。**这些都是局部证据，不将对应整个 AT 标成全部通过。** 未测试真实模型对提示注入的行为，也未冒充真正 Worker/Temporal 重启恢复、所有消费者失效传播或正式资格。

初次检查 23 passed/5 failed：资格表只读权限与 FOR UPDATE 锁冲突，见[初始失败日志](postgres-tests-initial-failure.log)。没有扩大资格写权；增加限定租户的 SECURITY DEFINER 只读锁函数，再重读实际资格并校验全部维度，相关迁移与最终34项通过。浏览器发现 Next内部 localhost 与访问127.0.0.1导致 Origin 比较拒绝合法请求，已改为实际 Host/协议校验；合法请求通过，跨 Origin 仍拒绝。手机确认返回的焦点恢复在最终候选修正和复核，不以旧候选截图冒充最终检查。

## 剩余与续接

1. G0.2/3：真实模型网关、模型出站授权/租户配置/独立评测资格；Temporal独立持久库与Activity、Outbox/Inbox分发、持久LangGraph检查点、预算/租约/重启恢复。当前Run在领域DB保存，短图没有持久checkpointer，默认provider为无，不能称为完整可恢复AI。
2. G0.3/4：私有版本化对象存储、恶意文件检查/隔离解析/PDF与图像；完整T1独立原子组/版本差异、T2具名决定、撤回传播、备份恢复/重放。当前只支持小型UTF-8文本、单条Claim补偿和同工作取消，尚无整Run多动作补偿。
3. 当前会话是限定本机的合成预览入口，尚无生产身份生命周期/登录交互。只有服务器发出的真实会话和产品Grant有效，预览入口不适用于生产。
4. G1～G5按方案接入产品定义、工程/NPI、实物/交接、测试/变更、试产/分别放行、外部生效、Loops、资源和知识；真实资料、工厂角色/结果、集成条件及原适用人工出口分别取得证据。

预览服务和仅本轮容器暂留供查看。后续用 `pdos-next/tools/local_environment.py` 复核、续接或只清理此任务 marker 匹配环境；凭据失效时重新创建合成会话，不访问原存续库或原预览。没有配置定时自动继续任务。
