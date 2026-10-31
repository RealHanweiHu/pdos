# 12道上下文候选的原生控制回放

上一检查点已完成三项实现差异及其本地验证。本轮直接补评测题的原生绑定、合法上下文准入与机制回放，不重跑未变化的整组检查，不调用真实模型。

| 归属 | 文件 | 场景 |
| --- | --- | --- |
| Sol xhigh history/state | tests/agent_kernel/test_eval_v0_history_state_pg.py；独立 support | CTX-01/04/05/06/07/10 |
| Sol xhigh source/context | tests/enterprise_search/test_eval_v0_source_context_pg.py | CTX-02/03/08/12 |
| Sol xhigh handle/candidate | tests/agent_kernel/test_eval_v0_handle_candidate_pg.py | CTX-09/11 |
| 主会话 | tools/xiaopai_context_native_baseline.py、汇总检查与集中数据库运行 | 两档F共24格 |

所有题干、事实锚点与可信题集保持原状。脚本端只驱动受控流程；READ、引用、句柄、候选、回执与工作状态取实际服务器记录。控制回放不赋答案/引用语义分，不用脚本usage冒充真实计量。

CTX-09题内每页3条不是生产json_fragment分页的现有合同，须记录实际覆盖、同句柄第三页失败和未绑定的条目对齐假设，不能制造“6/9已读”。CTX-12经合法隔离后若未形成压力，明确没有两档压力对照。CTX-08在撤权后才创建合法续轮，保持同会话原话而不发送旧私有正文。

主会话在现有核对后的53502/pdos_test上统一运行；代理不连接数据库、不改生产实现。候选正式审阅和真实模型质量仍待后续。

## 已确认的问题

- 首个source回放的记录器混入框架emit回调，已改为只捕获四个provider输入字段；6项相关纯检查通过，实际组复验中，首轮失败保留。
- CTX-09在普通时钟下实际第二页返回SOURCE_STALE（见ctx09-clock-reproduction2/native.xml），原因是列表顶层as_of每次生成，普通读取恢复把观测时间变化当成正文变化。已为明确登记的parameters/knowledge/competitors列表添加窄恢复适配；原READ、ACL与其它内容摘要比较保留，不冻结时钟、不泛化忽略外部字段。82项受影响纯检查、3项实际时钟/变更/撤权回归、CTX-09两档实际控制及4项既有分页回归通过，证据分别见pure-final.xml、clock-candidate-run1/native.xml和continuation-regression-final/native.xml；其中clock组另有CTX-11夹具断言失败，未记全组通过。
- CTX-11在F48000下实际准入50185 > 48000，派发和候选均为0；这是正确的容量停止。保留ctx11-f48000-diagnostic.json，较大F仍验证完整候选链。修正观测器区分主循环事件和隔离子图的完整模型账本，不把子图派发遗漏掉。
- CTX-12固定选择八份资料的原生父/续轮STATE为1436/1681，固定选择元数据单项898，超过STATE1500；保留ctx12-state-diagnostic.json及首次partial观察。另按原题允许的普通品类检索绑定八份资料，使用实际两批隔离读取和READ范围覆盖验证，不改题干、F、STATE上限或权限。
- CTX-11较大F实际生成旧pending候选后，新续轮触发真实context_schema_mismatch：work_state候选白名单已有kind/operation/state/receipt_id，资料schema漏登记。已仅补schema的这四字段、保持枚举/null和additionalProperties=false；27项新增纯回归覆盖合法候选与私有/未知字段拒绝。修复后174项受影响纯检查与11个Python文件Ruff通过，见pure-frozen-final2/pure.xml、ruff-frozen-final.txt。前次pure组误混3个PG入口且缺显式环境的错误保留在pure-frozen-final，不算原生验证通过。
- CTX-04两档项目引用复验通过（场景日期字段仍明确partial）。CTX-12普通读取变体的STATE751正常，F48000最终admission48298而停止，F64000完成八份各4695字符正文的真实区间并集覆盖，见project-source-focused-run3（4项控制通过，未冒充4个完整绑定）。

## 冻结候选

native-candidate2已完成12题×两档的完整回放：34项检查通过、24格观察齐全，18完整绑定/5部分/1预算不足；原六项等17项补验通过，去重为174纯检查＋41原生控制/回归。856项生产Python、运行框架、技能schema/正文、夹具、物化工具和原题输入在回放及补验前后哈希一致。frozen-source-manifest.json另保留本次直接涉及的13项输入摘要；[最终结果与未完成边界](result.md)、native-candidate2/baseline.json和final-checkpoint.json为本检查点证据。真实模型和embedding保持关闭。

首次整组native-candidate1在发现CTX-11夹具错误后主动中止，退出2、0/24观察；唯一遗留排队Run已由普通取消命令取消，合成数据保留，见interruption-cleanup.json。该轮不是最终候选通过证据。
