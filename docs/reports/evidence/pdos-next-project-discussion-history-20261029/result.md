# 项目页本人讨论与当时结果

已补齐 RAG §11.12 的项目回看入口：项目活动中的实际 Run 可通过原 AppShell `openRun` 打开，继续由已有 Run/结果读取路径重核本人范围与 P32 历史可见性，不新建 Run 或推理。项目小Pai的会话列表、会话内运行页、搜索和分页现在携带真实 `project_id`，不会混入同品类其他项目。

服务器在现有 `session_views` / `session_presentation` 读模型中，先核具名本人及当前 Project 普通 RLS，再按实际 Session.project_id 筛选；Run 与其 Session 的项目身份必须相同。过滤先于计数、标题/目标搜索、游标及分页，不以浏览器字段授予身份或读取权。列表只投影元数据，正文与来源沿既有 Run 接口读取，来源更新保留/撤权隐藏规则不变。

显式项目过滤的读取响应回显项目，前端同时核对响应范围及每个实际 Session 的项目；项目或身份切换即时隐藏旧列表，迟到响应不能回填。未选择项目时，旧响应格式保持。会话重命名、置顶、归档及原请求恢复继续使用原写入 URL、正文与请求摘要；仅在前端额外核对实际回执的 Session 项目，不扩展写权限。

直接修改为 2 个后端读模块、9 个前端生产文件及对应测试；[20 个输入的原/新 SHA](source-manifest.json)与[精确 patch](project-discussion-history.patch)列明范围。公共 `api.py` 的原历史 handler 已支持项目过滤，本次无需改动；`conversation.py`、领域事实、迁移、权限策略及已冻结 E 的 15 个文件均未修改。

本地验证：

- [后端纯检查](backend-pure-final.txt)32 项通过；[5 文件 Ruff](ruff-final.txt)通过。SQL 形状测试核实际项目条件、父对象可见性与分页前过滤；不把它当作实际 RLS 通过。
- [前端定向组](frontend-final.txt)117 通过、1 个新增 Activity 测试失败：测试树尚未展开实际纯子组件。仅修正该夹具的遍历后，[Activity 10 项](frontend-activity-fixed.txt)全部通过；最终 **118 个唯一用例**均有通过证据，重叠的 9 项不累计。
- [完整 TypeScript](typecheck-final.txt)、[9 个生产文件 ESLint](eslint-run1.txt)通过。
- [实际 PG nodeid](native-nodeids.json)已在独立 pdos_test 执行，[最终1项](pg-run2.xml)通过。用原领域命令建立两项目，创建本人/peer 的原生 Session/Run，覆盖同品类隔离、搜索、两页游标、别项目游标/详情拒绝、GET 零写入，以及撤权后隐去本人项目会话。第一轮最后撤权夹具失败，原因是第二个G0创建覆盖共享setup.product；[仅改新夹具用copy](native-fixture-delta.json)后严格原撤权helper通过。原生产与旧helper未改。[最终输入](final-inputs.json)。

首轮失败记录保留：[后端](backend-pure-run1.txt)的新 SQL 断言误用 CTE 别名；[前端](frontend-run1.txt)的旧断言仍拒绝新获准的 project 参数，另一个范围切换夹具未回显其实际项目。修正均保留原拒绝、身份切换和请求恢复断言，没有放宽生产校验。

主会话实际 HTTP/PG 与 752 输入生产构建通过（与相似历史组合）；[原生浏览器 run2](browser-final.md)已完成项目活动打开原 Run、当时状态与当前本人项目历史回看，24 张受保护表计数及行摘要保持，新增 Run/Receipt/ToolCall 均为 0。原取消/排队 Run 没有生成结果。浏览器首轮夹具失败、后续通过及截图分别保留；专用服务已清理。未调用真实模型或 embedding，不据合成资料宣称真实质量验收通过。
