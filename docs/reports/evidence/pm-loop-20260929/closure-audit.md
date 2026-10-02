# 产品经理闭环逐项核对与竞品历史比较修复

2026-09-29检查点（工具时间UTC为9月30日），0404工作树。依据唯一清单N1-01～06、N6-04、所需N7-01和完整合同§7、§11核对。前一轮属于实际进展：完成PDF分页修复、浏览器下载及回执核对；本轮不是重复等待外部材料。

## 这次确认并修复的问题

竞品列表已有历史标记，但比较接口只检查所选参数是否同口径、来源是否过期或冲突，没有检查观察记录本身是否已有后续修订。用户打开旧记录或选择后遇到他人追加修订时，旧参数仍可能显示“录入条件一致”。

现在比较时在当前租户、市场空间和产品线可见范围内检查后续修订。旧观察保留原数值、价格和证据，同时在比较行中提示“已有后续修订，请重核参数；本次仍使用所选历史版本”，同口径行转为需复核；原本不可比的行仍不可比。接口返回每条观察的is_latest，不自动换成新版，不改写历史或产生模型调用。页面复用原有原因展示，无前端生产代码或迁移变化。

- [接口10项](../../../../output/pm-closure-audit-0404/competitor-tests.log)：新增真实数据库/接口场景验证同口径原观察→新参数和新报价→原观察比较提示→原值完全保留→显式选择新版→跨空间拒绝及零模型调用；另外9项是现有竞品/市场候选应用、权限和恢复回归。
- [前端5项](../../../../output/pm-closure-audit-0404/frontend.log)：新增选择两条观察并展示服务器版本警告、保留100kPa旧值，其余4项为历史定位/拒绝读取回归。[类型](../../../../output/pm-closure-audit-0404/typecheck.log)、[ESLint](../../../../output/pm-closure-audit-0404/eslint.log)、[ruff](../../../../output/pm-closure-audit-0404/ruff.log)、[受影响源类型](../../../../output/pm-closure-audit-0404/mypy.log)通过。本轮无生产前端变化，未重复前轮完整构建；未宣称完成新浏览器整链或联合门禁。
- 新建独立`pdos-pm-closure-20260930-pg`，仅127.0.0.1:57434/pdos_test；先核对[空库目标](../../../../output/pm-closure-audit-0404/environment.log)，再按仓库脚本准备角色，测试显式TEST_DATABASE_URL，[最终head0404](../../../../output/pm-closure-audit-0404/test-head.log)。57433合成业务链和57432存续库均未操作。

## Word输出可读性

使用前轮已保存的合成发布定义快照和当前产品渲染器生成Word QA样本，不连接数据库、不调用模型，也不冒充新的API保存回执。原规格、引用、专业记录及发布历史逐段与结构化输出核对相等。

通过技能提供的文档转换器及配套LibreOffice渲染，14页全部逐页检查：中文/英文、单位、容差、105～115kPa判据、页眉页脚及跨页审计记录均可读，无裁切和重叠。首次转换器没有加载系统中文字体，产生漏字预览；为检查进程提供任务内字体配置后正常，原DOCX不改动。第一次字体配置中路径的&需XML转义，修正后最终日志无该错误。默认PDF文本提取器会重排中文替代字体片段，因此未将其结果用于声称逐字渲染相等；正文完整性由DOCX原段落对账，版式由逐页图像确认。

[来源与QA模式](../../../../output/pm-closure-audit-0404/word-input.json)、[最终渲染日志](../../../../output/pm-closure-audit-0404/word-final.log)、[结构与视觉记录](../../../../output/pm-closure-audit-0404/word-validation.json)。既有四格式API字节验证见[导出恢复](export-recovery.md)，PDF浏览器及视觉证据见[前轮记录](export-browser.md)。本次没有把合成Word作为真实业务交付，也未检查Word桌面原生程序或Excel/PPT视觉效果。

## 原验收项对账

下表记录证据的适用范围及缺口，不新增状态清单、不关闭原N项。代码存在和合成回归只能证明相应实现，不证明真实业务或模型效果。历史候选证据不能拼接成0404正式联合出口。

| 原项及必须保留的要求 | 当前实现与可用证据 | 尚未证明或下一步 |
|---|---|---|
| N1-01：无Project的八区工作台；真实typed scope、租户/空间/产品线隔离；专业工作分派、提交接收与My Work；旧项目及深链兼容 | product_workspace/catalog、作用域授权、研究及ScopedWorkItem；[准备与运行](runtime.md)、[导航](navigation-publication.md)；test_product_manager_loop_api明确验证专业工作完成且Project计数为0。模型范围由运行绑定。 | 当前候选跨角色真实试用、旧项目迁移及全部父子引用/权限场景的正式验收仍缺，不用一个Owner合成账号代替组织角色。 |
| N1-02：研究计划；真实搜索、GET抓取、订阅；owner/许可/保留/频率；URL/时间/digest/version/taint；去重、冲突、陈旧、超大与失败；SSRF及统一引用范围 | research_search/collection/subscriptions、EvidenceService、固定源读取；[采集恢复](collection-recovery.md)、[研究候选](research-application.md)、test_research_search_provider、test_evidence_api、test_agent_reach_fetch。未配置、无结果和失败分别显示。 | 真实搜索服务和允许查询的主题/网址尚未提供；真实搜索→快照→observation→引用运行、真实订阅变化/失败与该能力独立评测未通过。适用正式出口仍需完整安全验收。 |
| N1-03：具体型号/配置/区域/渠道/价格日期币种；宣传实测区别；同条件比较、未知不可比；原快照跳转、冲突/过期/参数变更提醒、桌面移动 | competitors确定性对比及不可变观察；[竞品候选](evidence-application.md)、[浏览器](browser.md)、[原记录回链](result-navigation.md)；本轮补后续修订提醒及原值保留。 | 真实品类竞品证据和competitor_analysis独立效果评测未通过；历史移动页面证据只覆盖记录范围，非全部异常交互。 |
| N1-04：细分/JTBD/Desired Outcome；TAM/SAM/SOM公式参数；机会分数；至少3方案；四维VUVF、证伪阈值、Owner与结果；Requirement关系和失败保留 | market_analysis.calculate_market、opportunities.score、experiments；[机会/实验应用](discovery-application.md)及test_product_manager_loop_api覆盖三方案不足拒绝、四维证据不足/证伪、未知规模不补值。 | 真实用户/市场参数、实验结果及market_analysis/opportunity_mapping/experiment_design三能力独立评测未通过；需求多对多的完整正式回归仍需在最终候选按影响纳入。 |
| N1-05：九区Canvas逐区；新开发/平台复用/升级三路线；模块成本、NRE和ID周期；事实/假设/决定；DQE/SQE/IE任务或处置；发布版本不可覆盖 | product_strategies.publication_readiness和budget_summary、[策略/定义候选](planning-application.md)；整链验证部分已知成本仍不产出伪总成本，专业工作与明确处置分别保留。 | 真实专业判断和策略选择证据、product_strategy独立评测未通过；合成处置不等于真实专业可行性结论。 |
| N1-06：固定策略版本；稳定规格编号/数值/单位/容差/工况/来源/验证/Owner/状态；版本差异、协审发布替代；Word/PDF；RFQ T1、派生父版锁定及三方接受 | product_definitions、[派生](inheritance.md)、[RFQ](rfq.md)、[发布与父版接受](navigation-publication.md)、[导出](export-browser.md)；本轮Word结构及14页视觉补证。 | RFQ四类的原设计名称尚缺；真实材料、product_definition及RFQ独立评测、真实五专业签核/发布试用未完成。没有将SHADOW解锁。 |
| N6-04：六层产品归属；未立项的发布定义矩阵/路线图；市场覆盖/空白/重叠/复用；循环/重复定位/冲突；组合评分权重参数版本复算；不复制ERP/PLM主数据 | product_catalog、product_matrix、product_matrix_coverage/records、product_roadmap及独立matrix运行；[发布后矩阵与旧路线图变化](navigation-publication.md)。覆盖记录保存快照、公式版本和原判据，可重算。 | **实现核对缺口：**产品覆盖计算仅有match/gap/unknown计数和重叠，没有权重评分。已存在的portfolio_scoring要求Project及项目排程/成本来源，不能直接证明未立项产品组合的加权评分入口已完成。需沿N6-04补版本化参数/权重与独立复算；真实product_matrix评测和产品组合负责人试用亦缺。 |

八能力的提示词/输入/引用/结果合同已接通，最终provider消息字段联验见[wire-context](wire-context.md)；候选离线评测器见[capability-evaluation](capability-evaluation.md)。固定合成响应、字段匹配和离线参考输出都不是独立真实模型资格。

## 后续顺序与边界

先处理已定位的N6-04未立项产品组合评分缺口：核对D24既有公式/政策边界，沿真实产品与发布定义来源接通具名参数、权重版本、缺参未知、历史复算及页面；不使用模型补分，不将项目资源评分冒称产品组合评分。随后在同一收口候选集中补适用联合验证。真实研究服务/公开材料、逐能力真实调用及独立参考评测、真实角色与人工Exit分别待条件，不阻断上述本地实现。

本轮测试、转换进程均已结束。经核对的57434隔离临时库[保留复用](../../../../output/pm-closure-audit-0404/environment-retained.json)，供下一段N6-04实现的相容检查使用；该库没有需保留的浏览器业务样本，不与57433混用。本轮没有生产操作、业务外发、git push或golden-case写入。[源摘要](closure-audit-source-sha256.json)记录本轮相关文件；原清单状态保持部分完成。
