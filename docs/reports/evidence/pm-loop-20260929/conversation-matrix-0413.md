# 产品经理小Pai：矩阵与路线图衔接候选（0413）

2026-09-30。沿产品经理第一主线补齐原矩阵解释服务与同一私人会话的衔接。当前目标仍在进行，未关闭N1、N6-04或N/P/Q人工出口。

页面从保存记录生成带真实Space、Line、record_id的固定链接；完整产品页只读原记录，不以refresh重建来源。小Pai复用0412的conversation/message/operation request，按本人、当前租户与范围列出可见原矩阵；显式选择路线图版本，未选版本保持未读取。矩阵记录与会话Line精确相等，Space共同范围不隐式代选Line记录。改变页签、产品线或空间清除旧目标；同范围改变矩阵选择不另建会话。

保存消息固定kind=matrix、实际record/roadmap selection、来源摘要及用户说明；复用原ProductMatrixRuns与原提示词，无第二Agent或自动业务处置。缺选择或多目标歧义只保存说明和待补提示；普通说明在未配置模型网关时仍可保存。分析派发受原模型资格、当前权限及预算约束。回读核对真实run的作者、版本、范围、selection、原来源及正文摘要；停止、进度与未知响应恢复沿原matrix运行接口，固定原请求，不把新版本替换进旧请求。矩阵解释保留观察、推断、假设、引用及覆盖限制，正式修订/处置/发布走原业务入口。

0413在实施时0412之后单调新增，复用原JSON列及消息动作。新CHECK与metadata一致，拒未知kind或混入附件来源的matrix payload；数据库守卫绑定当前记录范围及原result_digest。矩阵消息禁止私人附件绑定；核对三个同范围对象后先给出矩阵专用拒绝，原work/note/project的通用序列、解析与不可变规则保持。降级遇矩阵消息或命名运行拒退，空历史才恢复0412原CHECK与三个函数。没有新增pdos_agent写权限；离线构造不能证明PL/pgSQL已实际执行。

[25份源候选](../../../../output/pm-conversation-matrix-0413/source-candidate.json)与[验证摘要](../../../../output/pm-conversation-matrix-0413/verification.json)固定本轮覆盖：

- [107项后端纯检查](../../../../output/pm-conversation-matrix-0413/backend-pure.xml)通过，涵盖原私人会话/附件、矩阵选择/幂等/回执/派发、两版离线迁移及0413/414步源链。附件守卫顺序改动后，[4项0413离线检查](../../../../output/pm-conversation-matrix-0413/backend-final-migration.xml)再通过，是同一组4项而非额外计数。网络与Engine.connect拒绝探针开启；无数据库访问。
- 前端[原组合54项](../../../../output/pm-conversation-matrix-0413/frontend-components.json)中未变化的44项及[最终父入口11项](../../../../output/pm-conversation-matrix-0413/frontend-workspace.json)共55项不同检查通过。真实组件覆盖选择/路线图、原请求未知恢复、引用及假设展示、停止/进度撤权、记录深链和父导航。生产前端[最终类型](../../../../output/pm-conversation-matrix-0413/frontend-final-types.log)、[14文件lint](../../../../output/pm-conversation-matrix-0413/frontend-final-lint.log)，以及[11文件后端严格类型](../../../../output/pm-conversation-matrix-0413/backend-final-types.log)、lint/格式通过；follow-imports=silent不代表全后端导入诊断通过。
- 1062份前端源的[独立冻结清单](../../../../output/pm-conversation-matrix-0413/web-build/source-manifest.json)完成[真实Next/Geist生产构建](../../../../output/pm-conversation-matrix-0413/web-build/build.log)。7份本轮前端运行源均与快照一致；冻结后仅父入口测试补正确Page夹具并改用矩阵页实际页签控件，最终11项/类型/lint已过，原失败日志保留。仅此测试文件与构建快照不同，不重复构建或声称全部测试源字节相同。
- 自有临时前端[9项真实未登录HTTP检查](../../../../output/pm-conversation-matrix-0413/web-build/http-checks.json)通过并停服：7条合法路径401（含matrix-options）、非法扩展404均no-store，未支持PUT为405。无cookie/令牌、业务后端禁用；不是合法登录、数据库或业务浏览器证明。

[新增8项矩阵PG/API](../../../../server/tests/test_conversation_matrix_api.py)及[原11项会话PG/API](../../../../server/tests/test_product_conversations_api.py)共19项[仅收集](../../../../output/pm-conversation-matrix-0413/backend-pg-collection.log)，未运行夹具/正文。完整领域种子经原API准备矩阵/路线图；待验证本人及精确Line选项、固定输入/重试、未合资格保留消息、伪造原结果/未知kind/附件绑定SQL拒绝，以及保史DO拒退。DO保护块不代表CLI真实往返。强保留库护栏已导入，须协调明确分配并核对独立临时pdos_test后执行。

下一步集中冻结届时真实head，实际升级/往返/schema、会话/矩阵/附件19项、PIE恢复、0409/0408/0407及完整PM登录HTTP/浏览器联验。跨会话发送授权仍待人类回复，工具要求明确人类授权；未发送，57440未分配本会话。真实研究/搜索与允许材料、计量/模型资格和独立人工参考、RFQ原名称、具名专业协审、外部主数据原件及人工Exit仍待齐。原[0412证据](product-conversations-0412.md)保持历史覆盖；本轮源head0413，数据库版本未验证，未连接存续库、调用模型、授资格、推送或外发。
