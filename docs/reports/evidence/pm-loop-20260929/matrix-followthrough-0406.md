# 矩阵处置到实际修订与工作接收

2026-09-30，0406工作树；归属N6-04并验证N1-06定义发布和立项前工作接收的回链。产品经理仍为第一开发主线。

## 修复与可用行为

实际接口链发现：完成指定接收人的工作验收、发布新定义后，首次保存落实结果仍报 PostgreSQL `operator is not unique: unknown - unknown`。0350的结果守卫没有将JSON提取表达式括起，`NEW.source_snapshot->'disposition' - 'created_at'`产生运算歧义。

0406仅给提取表达式加括号，沿当前0405真实head追加；迁移核对原函数中的唯一匹配，保留原处置、时间、范围、摘要、顺序及不可变历史约束。已有结果时禁止回退到原失效守卫；空结果库可往返。

页面的具名处置和实际结果现在保留完整原请求：响应丢失后提供明确重试入口，冻结原摘要、请求编号和新建工作请求编号。刷新来源不会改写待核对请求；已收到保存回执而历史刷新失败时保留回执，提示刷新历史。401/403清除所涉面板的旧记录和草稿；切换市场空间/记录/处置时重置面板。此证据覆盖三个矩阵子面板，不能推论全部产品工作台撤权恢复均已验证。

## 验证证据

- [实际接口回链](../../../../output/pm-matrix-followthrough-0405/followthrough-final.log)：1项整链通过，分别办理定义和路线图修订。原研究、三方案/实验、策略、定义和矩阵通过真实领域接口创建；负责人不能冒充指定接收人，未接收/未发布处置后修订/仅假设/扩大到未修订产品均拒绝。实际发布后可确认所选产品，其余产品明确保留未核对；重复请求返回原回执，过期版本与改写请求拒绝；查看者不能登记，撤销产品线权限后历史读取拒绝。
- 同项检查数据库守卫拒绝篡改原处置、时间、摘要、范围和顺序，结果历史禁止覆盖，有数据降级拒绝。空库迁移往返与单调链核对已通过，见[前次检查日志](../../../../output/pm-matrix-followthrough-0405/backend.log)。该日志整次为2通过、1失败（测试路线图修订遗漏原节点）；保留原节点后整链单项重新通过。没有把失败运行称为全绿。
- [前端恢复9项](../../../../output/pm-matrix-followthrough-0405/frontend.log)、[前端lint](../../../../output/pm-matrix-followthrough-0405/eslint.log)、[后端lint](../../../../output/pm-matrix-followthrough-0405/ruff.log)和[当前页面生产构建](../../../../output/pm-matrix-followthrough-0405/build.log)通过。
- 浏览器从已保存矩阵打开实际处置和已核对结果。故意在服务端返回200后中断响应，刷新历史再重试：[结果请求](../../../../output/playwright/pm-matrix-followthrough-0406/uncertain-save.log)两次完整载荷相同、回执相同、版本均2；[创建工作请求](../../../../output/playwright/pm-matrix-followthrough-0406/disposition-recovery.log)两次载荷/处置/工作相同、版本均1。[页面未确认状态](../../../../output/playwright/pm-matrix-followthrough-0406/uncertain-save.png)和[工作恢复回执](../../../../output/playwright/pm-matrix-followthrough-0406/disposition-recovered.png)已视觉核对。控制台两条网络错误对应两次故意中断，见[控制台](../../../../output/playwright/pm-matrix-followthrough-0406/console.log)。首次登录脚本等待了错误的目标页导致观察超时，登录本身成功；随后进入实际产品工作台完成验证。
- [数据库回执计数](../../../../output/pm-matrix-followthrough-0405/validated-receipts.json)：3处置、3结果、2发布关联，恢复测试工作仅1份；Project和模型调用均0。两条验证结果关联定义v2和路线图v2，浏览器另追加一条待核对进展；没有把浏览器恢复测试作为新增业务落实。

## 数据与收尾

只用已核对的独立57434/pdos_test。清理测试租户前已有[完整备份](../../../../output/pm-matrix-followthrough-0405/pre-tests.dump)；本次回链及浏览器样本另存[完整备份](../../../../output/pm-matrix-followthrough-0405/validated-followthrough.dump)，结构化回执在同目录保留。然后恢复原备份、升级0406：[恢复日志](../../../../output/pm-matrix-followthrough-0405/restore.log)、[升级日志](../../../../output/pm-matrix-followthrough-0405/restored-upgrade.log)、[核对](../../../../output/pm-matrix-followthrough-0405/restore-verification.json)。原五版的输入、结果、摘要、版本链和创建时间与0405保留样本相同。57434现仍有需保留的五版样本，不是可直接清理的空库。

本轮API、页面及浏览器已停止。真实研究来源、八能力独立真实评测/资格、真实角色验收、RFQ四类原名称及规定人工Exit仍待原条件；N项保持部分完成。本证据是受影响业务闭环检查点，不替代正式联合门禁，也不解锁SHADOW。
