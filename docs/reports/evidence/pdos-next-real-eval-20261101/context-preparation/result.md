# 12 题真实上下文回放准备

本目录只保存准备与纯检查证据。真实数据库连接、HTTP 请求、Temporal 执行、模型和 embedding 调用均为 **0**；没有答案质量、缓存命中、时延或费用通过结论。真实执行与实际运行参数由主会话统一保存。

新增 [准备脚本](../../../../../pdos-next/tools/xiaopai_real_context_fixtures.py)，复用现有原生来源、知识版本、项目计划/任务及工作状态操作。实际模型调用必须走正常 `HTTP → Temporal → Activity → LangGraph`，不复用旧测试中的 `AgentKernel.execute`、scripted provider 或 `KernelStore.finish`。每条原用户输入单独建 Run 并续接；题内 assistant/tool 文本不作为模型消息注入。CTX-11 另有一个与旧原生夹具相同的、真实模型执行的明确资料读取前置轮。

| 题 | 可复用原生路径 | 本次准备与必要门槛 |
| --- | --- | --- |
| CTX-01 | `test_eval_v0_history_state_pg.py::ctx01` | 按冻结展开 SHA256 逐轮发送 30 条原用户输入，再发 final，共每档 31 个 Run；原始助手答案不注入。早期来源原件另行登记，需模型自行历史续读/重读。 |
| CTX-02 | `test_eval_v0_source_context_pg.py::documents/register_sources` | 登记三份可读原件，保持温湿条件与根因未知；原件声称版本和 Artifact snapshot revision 分别记录。 |
| CTX-03 | 同上 | V-017 v2、V-017 v1、V-071 v4 均为原件；只据实际编号通道、READ 和 citation 评估选择。 |
| CTX-04 | `ctx04`、`eval_v0_ctx04_plan_support.py::native_plan` | Human 原生命令建立 P8、独立 P9、Plan/PlanTask 与两项 WorkTask；耐压项具名分派、建议日期来自真实 forecast；无 commitment。题内周柯映射到真实合成人员 ID。 |
| CTX-05 | `ctx05`、`select_context` | A-17 v1、A-71 v2 知识原件及版本真实；逐轮用本人工作状态 `replace_focus`，不改写模型历史或约束。 |
| CTX-06 | `ctx06`、`change` | 三月/九月同 lineage；另建无权私有原件。须先有实际已携带的旧来源 citation，才能原生 exclude，再在用户删除轮前 remove；未取得 citation 则阻塞此情境。 |
| CTX-07 | `ctx07`、`knowledge` | 首轮必须实际 READ v1，随后 Human 追加同 lineage v2；不倒退当前指针、不重写 v1，不伪造题内读取日期为实际时钟。 |
| CTX-08 | `register_sources` + 原夹具的 `ObjectAudience` 控制 | 必须证明公开与私人原件都实际 READ、私人资料确实 carried、最终 citation 未含私人，且实际历史回答有私人派生内容；再删除该合成 audience。缺前置就 blocked，不伪造私人历史。撤权后全部请求/工作状态及答案须检查。 |
| CTX-09 | `eval_v0_ctx09_directory_support.py::native_directory` | 原题仍 **partial / needs_case_revision**。自然九项完整结果不是“三项一页”，不制造第三页失败、不修改题目、不据当前完整读取追认原题通过；可独立观测现机制。 |
| CTX-10 | `ctx10`、真实工作状态读取 | 须实际登记恰好 24 条逐字约束、计量大于 1500 且标 `context_incomplete`；最终为服务器控制、预期零模型派发。真实模型未登记齐时 blocked，不复用旧脚本 finish 灌入。 |
| CTX-11 | `test_eval_v0_handle_candidate_pg.py` 的实际来源/候选路径 | 真实读取前置轮取得 citation 后走 `work_followup_action`；旧新候选均需实际 GET 证据，旧 pending 保持，assignment 留空，不调用采用/确认。必须核实 work_management 已启用、无 T0，并核 create/assign 回执增量为零。 |
| CTX-12 | `documents/ctx12_queries` 与原 category-read 夹具 | 八份各32段的冻结文档直接登记为不可信原件，交正常隔离图读取；不把八份正文或题内工具消息平铺主模型。采用品类读取、final `lookup_depth=deep`，不显式 pin 八项绕过1500工作状态上限；完整读取需按实际区间并集核验。 |

CTX-03/08 本批默认使用品类 HTTP 入口隔离场景；旧 scripted 夹具使用个人入口。该执行差异必须保留在实际批次记录。每格应使用独立合成品类/等价 ACL 范围，避免同租户的重复原件影响另一档检索；CTX-07 不允许把已更新 lineage 的 current 指针倒回。所有模型、提示、工具/schema、采样、输出上限、语料和逻辑 ACL 应成对固定；逐轮真实生成的历史/状态可能不同，须保存实际 digest 并作为比较限制，不能宣称两档拥有相同生成历史。

F 两档只声明 `W=54048/70048`，`max_output_tokens=2048`，保留 4000 工具 reserve 与1500工作状态上限。由主会话经原配置 T1 入口分批切换路线；旧 Run 必须 terminal，不旁路网关，不把候选准备视为 T0 或 golden 资格。

真实逐轮前置仍有执行风险：CTX-06 首轮可能没有读取已排除历史，CTX-08 首句可能没有产生私人派生历史；缺少这些实际事实时应记 fixture blocked。CTX-10 的24条原句共2544字符，本地估算原句数组为2262tokens、逐条 run_id/text proposals 为2622tokens，真实服务商 token 尚未验证；固定输出2048可能使完整登记失败，不能因此擅自增加输出cap或补造状态。

10 项纯检查通过：冻结展开、用户逐轮而非平铺、两档仅预算差异、CTX-09不能升级为完整绑定、候选依赖实际 citation、CTX-12保留隔离与状态上限、数据库目标守卫。Ruff 通过。纯检查不验证真实 Human 命令、权限撤销传播或模型表现；这些由主会话执行并保留实际证据。

使用接口及 required previous 字段见 [runner-contract.md](runner-contract.md)。离线生成的24格计划见 [run-specs.final.json](run-specs.final.json)。
