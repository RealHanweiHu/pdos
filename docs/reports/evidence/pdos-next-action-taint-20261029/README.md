# Frozen action source classification delta

仅 `/tmp` 候选，无 live/DB/服务/模型调用。5 shared +3 new；无迁移。manifest 列表为唯一应用范围；shared.patch 只含公共小 delta。

基线为已合 CTA + B/D13 的实际文件，action_sources 已以当前 579e8eff… 重新叠加，完整保留 D SOURCE_TABLES/role_native_audience。各文件 baseSHA 见 manifest。

- capture 默认旧 proof 字段和 digest 不变，recheck 按冻结 proof 有无 taint 重建相同合同；只有服务器新 prepare_start 请求包含实际全 footprint 的 private/customer_original 分类。
- 新 verification/work action 通过原 conversation.merge_binding 既有显式绑定端口合并分类，保留已有类别/客户身份；讨论 citation、execution refs、read_sources、context_selection、READ ledger 不扩张。
- 模型调用前仅冻结 action Run 经现 direct-parent proof 重新读取全 actual footprint/current；撤权/来源变化沿原 guard 拒绝。Run 初始分类不涵盖当前完整分类时，使用既有 CONVERSATION_HISTORY_REVOKED→FORBIDDEN_SCOPE 并明确从原讨论重新续接。无运行时补写 Run 或泛化继承。
- 普通无 action Run 保留原 ledger.carried/current 分类路径。旧 proof 仍可按原形读取；旧 Run 如缺必要分类不能继续模型调用，须明确重新续接。

验证：105 pure 通过（pure.txt），显式配置 Ruff 8 文件通过（ruff.txt）；新增 PG/Temporal 1 个 nodeid 仅成功收集（pg-collect.txt），未实际执行。新用例原生命令上传/扫描/解析客户原件，父 Run 实际检索但未引用；私人 Build child 真实保存 private_context/customer_original，同时不把客户原件加入所选 sources，随后由真实 internal-only DPA 在首次 provider claim 前拒绝。观察 wrapper 调用实际 gateway.egress，不伪造成功回执。

root 应在真实独立 pdos_test/Temporal/checkpoint 环境运行 manifest.nodeids，并回归现 I14 的私人合法目标/撤权/原 action tests；本包不宣称实际 PG 通过。无真实 provider、资格或领域操作档位变化。
