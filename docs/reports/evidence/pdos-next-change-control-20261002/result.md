# PDOS Next G3 双线变更独立首版

已完成可调用的ChangeRequest、固定ImpactAssessment、ChangeOrder、EffectivityPlan、实施/实际生效/独立复核及关闭规则与授权读模型，封闭DTO/调用者Session ports、typed办理组件均已交付。公共入口与实际持久适配尚未接线。

固定候选SHA-256：`f53cb889ceda0c539487f0bbae25142630e3bfa196761f3fdbdb15a5a1886fa3`；18份独占源码/测试/组件文件的逐文件hash见[candidate.json](candidate.json)。

## 已实现能力

- 有出处的工程/制造双线遍历，固定版本/来源/受众/有效期，逐节点缺边或覆盖不完整保留UNKNOWN；AI推测独立，不补造影响边。全部已知影响逐项Disposition，未知不批准。
- draft→analysis→review→approved→implementing→verifying→closed；工程/制造及政策要求的客户/法规分别具名决定。批准不自动实施、生效、验证或关闭，AI/自批拒绝。
- T1人类实施记录复用共同一次确认，实际owner固定输出与本人/时钟匹配；新配置/Build/Run/ERP-MES只有受控意图和固定引用，不覆盖旧配置或原测量。
- 生效精确到对象/批次/序号/条件，sent/accepted/effective分开，部分/失败/未知不算全生效；重复fact不增历史/业务事件，原始回执不能换ID重复导入。
- 未知执行/回执仅通过服务器核验的同一次reconciles_id关系恢复，原未知历史保留，不盲重发。独立复核须覆盖新输出/全部范围、真实观察与当前适用性；提出/批准/实施/测量执行者不能自证，关闭再次具名重验。
- 精确来源、配置、图快照本身、政策和期限变化阻止新操作；读模型仍保留历史并标待重核。重核记录→新根/来源修订→重新分析/决定，不恢复旧批准。
- 前端分栏呈现双线影响/AI推测/UNKNOWN，实施、生效、复核、关闭分别展示；所有事实来自服务器typed投影。父提供共同sharedReview，无第二确认/业务权威，合成fixture不导出到生产组件入口。

## 验证与证据

105项后端纯合成检查通过，原输出[backend-pytest.txt](backend-pytest.txt)；领域/schema/测试Ruff无cache通过，[backend-ruff.txt](backend-ruff.txt)。覆盖缺边/覆盖UNKNOWN、跨范围/受众、来源和图/配置漂移、AI/自批、共同proof一次消费/过期、稳定意图/重复回执、CAS冲突、同调用者事务失败全回滚、实施失败/未知对账、部分生效、独立复核不足与历史关闭失效。

22项局部组件/候选合成检查、非incremental/noEmit TypeScript、ESLint无cache通过，原输出及范围见[ui-checks.md](ui-checks.md)。前端子候选和共同预览接线边界见[ui-result.md](ui-result.md)、[ui-integration.md](ui-integration.md)。全部检查汇总为[checks.json](checks.json)，计数属于各自局部检查，不相加为联合业务验收。

消费接口最终复核见[consumption-summary.md](consumption-summary.md)：共同contracts.py同期新增品质准备动作，Command/SourceRead消费信封保持，本包不导入共同注册；其他后端与既有前端消费接口未发现漂移。不是共享树冻结证据。

## 未接线与事务恢复边界

需要主线统一实现实际Session/权限/资格/来源/graph/selection/owner实施与回执/独立品质事实/policy适配；ORM/RLS/迁移、共同命令注册及T1/T2 proof、API/BFF/父页面、失效传播、真实新对象办理和ERP/MES受控对账。四个canonical动作保留原分级，另六个动作仅registry候选，不自行授T0资格或AI T2权力。

record合同要求CAS、完整读集/取消/资格/证明期限重验，所有领域事实、确认消费、导入身份映射、ActionReceipt、Audit、Outbox同Session原子提交；异常全部回滚，不自行commit。合成fake验证该合同的调用与恢复，不证明真实数据库事务已接通。真实所有者创建/外发独立于本包记录，结果未知先核对原意图。

具体接线项、对象映射和最低联合验收见[integration.md](integration.md)。没有连接数据库/共享服务、读取.env/.local/真实凭据、启停服务、写共享.next、安装依赖/全构建、调用真实模型、操作原件/外发/云/生产或git commit/push；未修改共同文件、他包或唯一清单。未执行DB/HTTP/浏览器及G/N/P/Q正式出口，主线接线条件未齐部分明确待接，不宣称实际业务生效或全系统完成。
