# Wave25 收口证据只读审核 v1

只读指定公共证据、必要原始日志和测试源码，比较 JSON/SHA 与 AST 参数数量；未运行 DB、SQL、HTTP、浏览器、pytest/收集或构建，未修改公共源、清单或报告。

| 声明 | 支持范围与去重规则 |
| --- | --- |
| 591冻结源 | v3为380运行源+42后端测试+165网页+4工具，591个唯一路径；本次首末全部SHA一致，无缺失/重复。HTTP final精确绑定v3 SHA。不是591份均已完成业务验收。 |
| 后端257 | 基线232=Change42+Controlled35+Public22+Combined10+Query7+制造74+制造协议30+Expiry12；新增Definition25，合计257。原布局231PASS/1FAIL由Query7全PASS替代该失败；制造重验140PASS/1FAIL（116旧+25新）由精确Expiry1PASS替代该失败。旧225、Query重复6、制造重复116和Expiry1不累计。当前九文件AST参数展开吻合257；这是分范围影响验证，不是最终591源整树联合验收。 |
| UI39 | 完整raw摘要39 tests/39 pass/0 fail/skip/cancel/todo；parser v2只重新解释原spec摘要，未重跑/新增39。旧检查器错误保留。v1未保存child exit_code；可以登记39原始摘要通过，不能声称归档了该child实际退出0。web checkpoint独立保存lint/build/type三个退出0。 |
| PG47 | Change原29PASS+同名8DELETE权限复验=37，制造10=47；其中2目录、45实际拒绝。原42601失败保留、同名8修正42501。Change13 PENDING与制造真实行/RLS/业务正向/来源race未计通过；探测rollback、16表原baseline前后相同。 |
| HTTP13 | final逐值等于v2成功9+v3 continuation1+v5 continuation3，三段SHA匹配。2 GET200+6精确422+5精确403；v6仅离线整理、无新增HTTP。旧500/DTO/计数失败保留，17表完整摘要前后相同。相同endpoint摘要的两条GET拒绝实际分别是unknown/duplicate query，不是重复请求凑数。 |
| 122实际表 | head28、27/28往返/schema见migration-final checkpoint；原111表全行保持、新11表强制RLS及零行、Agent直接写0。原失败/锁序修复/历史ordinal及numeric格式解释保留；目录/空表负例不证明真实有行RLS或专业保存。 |
| 页面与固定状态 | 165网页构建、320/1280亮暗四个实际viewport读回支持制造草稿表单/私有上游限制/unknown展示。旧品质链实际409 SOURCE_STALE、底层原因未解，不能计通过；无新T1保存/UNKNOWN恢复。共享Issue6、A2 planned1、原窗口不改，11新表/Observation/NamedReview均0；来源当前性和资格不能由行摘要保持推导。 |

不能计通过：正式ChangeOrder/工程制造分别批准/实际实施；实际WI/CP/Baseline T1保存及Current文档回读；八facet真实完整供给；13待办、真实有行跨tenant/private RLS、完整owner原子组/末端故障、来源资格撤回race；公共UNKNOWN恢复；原品质完整读取、实际A2承诺/开测/复测/完整观察、独立NamedReview、有效性/分别关闭、制造放行/Pilot、G3/G4和人工Exit。

HTTP口径是选定实际读取与精确拒绝通过，浏览器口径是制造草稿展示通过且旧品质失效已见。不要把注册/目录/负例通过写成正式变更或制造业务闭环已验证，也不要把有界摘要保持写成全库专业可用。精确输入SHA及计数绑定见同目录 audit-result-v1.json；本审核未新增真实验证项。
