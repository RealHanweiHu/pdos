# 候选保存、父组件刷新与访问拒绝：独立静态复核 v1

本记录只绑定下列当前源码的只读审阅。C 未运行浏览器、HTTP、数据库、测试或公共构建，未修改生产源码；不能用此记录替代实际页面或 ACL 演练。Root 的较早 v3 构建发生在晚到分支补丁前，不能冒充本文最终字节的构建结果。

| 文件 | SHA-256 |
| --- | --- |
| pdos-next/web/src/components/capa-effectiveness/candidate-panel.tsx | 4b73effa8b92de638467e25e6c5f3113148aee01a3589c633e7fb41d9061b88c |
| pdos-next/web/src/components/builds/build-quality-followup.tsx | 50082c286a2657906841162e2ef4c1b2d79fe232b369ae9a6710cfddcd8d0d4e |
| pdos-next/web/src/components/capa-effectiveness/candidate-workflow.tsx | a8fec27619378b5b8ab188c436437be4fdc768cca9acadaff63e1da9f46e849d |
| pdos-next/web/src/components/capa-effectiveness/candidate-workflow-state.ts | ec557e29115ade7523737a3b9d066efde5922ae3105e6870a97dc299351e9197 |

## 保存与刷新顺序

`candidate-workflow.tsx:143–155` 先校验真实 Receipt，调用 `save(candidateSaved(...))`，再进入刷新。`candidate-workflow-state.ts:202–209` 将 pending/草稿清空、保留 savedReceipt、outcome=saved；普通刷新异常不得退回 UNKNOWN。`candidate-workflow.tsx:63–67` 先写内存和 localStorage，后更新 React 状态；浏览器存储不可写时仅内存恢复仍在，不能宣称跨重载持久化成功。

其后 `candidate-panel.tsx:121–125` 先调用父 onSaved，再读取候选历史；父 `build-quality-followup.tsx:76–80` 先刷新当前整改事实，确认返回非空，再调用 Workspace onSaved。父完整刷新依次读取 builds/workspace、本轮 quality-execution、单 Issue quality-followup，Workspace onSaved 再刷新 workspace，最后子 Panel GET capa-candidates。任一步拒绝或失败都会阻止后续读取，不撤销已取得回执。

普通读取失败时，Workflow 的 saved 分支只显示“已取得保存回执；随后刷新失败，请只重试读取，不能重复提交。”pending 已清，不出现原提交恢复按钮；readRequired 仍锁新表单。恢复本机已保存状态也只要求读取（workflow:99–102）。明确 UNKNOWN 则保留原完整请求，普通网络失败或普通 409 不会解锁。

## 已发现并修复的父子边界

1. **已保存后失去访问**：原实现只在将卸载的子 Panel 内保留 savedHint，父 clearSensitive 清空 data 后提示消失。最终 `candidate-panel.tsx:72–77` 将 saved 布尔传给父；父 `build-quality-followup.tsx:62–68` 清私有材料后保留最低成功提示。Receipt、原文、请求或旧 Issue 标识不传回父提示。
2. **拒绝后旧提交回执晚到**：最终 `candidate-panel.tsx:108–120` 在 denied 且收到合法 Receipt 时，仍存活则仅设置提示；已卸载则传 `(true, true)`。父先检查自身 alive；旧 actor/product 的父实例已卸载时忽略。存活父对 late 不再 clearSensitive，只设置通用 saved 提示，保住后来选择的 Issue、草稿及 UNKNOWN 请求。Workflow 原私有内容不因此复活，也不写回已删除的本机请求。
3. **父候选锁遗留**：拒绝卸载子组件时不能依赖子 pending=null 的 passive effect 一定到达。最终父 `clearSensitive:61` 显式 setCandidateLocked(false)，同时保持 readFailed=true、空范围/空材料。该释放只发生于明确清私有上下文；不是普通 UNKNOWN 解锁，不授予服务器能力。

最终上述路径未见新增必须修复的静态阻塞。late=true 仅出自实际合法 Receipt 分支，不是可由表单勾选的保存判断；它不触发 preview、execute 或新请求。实际权限撤回、网络延迟及 React 卸载次序仍须 Root 页面验证。

## 页面应看到的文字与只读控件

- 正常保存：Workflow:153 的“候选已保存或读取原回执；适用性、独立核验和观察完整性仍待核对，未决定有效性或关闭。”及 :209 的第 1 版候选回执提示；无“按原请求恢复”按钮。
- 历史回读：Panel:139–148 的“已保存的固定候选”、候选第 1 版/待核对、服务器接收记录及三项未知；不出现有效性或关闭办理按钮。
- 普通刷新失败：保存提示优先，表单仍锁。Panel:126–130 的“读取当前候选事实”仅调用 GET；Workflow:176–181/:199 的“重试读取当前事实”同样仅调用 Panel read。二者不调用 inputs、preview 或 commands。
- 访问拒绝或晚到成功：父显示“候选已取得保存结果；当前访问已不可用，不能重发已保存操作。”私有材料、预览和本机请求已清，不保留 Receipt/来源详情。

一个当前交互区别保留：外层“读取当前候选事实”只刷新历史，不直接清 Workflow 内部 readRequired；内部“重试读取当前事实”成功才清该门闩。它不会重复写，但验证时应区分两个按钮，不把外层 GET 成功等同于解除本机保存后读取要求。

实际 v6 13 键业务解析与微秒对齐另见 `actual-candidate-business-review-v1.json`；该证据只说明业务材料阅读完整，不说明本记录的访问拒绝分支已在浏览器发生。
