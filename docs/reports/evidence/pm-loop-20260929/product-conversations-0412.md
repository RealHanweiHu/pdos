# 产品经理小Pai：私人会话、附件与产品运行候选（0412）

2026-09-30。按当前队列的小Pai定位补齐产品研究入口；本轮有实质实现进展，目标保持active，不宣称产品经理全链或人工出口完成。

同一会话体系新增personal、market_space、product_line范围，项目旧会话兼容。服务器重新核对当前租户、用户、岗位及Space/Line权限，非项目历史仅创建者可见，范围与请求不可变。页面携实际范围/业务来源，不把可见文字或模型传参当授权；切换范围新建/恢复该范围会话，已提交请求及迟到响应固定原范围。

PDF/XLSX复用原私人对象储存、解析、分类、撤回与消息关联。personal支持私人暂存；产品分析只用同会话、同已授权Space/Line的internal、已解析且未撤回原文。选定片段保留SHA、解析版本、原文定位及局部覆盖，不能推断整件。机密/受限资料不交给此模型；邮件子件、OCR及私人资料自动转为共享业务来源未扩展。

自然目标沿原ProductWorkRuns办理研究规划、RFQ抽取、竞品、市场、机会、实验、策略或定义分析；多目标歧义、缺产品线或原件时保存说明并列待补项。消息先保存固定selection/摘要/操作请求，模型派发仍受真实资格、权限、计量与预算约束。回读核对实际run的作者、范围、输入、原来源及摘要；来源撤回后不展示派生结果。结果分项、引用、缺项和下一步可见，停止复用原运行接口，未知响应只恢复原请求。没有新增Agent管线或自动接受、应用、发布、外发；产品矩阵及正式办理继续原业务入口。

0412是实施时0411之后的新迁移，五张既有表支持可空project并补不依赖NULL的严格父子FK、typed scope及不可变守卫。保留0395项目共享/EML及0177绑定规则；PM运行核对固定来源与消息附件集合。降级遇非项目历史即拒绝，不删历史；没有给pdos_agent增加业务表写权限。旧项目专用动作不能借NULL project绕过范围。

验证以[25份源候选](../../../../output/pm-product-conversations-0412/source-candidate.json)及[验证摘要](../../../../output/pm-product-conversations-0412/verification.json)为准：

- [129项后端纯检查](../../../../output/pm-product-conversations-0412/backend-pure.xml)通过，含新范围/权限/幂等/来源行为、附件及旧产品合同回归；其中4项是离线DDL/metadata/旧守卫快照检查，1项是0412/413步源迁移链。网络和Engine.connect设拒绝探针，未执行数据库。
- [44项组件/BFF检查](../../../../output/pm-product-conversations-0412/frontend-components.json)及[2项跨入口恢复检查](../../../../output/pm-product-conversations-0412/frontend-scope.json)通过；包含PIE表单与产品页导航/权限回归。全前端[类型](../../../../output/pm-product-conversations-0412/frontend-types.log)、[所属lint](../../../../output/pm-product-conversations-0412/frontend-lint.log)及14份后端严格类型/lint通过；后端follow-imports=silent不代表所有导入文件均检查。
- 1061份前端源的[独立快照](../../../../output/pm-product-conversations-0412/web-build/source-manifest.json)已用真实Next 16.3.3/Geist完成[生产构建](../../../../output/pm-product-conversations-0412/web-build/build.log)，无字体mock。自有临时前端[8项真实HTTP](../../../../output/pm-product-conversations-0412/web-build/http-checks.json)通过并停服：无cookie/令牌，业务后端禁用；6条合法路径401、非法扩展404均no-store，未支持PUT为405。不是合法登录、数据库、standalone部署或业务浏览器证明。
- 首次集中检查发现运行来源正文未重新验摘要、测试哨兵撞覆盖提示、两处前端类型错误及旧测试无效Line，均修复后复核。未构建的[被拒初快照](../../../../output/pm-product-conversations-0412/web-build/initial-rejected.json)保留，最终构建不继承失败检查。

[11项PG/API场景](../../../../server/tests/test_product_conversations_api.py)仅收集，未运行夹具/正文；附保留库地址护栏。覆盖真实授权/撤权恢复、历史保全、NULL范围FK及PM运行守卫，须在协调明确分配且核对的独立临时pdos_test执行。还须将0412实际CLI升级/往返/schema、0409的14项数据库场景、0408的8项API、0407来源恢复、PIE新旧运行恢复与合法登录页面整链汇入同一联合候选；历史分散检查不能替代当前完整出口。

只读观察到“估算执行计划完成时间”已完成供应/排程本地检查并备份停止其临时环境；该证据不覆盖本PM候选或分配57440。跨会话发送授权仍待人类回复，未发送；未连接任何数据库，不重复探测未变化的材料/模型条件。真实搜索与允许材料、计量/调用授权、八能力独立人工参考/原始调用、RFQ原名称、具名专业协审、外部主数据原件和人工Exit仍待齐；N/P/Q保持原状态。
